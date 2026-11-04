"""Outbound notifications: webhook (HMAC-signed JSON) and e-mail (SMTP).

Events are queued and delivered by a background worker with retries, so a slow
or unreachable receiver never blocks telemetry or control. Every attempt is
recorded in notification_deliveries.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import smtplib
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.core.crypto import decrypt_json
from app.models import NotificationChannel, NotificationDelivery

log = logging.getLogger("twin.notify")

SEVERITY_RANK = {"info": 0, "warning": 1, "alarm": 2}
RETRIES = 3
TIMEOUT_S = 5.0


@dataclass
class Event:
    org_id: str
    kind: str  # alert.raised | alert.escalated | alert.cleared | automation | test
    subject: str
    payload: dict[str, Any]
    severity: str = "info"
    channel_ids: list[str] | None = None  # None = all channels subscribed to alerts


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def send_webhook(ch: NotificationChannel, secrets: dict, ev: Event) -> str:
    body = json.dumps({"event": ev.kind, "subject": ev.subject, "severity": ev.severity, "sent_at": datetime.now(UTC).isoformat(),
                       **ev.payload}, default=str).encode()
    headers = {"Content-Type": "application/json", "User-Agent": "twin-platform/1.0", "X-Twin-Event": ev.kind}
    if secrets.get("secret"):
        headers["X-Twin-Signature"] = sign(secrets["secret"], body)
    req = urllib.request.Request(ch.config["url"], data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:  # noqa: S310 - URL is admin-configured
        return f"HTTP {r.status}"


def send_email(ch: NotificationChannel, secrets: dict, ev: Event) -> str:
    c = ch.config
    msg = EmailMessage()
    msg["Subject"] = f"[Twin] {ev.subject}"
    msg["From"] = c["from"]
    msg["To"] = c["to"]
    lines = [ev.subject, ""] + [f"{k}: {v}" for k, v in ev.payload.get("alert", ev.payload).items() if not isinstance(v, (dict, list))]
    msg.set_content("\n".join(lines))
    port = int(c.get("port", 587))
    with smtplib.SMTP(c["host"], port, timeout=TIMEOUT_S) as s:
        if c.get("starttls", True):
            s.starttls(context=ssl.create_default_context())
        if c.get("username"):
            s.login(c["username"], secrets.get("password", ""))
        s.send_message(msg)
    return f"accepted by {c['host']}"


SENDERS = {"webhook": send_webhook, "email": send_email}


class Notifier:
    def __init__(self, session_factory: sessionmaker):
        self.session_factory = session_factory
        self.queue: asyncio.Queue[Event] | None = None
        self._task: asyncio.Task | None = None
        self._notified: dict[str, str] = {}  # alert id -> last severity notified
        self.loop: asyncio.AbstractEventLoop | None = None
        self.stats = {"sent": 0, "failed": 0}

    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.queue = asyncio.Queue(maxsize=5000)
        self._task = asyncio.create_task(self._worker(), name="notifier")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    def submit(self, ev: Event) -> bool:
        if self.queue is None or self.loop is None:
            return False

        def put():
            try:
                self.queue.put_nowait(ev)
            except asyncio.QueueFull:
                log.error("notification queue full; dropping %s", ev.kind)

        try:
            if asyncio.get_running_loop() is self.loop:
                put()
                return True
        except RuntimeError:
            pass
        self.loop.call_soon_threadsafe(put)
        return True

    def on_alert(self, rec: dict[str, Any]) -> None:
        """Called for every alert change; notifies on raise, escalation and (optionally) clear."""
        aid = rec["id"]
        if rec.get("active"):
            prev = self._notified.get(aid)
            if prev == rec["severity"] or (prev == "alarm" and rec["severity"] == "warning"):
                return
            self._notified[aid] = rec["severity"]
            kind = "alert.raised" if prev is None else "alert.escalated"
        else:
            if aid not in self._notified:
                return
            self._notified.pop(aid, None)
            kind = "alert.cleared"
        self.submit(Event(rec["org_id"], kind, rec["message"], {"alert": rec}, rec.get("severity", "warning")))

    async def _worker(self) -> None:
        while True:
            ev = await self.queue.get()
            try:
                await asyncio.to_thread(self._deliver, ev)
            except Exception:  # noqa: BLE001 - never kill the worker
                log.exception("notification delivery crashed")

    def _channels(self, db, ev: Event) -> list[NotificationChannel]:
        q = select(NotificationChannel).where(NotificationChannel.org_id == ev.org_id, NotificationChannel.enabled.is_(True))
        if ev.channel_ids is not None:
            q = q.where(NotificationChannel.id.in_(ev.channel_ids))
        chans = db.scalars(q).all()
        if ev.channel_ids is None:
            chans = [c for c in chans if c.alerts and SEVERITY_RANK.get(ev.severity, 0) >= SEVERITY_RANK.get(c.min_severity, 1)
                     and (ev.kind != "alert.cleared" or c.notify_clear)]
        return chans

    def deliver_now(self, ev: Event) -> list[dict[str, Any]]:
        """Synchronous delivery (used by the worker and by 'send test')."""
        return self._deliver(ev)

    def _deliver(self, ev: Event) -> list[dict[str, Any]]:
        results = []
        with self.session_factory() as db:
            for ch in self._channels(db, ev):
                sender = SENDERS.get(ch.type)
                secrets = decrypt_json(ch.secrets_encrypted)
                status, detail, attempts = "failed", "unknown channel type", 0
                for attempt in range(1, RETRIES + 1):
                    attempts = attempt
                    try:
                        detail = sender(ch, secrets, ev)
                        status = "sent"
                        break
                    except urllib.error.HTTPError as e:
                        detail = f"HTTP {e.code}"
                        if 400 <= e.code < 500 and e.code != 429:
                            break  # receiver rejected it; retrying won't help
                    except Exception as e:  # noqa: BLE001
                        detail = f"{type(e).__name__}: {e}"[:400]
                    if attempt < RETRIES:
                        time.sleep(min(2 ** (attempt - 1), 4))
                db.add(NotificationDelivery(org_id=ev.org_id, channel_id=ch.id, event=ev.kind, subject=ev.subject[:300],
                                            status=status, attempts=attempts, detail=detail[:500]))
                self.stats["sent" if status == "sent" else "failed"] += 1
                results.append({"channel": ch.name, "status": status, "detail": detail, "attempts": attempts})
            db.commit()
        return results

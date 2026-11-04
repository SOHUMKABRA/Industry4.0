"""In-process telemetry runtime.

Pipeline per sample: adapter Sample → point mapping (scale/offset) →
duplicate/out-of-order filter → latest-value cache → alert evaluation →
WebSocket hub → batched history write. Poll adapters (Modbus, simulator) are
read every poll interval over a persistent connection; push adapters (MQTT)
deliver samples as they arrive. Simulated devices are tagged
source='simulated' all the way through.

Designed so the same class can run inside an edge gateway later.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.base import AdapterError, CommandAck, DeviceAdapter, Sample
from app.adapters.registry import get_adapter_class
from app.core.crypto import decrypt_json
from app.models import Asset, AssetType, Device, TelemetryRecord
from app.telemetry.alerts import AlertEngine, AssetMeta
from app.telemetry.hub import Hub

log = logging.getLogger("twin.telemetry")

DEVICE_REFRESH_S = 5.0
FLUSH_EVERY_S = 2.0
PRUNE_EVERY_S = 600.0
ROLLUP_EVERY_S = 120.0
READ_TIMEOUT_S = 5.0
WRITE_TIMEOUT_S = 5.0


@dataclass
class LatestValue:
    org_id: str
    factory_id: str
    asset_id: str
    measurement: str
    value: Any
    ts: datetime
    quality: str
    source: str
    device_id: str

    def frame(self) -> list[Any]:
        return [self.asset_id, self.measurement, self.value, int(self.ts.timestamp() * 1000), self.quality, self.source]


@dataclass
class DeviceCtx:
    id: str
    org_id: str
    factory_id: str
    asset_id: str
    name: str
    protocol: str
    source: str
    mappings: dict[str, tuple[str, float, float]]
    control_mappings: list[dict[str, Any]]
    fingerprint: str
    adapter: DeviceAdapter
    last_seq: dict[str, int] = field(default_factory=dict)
    last_seen: float | None = None
    last_error: str = ""
    samples: int = 0
    errors: int = 0
    last_poll_ms: float | None = None
    started_at: float = field(default_factory=time.time)
    was_online: bool | None = None


def _fingerprint(d: Device) -> str:
    raw = json.dumps([d.protocol, d.connection_config, d.point_mappings, d.control_mappings, d.asset_id, d.credentials_encrypted],
                     sort_keys=True, default=str)
    return hashlib.sha1(raw.encode()).hexdigest()


def apply_mapping(value: Any, scale: float, offset: float) -> Any:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    if scale == 1 and offset == 0:
        return value
    return round(value * scale + offset, 6)


class TelemetryRuntime:
    def __init__(self, session_factory: sessionmaker, poll_s: float = 1.0, retention_hours: float = 6.0):
        self.session_factory = session_factory
        self.poll_s = poll_s
        self.retention = timedelta(hours=retention_hours)
        self.hub = Hub()
        self.latest: dict[tuple[str, str], LatestValue] = {}
        self.devices: dict[str, DeviceCtx] = {}
        self.assets: dict[str, AssetMeta] = {}
        # Alert changes go to WebSocket subscribers and to any listeners (e.g. the notifier).
        self.alert_listeners: list = []
        self.alerts = AlertEngine(self._alert_changed)
        self._buffer: list[dict[str, Any]] = []
        self._dirty_hours: set[datetime] = set()  # hours that received data since the last roll-up
        self._tasks: list[asyncio.Task] = []
        self.started_at: float | None = None
        self.stats = {"ingested": 0, "duplicates": 0, "out_of_order": 0, "bad_quality": 0, "written": 0, "write_errors": 0}

    def _alert_changed(self, org: str, fac: str, rec: dict[str, Any]) -> None:
        self.hub.publish_event(org, fac, {"type": "alert", "alert": rec})
        for fn in self.alert_listeners:
            try:
                fn(rec)
            except Exception:  # noqa: BLE001 - a listener must never break alerting
                log.exception("alert listener failed")

    # ---------- lifecycle ----------
    async def start(self) -> None:
        self.started_at = time.time()
        with self.session_factory() as db:
            n = self.alerts.load_active(db)
        if n:
            log.info("restored %d active alerts", n)
        self._tasks = [
            asyncio.create_task(self._poll_loop(), name="telemetry-poll"),
            asyncio.create_task(self._flush_loop(), name="telemetry-flush"),
        ]
        log.info("Telemetry runtime started (poll %.1fs, retention %s)", self.poll_s, self.retention)

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        for ctx in list(self.devices.values()):
            await self._shutdown(ctx)
        await asyncio.to_thread(self.flush)

    @property
    def running(self) -> bool:
        return bool(self._tasks)

    async def _shutdown(self, ctx: DeviceCtx) -> None:
        try:
            await asyncio.wait_for(ctx.adapter.stop() if ctx.adapter.push else ctx.adapter.disconnect(), 5)
        except Exception:  # noqa: BLE001 - best effort
            pass

    # ---------- device set ----------
    def _load_rows(self):
        with self.session_factory() as db:
            rows = db.scalars(select(Device).where(Device.enabled.is_(True), Device.asset_id.is_not(None))).all()
            asset_ids = {d.asset_id for d in rows}
            assets = {a.id: a for a in db.scalars(select(Asset).where(Asset.id.in_(asset_ids)))} if asset_ids else {}
            type_ids = {a.asset_type_id for a in assets.values()}
            types = {t.id: t for t in db.scalars(select(AssetType).where(AssetType.id.in_(type_ids)))} if type_ids else {}
            metas = {}
            for a in assets.values():
                t = types.get(a.asset_type_id)
                defs = {d["key"]: {**d, **(a.operating_limits or {}).get(d["key"], {})} for d in (t.telemetry if t else [])}
                metas[a.id] = AssetMeta(a.id, a.org_id, a.factory_id, a.code, a.name, defs)
            return rows, assets, metas

    async def refresh_devices(self) -> None:
        rows, assets, metas = await asyncio.to_thread(self._load_rows)
        self.assets = metas
        seen = set()
        for d in rows:
            asset = assets.get(d.asset_id)
            if asset is None or asset.factory_id != d.factory_id:
                continue
            seen.add(d.id)
            fp = _fingerprint(d)
            cur = self.devices.get(d.id)
            if cur and cur.fingerprint == fp:
                cur.name = d.name
                continue
            if cur:
                await self._shutdown(cur)
            try:
                cls = get_adapter_class(d.protocol)
            except AdapterError:
                continue
            adapter = cls(d.connection_config, decrypt_json(d.credentials_encrypted))
            ctx = DeviceCtx(
                id=d.id, org_id=d.org_id, factory_id=d.factory_id, asset_id=d.asset_id, name=d.name, protocol=d.protocol,
                source="simulated" if d.protocol == "simulated" else "live",
                mappings={m["point"]: (m["measurement"], float(m.get("scale", 1)), float(m.get("offset", 0))) for m in d.point_mappings},
                control_mappings=list(d.control_mappings or []), fingerprint=fp, adapter=adapter,
            )
            self.devices[d.id] = ctx
            if adapter.push:
                try:
                    await adapter.start(list(ctx.mappings), lambda samples, c=ctx: self._on_push(c, samples))
                except Exception as e:  # noqa: BLE001
                    ctx.last_error = f"{type(e).__name__}: {e}"
        for gone in set(self.devices) - seen:
            ctx = self.devices.pop(gone)
            await self._shutdown(ctx)
            self.alerts.device_removed(ctx.id)
            # A disabled/unbound device must not keep showing data.
            for m, _, _ in ctx.mappings.values():
                self.latest.pop((ctx.asset_id, m), None)

    # ---------- ingestion ----------
    def _on_push(self, ctx: DeviceCtx, samples: list[Sample]) -> None:
        ctx.last_seen = time.time()
        ctx.last_error = ""
        self.ingest(ctx, samples)

    def ingest(self, ctx: DeviceCtx, samples: list[Sample]) -> list[LatestValue]:
        accepted: list[LatestValue] = []
        meta = self.assets.get(ctx.asset_id)
        for s in samples:
            mapping = ctx.mappings.get(s.point)
            if mapping is None:
                continue
            if s.quality == "bad" or s.value is None:
                self.stats["bad_quality"] += 1
                continue
            if s.seq is not None:
                prev = ctx.last_seq.get(s.point)
                if prev is not None and s.seq <= prev and prev - s.seq < 1_000_000:
                    self.stats["duplicates"] += 1
                    continue
                ctx.last_seq[s.point] = s.seq
            measurement, scale, offset = mapping
            value = apply_mapping(s.value, scale, offset)
            lv = LatestValue(ctx.org_id, ctx.factory_id, ctx.asset_id, measurement, value, s.ts, s.quality, ctx.source, ctx.id)
            numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
            # History keeps every accepted sample; the latest cache ignores older ones.
            self._dirty_hours.add(s.ts.replace(minute=0, second=0, microsecond=0))
            self._buffer.append({
                "org_id": ctx.org_id, "asset_id": ctx.asset_id, "measurement": measurement, "ts": s.ts,
                "value_num": float(value) if numeric else None, "value_text": None if numeric else str(value)[:200],
                "quality": s.quality, "source": ctx.source, "device_id": ctx.id,
            })
            key = (ctx.asset_id, measurement)
            cur = self.latest.get(key)
            if cur is not None and cur.ts > s.ts:
                self.stats["out_of_order"] += 1
                continue
            self.latest[key] = lv
            self.hub.publish(ctx.org_id, ctx.factory_id, ctx.asset_id, measurement, lv.frame())
            if meta is not None:
                try:
                    self.alerts.evaluate(meta, measurement, value, ctx.source)
                except Exception:  # noqa: BLE001 - alerting must never break ingestion
                    log.exception("alert evaluation failed")
            accepted.append(lv)
        ctx.samples += len(samples)
        self.stats["ingested"] += len(accepted)
        return accepted

    async def poll_device(self, ctx: DeviceCtx) -> None:
        if ctx.adapter.push:
            return
        t0 = time.perf_counter()
        try:
            samples = await asyncio.wait_for(ctx.adapter.read_telemetry(list(ctx.mappings)), READ_TIMEOUT_S)
        except Exception as e:  # adapters talk to the outside world
            ctx.errors += 1
            ctx.last_error = f"{type(e).__name__}: {e}"[:300] if str(e) else type(e).__name__
            return
        ctx.last_poll_ms = round((time.perf_counter() - t0) * 1000, 1)
        if samples:
            ctx.last_seen = time.time()
            ctx.last_error = ""
            self.ingest(ctx, samples)

    def check_connectivity(self) -> None:
        now = time.time()
        for ctx in self.devices.values():
            if now - ctx.started_at < max(6.0, self.poll_s * 4):
                continue  # grace period after (re)connect
            online = self.device_online(ctx)
            if online != ctx.was_online:
                ctx.was_online = online
                self.alerts.device_comm(ctx.org_id, ctx.factory_id, ctx.id, ctx.asset_id, ctx.name, online, ctx.source)

    async def _poll_loop(self) -> None:
        last_refresh = 0.0
        while True:
            started = time.monotonic()
            try:
                if started - last_refresh > DEVICE_REFRESH_S:
                    await self.refresh_devices()
                    last_refresh = started
                await asyncio.gather(*(self.poll_device(c) for c in list(self.devices.values())))
                self.check_connectivity()
            except asyncio.CancelledError:
                raise
            except Exception:  # keep the runtime alive; log and retry next tick
                log.exception("telemetry poll cycle failed")
            await asyncio.sleep(max(0.05, self.poll_s - (time.monotonic() - started)))

    # ---------- commands ----------
    async def write(self, device_id: str, point: str, value: Any) -> CommandAck:
        ctx = self.devices.get(device_id)
        if ctx is None:
            raise AdapterError("Device is not active in the runtime (disabled or not bound)")
        if not ctx.adapter.supports_write:
            raise AdapterError(f"{ctx.adapter.name} adapter does not support writes")
        return await asyncio.wait_for(ctx.adapter.write_command(point, value), WRITE_TIMEOUT_S)

    # ---------- persistence ----------
    def flush(self) -> int:
        n = 0
        if self._buffer:
            rows, self._buffer = self._buffer, []
            try:
                with self.session_factory() as db:
                    db.bulk_insert_mappings(TelemetryRecord, rows)
                    db.commit()
                self.stats["written"] += len(rows)
                n = len(rows)
            except Exception:
                # Don't silently discard: put rows back (bounded) and report.
                self.stats["write_errors"] += 1
                log.exception("telemetry history write failed; %d rows re-queued", len(rows))
                self._buffer = (rows + self._buffer)[-100_000:]
        try:
            with self.session_factory() as db:
                self.alerts.flush(db)
        except Exception:
            log.exception("alert write failed")
        return n

    def _rollup(self, fn) -> None:
        dirty, self._dirty_hours = self._dirty_hours, set()
        try:
            with self.session_factory() as db:
                fn(db, dirty=dirty)
        except Exception:
            self._dirty_hours |= dirty  # retry next time
            raise

    def prune(self) -> int:
        cutoff = datetime.now(UTC) - self.retention
        with self.session_factory() as db:
            n = db.execute(delete(TelemetryRecord).where(TelemetryRecord.ts < cutoff)).rowcount or 0
            db.commit()
        return n

    async def _flush_loop(self) -> None:
        from app.telemetry.rollup import rollup_recent

        last_prune = time.monotonic()
        last_rollup = 0.0
        while True:
            await asyncio.sleep(FLUSH_EVERY_S)
            try:
                await asyncio.to_thread(self.flush)
                if time.monotonic() - last_rollup > ROLLUP_EVERY_S:
                    last_rollup = time.monotonic()
                    await asyncio.to_thread(self._rollup, rollup_recent)
                if time.monotonic() - last_prune > PRUNE_EVERY_S:
                    n = await asyncio.to_thread(self.prune)
                    last_prune = time.monotonic()
                    if n:
                        log.info("pruned %d telemetry rows older than %s", n, self.retention)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("telemetry flush loop error")

    # ---------- queries ----------
    def device_online(self, ctx: DeviceCtx) -> bool:
        return ctx.last_seen is not None and time.time() - ctx.last_seen < max(6.0, self.poll_s * 4)

    def snapshot(self, org_id: str, factory_id: str) -> dict[str, Any]:
        points = [lv.frame() for lv in self.latest.values() if lv.org_id == org_id and lv.factory_id == factory_id]
        return {"points": points, "devices": self.device_states(org_id, factory_id), "running": self.running}

    def device_states(self, org_id: str, factory_id: str) -> list[dict[str, Any]]:
        return [
            {
                "device_id": c.id, "asset_id": c.asset_id, "online": self.device_online(c), "source": c.source,
                "protocol": c.protocol, "last_seen": int(c.last_seen * 1000) if c.last_seen else None, "error": c.last_error,
                "samples": c.samples, "errors": c.errors, "poll_ms": c.last_poll_ms,
            }
            for c in self.devices.values()
            if c.org_id == org_id and c.factory_id == factory_id
        ]

    def latest_value(self, asset_id: str, measurement: str) -> LatestValue | None:
        return self.latest.get((asset_id, measurement))


def history(db: Session, asset_id: str, measurement: str, since: datetime, until: datetime, buckets: int) -> list[dict[str, Any]]:
    """Downsample to at most `buckets` points (avg/min/max for numbers; last value for text).

    Done in Python for SQLite portability; on PostgreSQL+Timescale this becomes
    a time_bucket() query.
    """
    rows = db.execute(
        select(TelemetryRecord.ts, TelemetryRecord.value_num, TelemetryRecord.value_text, TelemetryRecord.source)
        .where(
            TelemetryRecord.asset_id == asset_id,
            TelemetryRecord.measurement == measurement,
            TelemetryRecord.ts >= since,
            TelemetryRecord.ts <= until,
        )
        .order_by(TelemetryRecord.ts)
    ).all()
    span = max((until - since).total_seconds(), 1.0)
    width = span / max(buckets, 1)
    out: dict[int, dict[str, Any]] = {}
    for ts, num, text, source in rows:
        idx = min(int((ts - since).total_seconds() / width), buckets - 1)
        b = out.get(idx)
        if b is None:
            b = out[idx] = {"t": int((since.timestamp() + idx * width) * 1000), "n": 0, "sum": 0.0,
                            "min": None, "max": None, "last": None, "source": source}
        b["n"] += 1
        if num is not None:
            b["sum"] += num
            b["min"] = num if b["min"] is None else min(b["min"], num)
            b["max"] = num if b["max"] is None else max(b["max"], num)
            b["last"] = num
        else:
            b["last"] = text
    result = []
    for idx in sorted(out):
        b = out[idx]
        numeric = b["min"] is not None
        result.append({
            "t": b["t"], "avg": round(b["sum"] / b["n"], 4) if numeric else None, "min": b["min"], "max": b["max"],
            "last": b["last"], "count": b["n"], "source": b["source"],
        })
    return result

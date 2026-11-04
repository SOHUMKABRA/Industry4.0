"""Hourly roll-ups of raw telemetry (long-term analytics).

Raw samples are kept for TELEMETRY_RETENTION_HOURS; roll-ups are kept for
ROLLUP_RETENTION_DAYS. Each hour is recomputed from raw data, so re-running is
idempotent. State signals get time-in-state; a gap longer than MAX_GAP_S is
counted as "no data", never as the last known state.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import TelemetryHourly, TelemetryRecord

log = logging.getLogger("twin.rollup")

MAX_GAP_S = 60.0
ROLLUP_RETENTION_DAYS = 400


def hour_floor(t: datetime) -> datetime:
    return t.replace(minute=0, second=0, microsecond=0)


def rollup_hour(db: Session, hour: datetime, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    end = hour + timedelta(hours=1)
    rows = db.execute(
        select(TelemetryRecord.org_id, TelemetryRecord.asset_id, TelemetryRecord.measurement, TelemetryRecord.ts,
               TelemetryRecord.value_num, TelemetryRecord.value_text, TelemetryRecord.source)
        .where(TelemetryRecord.ts >= hour, TelemetryRecord.ts < end)
        .order_by(TelemetryRecord.asset_id, TelemetryRecord.measurement, TelemetryRecord.ts)
    ).all()
    groups: dict[tuple[str, str], list] = defaultdict(list)
    for r in rows:
        groups[(r.asset_id, r.measurement)].append(r)
    out: list[dict[str, Any]] = []
    horizon = min(end, now)
    for (asset_id, measurement), samples in groups.items():
        nums = [s.value_num for s in samples if s.value_num is not None]
        rec: dict[str, Any] = {
            "org_id": samples[0].org_id, "asset_id": asset_id, "measurement": measurement, "hour": hour,
            "count": len(samples), "source": samples[-1].source, "states": {},
            "avg": sum(nums) / len(nums) if nums else None, "min": min(nums) if nums else None,
            "max": max(nums) if nums else None, "first_num": nums[0] if nums else None, "last_num": nums[-1] if nums else None,
            "last_text": samples[-1].value_text,
        }
        texts = [s for s in samples if s.value_text is not None]
        if texts:
            states: dict[str, float] = defaultdict(float)
            starts = 0
            # Carry the state from just before the hour, so a transition (or time in
            # state) at the hour boundary isn't lost.
            before = db.execute(
                select(TelemetryRecord.ts, TelemetryRecord.value_text)
                .where(TelemetryRecord.asset_id == asset_id, TelemetryRecord.measurement == measurement,
                       TelemetryRecord.ts < hour, TelemetryRecord.ts >= hour - timedelta(seconds=MAX_GAP_S),
                       TelemetryRecord.value_text.is_not(None))
                .order_by(TelemetryRecord.ts.desc()).limit(1)
            ).first()
            prev = None
            if before is not None:
                prev = before.value_text
                carry = min((texts[0].ts - hour).total_seconds(), MAX_GAP_S - (hour - before.ts).total_seconds())
                if carry > 0:
                    states[prev] += carry
            for i, s in enumerate(texts):
                nxt = texts[i + 1].ts if i + 1 < len(texts) else horizon
                states[s.value_text] += max(0.0, min((nxt - s.ts).total_seconds(), MAX_GAP_S))
                if s.value_text == "running" and prev not in (None, "running"):
                    starts += 1
                prev = s.value_text
            rec["states"] = {k: round(v, 1) for k, v in states.items()} | {"_starts": starts}
        out.append(rec)
    db.execute(delete(TelemetryHourly).where(TelemetryHourly.hour == hour))
    if out:
        db.bulk_insert_mappings(TelemetryHourly, out)
    db.commit()
    return len(out)


def rollup_recent(db: Session, now: datetime | None = None, dirty: set[datetime] | None = None) -> int:
    """Roll up every hour since the last roll-up (including the current one), plus any
    older hours that received late data (e.g. a gateway flushing its buffer)."""
    now = now or datetime.now(UTC)
    current = hour_floor(now)
    last = db.scalar(select(func.max(TelemetryHourly.hour)))
    if last is None:
        first_raw = db.scalar(select(func.min(TelemetryRecord.ts)))
        if first_raw is None:
            return 0
        start = hour_floor(first_raw)
    else:
        start = min(last, current - timedelta(hours=1))
    hours = set()
    h = start
    while h <= current:
        hours.add(h)
        h += timedelta(hours=1)
    hours |= {d for d in (dirty or set()) if d <= current}
    n = sum(rollup_hour(db, h, now) for h in sorted(hours))
    db.execute(delete(TelemetryHourly).where(TelemetryHourly.hour < now - timedelta(days=ROLLUP_RETENTION_DAYS)))
    db.commit()
    return n

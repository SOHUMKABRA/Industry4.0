"""Analytics, reports and historical playback."""

import csv
import io
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import select

from app.core.deps import DB, CurrentUser, get_owned
from app.models import (
    Alert, Asset, AssetType, AutomationExecution, AutomationRule, ControlCommand, Factory, TelemetryHourly, TelemetryRecord,
)
from app.telemetry.rollup import hour_floor, rollup_hour

router = APIRouter(tags=["analytics"])
COUNTERS = {"item_count", "output_count", "cycle_count"}


def _ctx(db, user, factory_id: str):
    f = get_owned(db, Factory, factory_id, user, "Factory")
    assets = {a.id: a for a in db.scalars(select(Asset).where(Asset.factory_id == f.id))}
    types = {t.id: t for t in db.scalars(select(AssetType).where(AssetType.org_id == user.org_id))}
    try:
        tz = ZoneInfo(f.timezone or "UTC")
    except Exception:  # noqa: BLE001
        tz = ZoneInfo("UTC")
    return f, assets, types, tz


def _fresh_rollups(db, since: datetime, until: datetime) -> None:
    """Re-roll the current (partial) hour so 'today' includes the last few minutes."""
    rollup_hour(db, hour_floor(until), until)


def _rollups(db, asset_ids, measurements: set[str] | None, since: datetime, until: datetime):
    q = select(TelemetryHourly).where(TelemetryHourly.asset_id.in_(asset_ids), TelemetryHourly.hour >= hour_floor(since),
                                      TelemetryHourly.hour < until)
    if measurements is not None:
        q = q.where(TelemetryHourly.measurement.in_(measurements))
    return db.scalars(q.order_by(TelemetryHourly.hour)).all()


def _window(hours: float, until: datetime | None = None) -> tuple[datetime, datetime]:
    until = until or datetime.now(UTC)
    return until - timedelta(hours=hours), until


def utilization_data(db, assets, types, since, until) -> list[dict[str, Any]]:
    rows = _rollups(db, list(assets), {"state"}, since, until)
    acc: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for r in rows:
        for k, v in (r.states or {}).items():
            acc[r.asset_id][k] += v
    window = (until - since).total_seconds()
    out = []
    for aid, a in assets.items():
        t = types.get(a.asset_type_id)
        if not t or not any(d["key"] == "state" for d in t.telemetry):
            continue
        st = acc.get(aid, {})
        starts = int(st.pop("_starts", 0)) if st else 0
        known = sum(st.values())
        running = st.get("running", 0.0)
        out.append({
            "asset_id": aid, "code": a.code, "name": a.name, "category": t.category,
            "seconds": {k: round(v) for k, v in sorted(st.items(), key=lambda kv: -kv[1])},
            "known_s": round(known), "no_data_s": round(max(0.0, window - known)), "running_s": round(running),
            "downtime_s": round(sum(v for k, v in st.items() if k in ("stopped", "fault", "emergency_stop", "idle", "maintenance"))),
            "utilization": round(running / known, 4) if known else None, "starts": starts,
        })
    return sorted(out, key=lambda r: r["code"])


def _bucket_key(h: datetime, bucket: str, tz: ZoneInfo) -> datetime:
    if bucket == "day":
        local = h.astimezone(tz)
        return datetime(local.year, local.month, local.day, tzinfo=tz).astimezone(UTC)
    return h


def energy_data(db, assets, types, since, until, bucket, tz) -> dict[str, Any]:
    meters = {aid: a for aid, a in assets.items() if any(d["key"] == "power_kw" for d in (types[a.asset_type_id].telemetry if a.asset_type_id in types else []))}
    rows = _rollups(db, list(meters), {"power_kw"}, since, until)
    series: dict[str, dict[datetime, float]] = defaultdict(lambda: defaultdict(float))
    for r in rows:
        if r.avg is None:
            continue
        hours = min(1.0, max(0.0, (min(until, r.hour + timedelta(hours=1)) - max(since, r.hour)).total_seconds() / 3600))
        series[r.asset_id][_bucket_key(r.hour, bucket, tz)] += r.avg * hours
    keys = sorted({k for s in series.values() for k in s})
    return {
        "bucket": bucket, "buckets": [int(k.timestamp() * 1000) for k in keys],
        "meters": [{"asset_id": aid, "code": meters[aid].code, "name": meters[aid].name,
                    "kwh": [round(series[aid].get(k, 0.0), 2) for k in keys], "total_kwh": round(sum(series[aid].values()), 1)}
                   for aid in sorted(series, key=lambda x: meters[x].code)],
    }


def production_data(db, assets, since, until, bucket, tz) -> dict[str, Any]:
    rows = _rollups(db, list(assets), COUNTERS, since, until)
    by_key: dict[tuple[str, str], list] = defaultdict(list)
    for r in rows:
        by_key[(r.asset_id, r.measurement)].append(r)
    series: dict[tuple[str, str], dict[datetime, float]] = defaultdict(lambda: defaultdict(float))
    for key, hrs in by_key.items():
        prev_last = None
        for r in hrs:
            if r.first_num is None or r.last_num is None:
                prev_last = None
                continue
            inc = r.last_num - r.first_num if r.last_num >= r.first_num else r.last_num  # counter reset (midnight)
            if prev_last is not None and r.first_num >= prev_last:
                inc += r.first_num - prev_last
            series[key][_bucket_key(r.hour, bucket, tz)] += max(0.0, inc)
            prev_last = r.last_num
    keys = sorted({k for s in series.values() for k in s})
    return {
        "bucket": bucket, "buckets": [int(k.timestamp() * 1000) for k in keys],
        "counters": [{"asset_id": aid, "code": assets[aid].code, "name": assets[aid].name, "measurement": m,
                      "counts": [round(series[(aid, m)].get(k, 0)) for k in keys], "total": round(sum(series[(aid, m)].values()))}
                     for (aid, m) in sorted(series, key=lambda x: assets[x[0]].code)],
    }


@router.get("/analytics/utilization")
def utilization(factory_id: str, user: CurrentUser, db: DB, hours: float = Query(default=24, gt=0, le=24 * 400)):
    f, assets, types, tz = _ctx(db, user, factory_id)
    since, until = _window(hours)
    _fresh_rollups(db, since, until)
    return {"from": int(since.timestamp() * 1000), "to": int(until.timestamp() * 1000), "assets": utilization_data(db, assets, types, since, until)}


@router.get("/analytics/energy")
def energy(factory_id: str, user: CurrentUser, db: DB, hours: float = Query(default=24, gt=0, le=24 * 400),
           bucket: str = Query(default="hour", pattern="^(hour|day)$")):
    f, assets, types, tz = _ctx(db, user, factory_id)
    since, until = _window(hours)
    _fresh_rollups(db, since, until)
    return energy_data(db, assets, types, since, until, bucket, tz)


@router.get("/analytics/production")
def production(factory_id: str, user: CurrentUser, db: DB, hours: float = Query(default=24, gt=0, le=24 * 400),
               bucket: str = Query(default="hour", pattern="^(hour|day)$")):
    f, assets, types, tz = _ctx(db, user, factory_id)
    since, until = _window(hours)
    _fresh_rollups(db, since, until)
    return production_data(db, assets, since, until, bucket, tz)


@router.get("/analytics/compare")
def compare(factory_id: str, measurement: str, asset_ids: str, user: CurrentUser, db: DB,
            hours: float = Query(default=24, gt=0, le=24 * 400)):
    f, assets, types, tz = _ctx(db, user, factory_id)
    ids = [a for a in asset_ids.split(",") if a in assets][:12]
    if not ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose at least one asset of this factory")
    since, until = _window(hours)
    series = []
    if hours <= 24:
        # 5-minute buckets from raw data
        step = 300 if hours > 2 else 60
        rows = db.execute(select(TelemetryRecord.asset_id, TelemetryRecord.ts, TelemetryRecord.value_num)
                          .where(TelemetryRecord.asset_id.in_(ids), TelemetryRecord.measurement == measurement,
                                 TelemetryRecord.ts >= since, TelemetryRecord.value_num.is_not(None))).all()
        acc: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(lambda: [0.0, 0]))
        for aid, ts, v in rows:
            b = int(ts.timestamp() // step * step)
            acc[aid][b][0] += v
            acc[aid][b][1] += 1
        for aid in ids:
            pts = sorted((b * 1000, round(s / n, 4)) for b, (s, n) in acc[aid].items())
            series.append({"asset_id": aid, "code": assets[aid].code, "points": pts})
    else:
        _fresh_rollups(db, since, until)
        rows = _rollups(db, ids, {measurement}, since, until)
        acc2: dict[str, list] = defaultdict(list)
        for r in rows:
            if r.avg is not None:
                acc2[r.asset_id].append((int(r.hour.timestamp() * 1000), round(r.avg, 4)))
        series = [{"asset_id": aid, "code": assets[aid].code, "points": acc2[aid]} for aid in ids]
    return {"measurement": measurement, "from": int(since.timestamp() * 1000), "to": int(until.timestamp() * 1000), "series": series}


# ---------- reports ----------
def report_data(db, user, factory_id: str, day: date) -> dict[str, Any]:
    f, assets, types, tz = _ctx(db, user, factory_id)
    since = datetime(day.year, day.month, day.day, tzinfo=tz).astimezone(UTC)
    until = min(since + timedelta(days=1), datetime.now(UTC))
    if until <= since:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That day hasn't started yet")
    _fresh_rollups(db, since, until)
    util = utilization_data(db, assets, types, since, until)
    en = energy_data(db, assets, types, since, until, "hour", tz)
    prod = production_data(db, assets, since, until, "hour", tz)
    alerts = db.scalars(select(Alert).where(Alert.factory_id == f.id, Alert.raised_at >= since, Alert.raised_at < until)).all()

    def dur(a):
        end = a.cleared_at or until
        return max(0.0, (min(end, until) - a.raised_at).total_seconds())

    cmds = db.scalars(select(ControlCommand).where(ControlCommand.factory_id == f.id, ControlCommand.requested_at >= since,
                                                   ControlCommand.requested_at < until)).all()
    rule_ids = list(db.scalars(select(AutomationRule.id).where(AutomationRule.factory_id == f.id)))
    runs = db.scalars(select(AutomationExecution).where(AutomationExecution.rule_id.in_(rule_ids), AutomationExecution.started_at >= since,
                                                        AutomationExecution.started_at < until, AutomationExecution.dry_run.is_(False))).all() if rule_ids else []

    def count(items, key) -> dict[str, int]:
        return dict(sorted(Counter(key(i) for i in items).items()))

    return {
        "factory": {"id": f.id, "name": f.name, "location": f.location, "timezone": str(tz)},
        "date": day.isoformat(), "from": since.isoformat(), "to": until.isoformat(), "generated_at": datetime.now(UTC).isoformat(),
        "generated_by": user.email, "partial_day": until < since + timedelta(days=1),
        "utilization": util,
        "energy": {"total_kwh": round(sum(m["total_kwh"] for m in en["meters"]), 1), "meters": [{k: m[k] for k in ("code", "name", "total_kwh")} for m in en["meters"]]},
        "production": [{k: c[k] for k in ("code", "name", "measurement", "total")} for c in prod["counters"]],
        "alerts": {
            "total": len(alerts), "by_severity": count(alerts, lambda a: a.severity), "by_kind": count(alerts, lambda a: a.kind),
            "unacknowledged": sum(1 for a in alerts if not a.acked),
            "longest": [{"severity": a.severity, "message": a.message, "raised_at": a.raised_at.isoformat(), "duration_s": round(dur(a)),
                         "asset": assets[a.asset_id].code if a.asset_id in assets else None}
                        for a in sorted(alerts, key=dur, reverse=True)[:10]],
        },
        "commands": {"total": len(cmds), "by_status": count(cmds, lambda c: c.status),
                     "verified": sum(1 for c in cmds if c.verified), "simulated": sum(1 for c in cmds if c.simulated)},
        "automations": {"runs": len(runs), "by_status": count(runs, lambda r: r.status)},
    }


@router.get("/reports/daily")
def daily_report(factory_id: str, user: CurrentUser, db: DB, day: date = Query(alias="date")):
    return report_data(db, user, factory_id, day)


@router.get("/reports/daily.csv")
def daily_report_csv(factory_id: str, user: CurrentUser, db: DB, day: date = Query(alias="date")):
    r = report_data(db, user, factory_id, day)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Daily operations report", r["factory"]["name"], r["date"], f"generated {r['generated_at']} by {r['generated_by']}"])
    w.writerow([])
    w.writerow(["Equipment", "Name", "Utilization %", "Running h", "Downtime h", "No data h", "Starts"])
    for u in r["utilization"]:
        w.writerow([u["code"], u["name"], "" if u["utilization"] is None else round(u["utilization"] * 100, 1),
                    round(u["running_s"] / 3600, 2), round(u["downtime_s"] / 3600, 2), round(u["no_data_s"] / 3600, 2), u["starts"]])
    w.writerow([])
    w.writerow(["Energy meter", "Name", "kWh"])
    for m in r["energy"]["meters"]:
        w.writerow([m["code"], m["name"], m["total_kwh"]])
    w.writerow(["TOTAL", "", r["energy"]["total_kwh"]])
    w.writerow([])
    w.writerow(["Counter", "Name", "Measurement", "Count"])
    for c in r["production"]:
        w.writerow([c["code"], c["name"], c["measurement"], c["total"]])
    w.writerow([])
    w.writerow(["Alerts", r["alerts"]["total"], "unacknowledged", r["alerts"]["unacknowledged"]])
    for k, v in r["alerts"]["by_severity"].items():
        w.writerow(["  severity", k, v])
    w.writerow(["Commands", r["commands"]["total"], "verified", r["commands"]["verified"]])
    for k, v in r["commands"]["by_status"].items():
        w.writerow(["  status", k, v])
    name = f"report-{r['factory']['name'].replace(' ', '_')}-{r['date']}.csv"
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ---------- playback ----------
@router.get("/factories/{factory_id}/playback")
def playback(factory_id: str, user: CurrentUser, db: DB, from_ms: int, to_ms: int, step_s: float = Query(default=5, ge=1, le=3600)):
    f, assets, types, tz = _ctx(db, user, factory_id)
    since = datetime.fromtimestamp(from_ms / 1000, UTC)
    until = datetime.fromtimestamp(to_ms / 1000, UTC)
    if until <= since or (until - since) > timedelta(hours=24):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Playback window must be between 0 and 24 h")
    step = max(step_s, (until - since).total_seconds() / 2000)
    rows = db.execute(select(TelemetryRecord.asset_id, TelemetryRecord.measurement, TelemetryRecord.ts, TelemetryRecord.value_num,
                             TelemetryRecord.value_text)
                      .where(TelemetryRecord.asset_id.in_(list(assets)), TelemetryRecord.ts >= since, TelemetryRecord.ts < until)
                      .order_by(TelemetryRecord.ts)).all()
    acc: dict[tuple[str, str], dict[int, Any]] = defaultdict(dict)
    for aid, m, ts, num, text in rows:
        b = int((ts - since).total_seconds() // step)
        acc[(aid, m)][b] = num if num is not None else text  # last value in bucket
    series = []
    for (aid, m), buckets in acc.items():
        ks = sorted(buckets)
        series.append({"a": aid, "m": m, "t": [int((since.timestamp() + k * step) * 1000) for k in ks], "v": [buckets[k] for k in ks]})
    return {"from": from_ms, "to": to_ms, "step_s": step, "series": series, "samples": len(rows)}

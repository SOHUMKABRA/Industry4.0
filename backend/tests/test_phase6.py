import asyncio
import hashlib
import hmac
import json
import threading
import time
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.automation.engine import AutomationEngine
from app.control.engine import ControlEngine
from app.core.db import SessionLocal
from app.main import app
from app.models import TelemetryRecord
from app.notify.service import Event, Notifier
from app.telemetry.rollup import rollup_recent
from app.telemetry.runtime import TelemetryRuntime
from tests.conftest import login, type_by_key


def mk_asset(client, h, f, key, code):
    return client.post("/api/assets", json={"factory_id": f["id"], "asset_type_id": type_by_key(client, h, key)["id"], "code": code, "name": code}, headers=h).json()


def test_rollups_analytics_and_report(client, new_org, factory):
    h, me = new_org()
    f = factory(h)
    org = me["organization"]["id"]
    conv = mk_asset(client, h, f, "conveyor", "CV")
    em = mk_asset(client, h, f, "energy_meter", "EM")
    now = datetime.now(UTC)
    start = (now - timedelta(hours=3)).replace(minute=0, second=0, microsecond=0)
    rows = []
    # 2 complete hours: conveyor running 45 min / stopped 15 min per hour, 2 starts; meter 50 kW; counter +30/h
    for hour in range(2):
        h0 = start + timedelta(hours=hour)
        for s in range(0, 3600, 10):
            ts = h0 + timedelta(seconds=s)
            st = "running" if s < 2700 else "stopped"
            rows.append(dict(org_id=org, asset_id=conv["id"], measurement="state", ts=ts, value_text=st, source="live"))
            rows.append(dict(org_id=org, asset_id=em["id"], measurement="power_kw", ts=ts, value_num=50.0, source="live"))
            rows.append(dict(org_id=org, asset_id=conv["id"], measurement="item_count", ts=ts, value_num=float(hour * 30 + s // 120), source="live"))
    with SessionLocal() as db:
        db.bulk_insert_mappings(TelemetryRecord, rows)
        db.commit()
        rollup_recent(db, now, dirty={start, start + timedelta(hours=1)})  # late data → explicit dirty hours
    u = client.get(f"/api/analytics/utilization?factory_id={f['id']}&hours=4", headers=h).json()["assets"]
    cv = next(x for x in u if x["code"] == "CV")
    assert abs(cv["seconds"]["running"] - 2 * 2700) < 30 and abs(cv["seconds"]["stopped"] - 2 * 900) < 80
    assert cv["starts"] == 1  # stopped → running once between the hours
    assert 0.7 < cv["utilization"] < 0.8
    e = client.get(f"/api/analytics/energy?factory_id={f['id']}&hours=4", headers=h).json()
    assert abs(e["meters"][0]["total_kwh"] - 100) < 1
    p = client.get(f"/api/analytics/production?factory_id={f['id']}&hours=4", headers=h).json()
    assert abs(p["counters"][0]["total"] - 59) <= 1
    c = client.get(f"/api/analytics/compare?factory_id={f['id']}&measurement=power_kw&asset_ids={em['id']}&hours=6", headers=h).json()
    assert c["series"][0]["points"] and c["series"][0]["points"][0][1] == 50.0
    day = start.astimezone().date().isoformat()
    r = client.get(f"/api/reports/daily?factory_id={f['id']}&date={day}", headers=h)
    assert r.status_code == 200 and r.json()["factory"]["name"] == "Plant"
    csv = client.get(f"/api/reports/daily.csv?factory_id={f['id']}&date={day}", headers=h)
    assert csv.headers["content-type"].startswith("text/csv") and "Utilization %" in csv.text
    pb = client.get(f"/api/factories/{f['id']}/playback?from_ms={int(start.timestamp()*1000)}&to_ms={int((start+timedelta(hours=1)).timestamp()*1000)}&step_s=60", headers=h).json()
    st = next(s for s in pb["series"] if s["m"] == "state")
    assert st["v"][0] == "running" and st["v"][-1] == "stopped" and len(st["t"]) == 60
    # other tenants can't read it
    h2, _ = new_org()
    assert client.get(f"/api/analytics/utilization?factory_id={f['id']}", headers=h2).status_code == 404


class Inbox(BaseHTTPRequestHandler):
    received: list = []
    fail_next = 0

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        if Inbox.fail_next:
            Inbox.fail_next -= 1
            self.send_response(503); self.end_headers(); return
        Inbox.received.append((self.headers.get("X-Twin-Signature"), body))
        self.send_response(200); self.end_headers()

    def log_message(self, *a):
        pass


@pytest.fixture
def inbox():
    srv = HTTPServer(("127.0.0.1", 0), Inbox)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    Inbox.received.clear()
    yield f"http://127.0.0.1:{srv.server_address[1]}/hook"
    srv.shutdown()


def test_webhook_channel_signed_with_retry(client, new_org, inbox):
    h, me = new_org()
    app.state.notifier = Notifier(SessionLocal)
    try:
        ch = client.post("/api/notification-channels", json={"name": "Ops", "type": "webhook", "url": inbox, "secret": "s3cr3t"}, headers=h).json()
        assert ch["has_secret"] and "s3cr3t" not in json.dumps(ch)
        Inbox.fail_next = 1  # first attempt fails, retry succeeds
        r = client.post(f"/api/notification-channels/{ch['id']}/test", headers=h).json()
        assert r["status"] == "sent" and r["attempts"] == 2
        sig, body = Inbox.received[-1]
        assert sig == "sha256=" + hmac.new(b"s3cr3t", body, hashlib.sha256).hexdigest()
        assert json.loads(body)["event"] == "test"
        log = client.get(f"/api/notification-channels/{ch['id']}/deliveries", headers=h).json()
        assert log[0]["status"] == "sent"
        # invalid config
        assert client.post("/api/notification-channels", json={"name": "x", "type": "webhook"}, headers=h).status_code == 422
        viewer = login(client, "viewer@demo.example.com")
        assert client.post("/api/notification-channels", json={"name": "x", "type": "webhook", "url": inbox}, headers=viewer).status_code == 403
    finally:
        app.state.notifier = None


def test_alert_notifications_dedupe(inbox, client, new_org):
    h, me = new_org()
    ch = client.post("/api/notification-channels", json={"name": "Ops", "type": "webhook", "url": inbox, "min_severity": "warning",
                                                          "notify_clear": True}, headers=h).json()
    n = Notifier(SessionLocal)
    sent = []
    n.submit = lambda ev: sent.append(ev) or True
    org = me["organization"]["id"]
    rec = {"id": "a1", "org_id": org, "active": True, "severity": "warning", "message": "hot"}
    n.on_alert(rec); n.on_alert(rec)                      # same severity twice → once
    n.on_alert({**rec, "severity": "alarm"})               # escalation → again
    n.on_alert({**rec, "severity": "warning"})             # de-escalation → silent
    n.on_alert({**rec, "active": False})                   # clear → once
    assert [e.kind for e in sent] == ["alert.raised", "alert.escalated", "alert.cleared"]
    results = n.deliver_now(sent[1])
    assert results[0]["status"] == "sent"


@pytest.fixture
def engines(client):
    rt = TelemetryRuntime(SessionLocal, poll_s=0.25)
    client.portal.call(rt.start)
    ctl = ControlEngine(rt, SessionLocal)

    async def loop():
        return asyncio.get_running_loop()

    ctl.bind_loop(client.portal.call(loop))
    n = Notifier(SessionLocal)
    client.portal.call(n.start)
    auto = AutomationEngine(rt, ctl, n, SessionLocal)
    app.state.telemetry, app.state.control, app.state.notifier, app.state.automation = rt, ctl, n, auto
    from app.simulation import ScenarioRunner

    app.state.scenarios = ScenarioRunner(rt)
    end = time.time() + 8
    while time.time() < end and not (rt.devices and all(rt.device_online(c) for c in rt.devices.values() if c.protocol == "simulated")):
        time.sleep(0.2)
    yield rt, auto
    client.portal.call(auto.stop)
    client.portal.call(rt.stop)
    client.portal.call(n.stop)
    app.state.telemetry = app.state.control = app.state.notifier = app.state.automation = app.state.scenarios = None


def demo_assets(client, h):
    fid = client.get("/api/factories", headers=h).json()[0]["id"]
    return fid, {a["code"]: a for a in client.get(f"/api/assets?factory_id={fid}", headers=h).json()}


def test_automation_validation_dry_run_and_firing(client, engines, demo_admin):
    rt, auto = engines
    eng = login(client, "engineer@demo.example.com")
    op = login(client, "operator@demo.example.com")
    fid, a = demo_assets(client, eng)
    base = {"factory_id": fid, "name": "t", "conditions": {"match": "all", "for_s": 0, "items": [
        {"asset_id": a["TT-201"]["id"], "measurement": "temp", "operator": ">", "value": "-100"}]}}
    bad = client.post("/api/automations", json=base | {"actions": [{"type": "command", "asset_id": a["CV-101"]["id"], "control": "nope"}]}, headers=eng)
    assert bad.status_code == 422
    assert client.post("/api/automations", json=base | {"actions": [{"type": "alert"}]}, headers=op).status_code == 403
    r = client.post("/api/automations", json=base | {"name": "Always true", "enabled": False, "cooldown_s": 0, "actions": [
        {"type": "alert", "severity": "warning", "message": "rule {rule} saw {value}"},
        {"type": "command", "asset_id": a["CV-201"]["id"], "control": "speed_setpoint", "params": {"value": 1.0}}]}, headers=eng)
    assert r.status_code == 201 and any("approval" in w for w in r.json()["warnings"])
    rid = r.json()["id"]
    dry = client.post(f"/api/automations/{rid}/dry-run", json={}, headers=eng).json()
    assert dry["dry_run"] and dry["status"] == "dry_run" and [s["status"] for s in dry["steps"]] == ["would_run", "would_run"]
    assert client.get(f"/api/commands?asset_id={a['CV-201']['id']}&status=PENDING_APPROVAL", headers=eng).json() == []  # nothing sent
    # what-if override makes a false condition true
    client.put(f"/api/automations/{rid}", json=base | {"name": "Always true", "conditions": {"match": "all", "for_s": 0, "items": [
        {"asset_id": a["TT-201"]["id"], "measurement": "temp", "operator": ">", "value": "1000"}]},
        "actions": [{"type": "alert", "message": "x"}]}, headers=eng)
    dry = client.post(f"/api/automations/{rid}/dry-run", json={"overrides": {f"{a['TT-201']['id']}:temp": 1500}}, headers=eng).json()
    assert dry["trigger_detail"].startswith("Conditions TRUE")

    # live firing: condition true → one execution, alert raised; edge-triggered (no repeats)
    client.put(f"/api/automations/{rid}", json=base | {"name": "Always true", "enabled": True, "cooldown_s": 0,
                                                       "actions": [{"type": "alert", "severity": "warning", "message": "rule {rule} saw {value}"}]}, headers=eng)
    client.portal.call(auto.start)
    time.sleep(4)
    ex = [e for e in client.get(f"/api/automations/{rid}/executions", headers=eng).json() if not e["dry_run"]]
    assert len(ex) == 1 and ex[0]["status"] == "succeeded", ex
    assert any(k[1] == "automation" for k in rt.alerts.active)
    client.post(f"/api/automations/{rid}/enabled?enabled=false", headers=eng)
    auto.reload()
    assert not any(k[0] == rid for k in rt.alerts.active)  # disabling clears the rule's alert


def test_automation_command_goes_through_control_engine(client, engines, demo_admin):
    rt, auto = engines
    eng = login(client, "engineer@demo.example.com")
    fid, a = demo_assets(client, eng)
    r = client.post("/api/automations", headers=eng, json={"factory_id": fid, "name": "Stop CV-102 when TT-201 exists", "enabled": True, "cooldown_s": 0,
        "conditions": {"match": "all", "for_s": 0, "items": [{"asset_id": a["TT-201"]["id"], "measurement": "temp", "operator": ">", "value": "-100"}]},
        "actions": [{"type": "command", "asset_id": a["CV-102"]["id"], "control": "stop"}]})
    rid = r.json()["id"]
    client.portal.call(auto.start)
    end = time.time() + 20
    ex = []
    while time.time() < end:
        ex = [e for e in client.get(f"/api/automations/{rid}/executions", headers=eng).json() if not e["dry_run"]]
        if ex and ex[0]["status"] != "running":
            break
        time.sleep(0.5)
    assert ex and ex[0]["steps"][0]["status"] == "done", ex
    cmd = client.get(f"/api/commands/{ex[0]['steps'][0]['command_id']}", headers=eng).json()
    assert cmd["status"] == "COMPLETED" and cmd["verified"] and cmd["reason"].startswith("Automation") and cmd["requested_by"] == "engineer@demo.example.com"
    client.post(f"/api/automations/{rid}/enabled?enabled=false", headers=eng)
    time.sleep(2.2)
    op = login(client, "operator@demo.example.com")
    client.post(f"/api/assets/{a['CV-102']['id']}/commands", json={"control": "start", "confirm": True}, headers=op)


def test_stale_data_never_satisfies_conditions(engines):
    rt, auto = engines
    ctx = next(c for c in rt.devices.values() if c.protocol == "simulated")
    m = next(iter(ctx.mappings.values()))[0]
    rule = {"id": "r", "name": "r", "conditions": {"match": "any", "items": [{"asset_id": ctx.asset_id, "measurement": m, "operator": "!=", "value": "zzz"}]}}
    assert auto.evaluate(rule, time.time()).ok
    assert not auto.evaluate(rule, time.time() + 3600).ok  # same data, an hour later = stale


def test_simulation_inject_and_scenario(client, engines, demo_admin, new_org, factory):
    rt, auto = engines
    eng = login(client, "engineer@demo.example.com")
    fid, a = demo_assets(client, eng)
    devs = {d["name"]: d for d in client.get(f"/api/devices?factory_id={fid}", headers=eng).json()}
    tt = devs["TT-301 simulator"]
    r = client.post("/api/simulation/inject", json={"device_id": tt["id"], "action": "set", "point": "temp", "value": 99.5, "duration_s": 30}, headers=eng)
    assert r.status_code == 200, r.text
    time.sleep(1.2)
    assert rt.latest_value(a["TT-301"]["id"], "temp").value == 99.5
    client.post("/api/simulation/inject", json={"device_id": tt["id"], "action": "restore"}, headers=eng)
    # field devices are refused
    h, _ = new_org()
    f = factory(h)
    conv = mk_asset(client, h, f, "conveyor", "C1")
    md = client.post("/api/devices", headers=h, json={"factory_id": f["id"], "asset_id": conv["id"], "name": "plc", "protocol": "modbus_tcp",
                                                      "connection_config": {"host": "127.0.0.1", "port": 1}}).json()
    assert client.post("/api/simulation/inject", json={"device_id": md["id"], "action": "offline"}, headers=h).status_code == 422
    # scenario
    sc = client.post("/api/simulation/scenarios", headers=eng, json={"factory_id": fid, "name": "drill", "steps": [
        {"at_s": 0, "device_id": tt["id"], "action": "offline", "duration_s": 3}]}).json()
    run = client.post(f"/api/simulation/scenarios/{sc['id']}/run", headers=eng).json()
    assert run["done"] is False
    assert client.post(f"/api/simulation/scenarios/{sc['id']}/run", headers=eng).status_code == 409
    time.sleep(4.5)
    st = client.get(f"/api/simulation/status?factory_id={fid}", headers=eng).json()
    assert st["done"] and any("offline" in line for line in st["log"])

import socket
import time

import pytest

from app.control.engine import ControlEngine
from app.core.db import SessionLocal
from app.main import app
from app.models import ControlCommand
from app.telemetry.runtime import TelemetryRuntime
from tests.conftest import login, type_by_key

TERMINAL = {"COMPLETED", "REJECTED", "FAILED", "TIMED_OUT", "CANCELLED"}


@pytest.fixture
def live(client):
    rt = TelemetryRuntime(SessionLocal, poll_s=0.25)
    client.portal.call(rt.start)
    app.state.telemetry = rt
    eng = ControlEngine(rt, SessionLocal)
    eng.bind_loop(client.portal.call(_current_loop))
    app.state.control = eng
    yield rt
    client.portal.call(rt.stop)
    app.state.telemetry = None
    app.state.control = None


async def _current_loop():
    import asyncio

    return asyncio.get_running_loop()


def wait_online(rt, device_ids=None, timeout=8):
    end = time.time() + timeout
    while time.time() < end:
        ctxs = [c for c in rt.devices.values() if device_ids is None or c.id in device_ids]
        if ctxs and all(rt.device_online(c) for c in ctxs):
            return
        time.sleep(0.2)
    raise AssertionError("devices did not come online")


def wait_done(client, h, cmd_id, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        c = client.get(f"/api/commands/{cmd_id}", headers=h).json()
        if c["status"] in TERMINAL:
            return c
        time.sleep(0.2)
    raise AssertionError(f"command not finished: {c['status']}")


def demo_asset(client, h, code):
    fid = client.get("/api/factories", headers=h).json()[0]["id"]
    return next(a for a in client.get(f"/api/assets?factory_id={fid}", headers=h).json() if a["code"] == code)


def test_simulated_stop_start_verified(client, live, demo_admin):
    wait_online(live)
    op = login(client, "operator@demo.example.com")
    cv = demo_asset(client, op, "CV-101")
    r = client.post(f"/api/assets/{cv['id']}/commands", json={"control": "stop", "confirm": True, "reason": "test"}, headers=op)
    assert r.status_code == 201, r.text
    c = wait_done(client, op, r.json()["id"])
    assert c["status"] == "COMPLETED" and c["verified"] is True, c
    assert [e["status"] for e in c["events"]] == ["REQUESTED", "VALIDATING", "APPROVED", "SENT", "ACKNOWLEDGED", "COMPLETED"]
    assert c["simulated"] is True
    time.sleep(2.1)  # per-asset rate limit
    c = wait_done(client, op, client.post(f"/api/assets/{cv['id']}/commands", json={"control": "start", "confirm": True}, headers=op).json()["id"])
    assert c["status"] == "COMPLETED" and c["verified"]
    log = client.get(f"/api/audit?entity_id={cv['id']}", headers=demo_admin).json()
    assert any(e["action"] == "command.completed" for e in log)


def test_validation_rejections(client, live, demo_admin):
    wait_online(live)
    op = login(client, "operator@demo.example.com")
    viewer = login(client, "viewer@demo.example.com")
    cv = demo_asset(client, op, "CV-102")
    r = client.post(f"/api/assets/{cv['id']}/commands", json={"control": "start"}, headers=op).json()
    assert r["status"] == "REJECTED" and any(ch["name"] == "Confirmation" and not ch["ok"] for ch in r["checks"])
    r = client.post(f"/api/assets/{cv['id']}/commands", json={"control": "start", "confirm": True}, headers=viewer).json()
    assert r["status"] == "REJECTED" and not next(ch for ch in r["checks"] if ch["name"] == "Permission")["ok"]
    r = client.post(f"/api/assets/{cv['id']}/commands", json={"control": "self_destruct", "confirm": True}, headers=op).json()
    assert r["status"] == "REJECTED"
    r = client.post(f"/api/assets/{cv['id']}/commands/validate", json={"control": "speed_setpoint", "params": {"value": 5}, "confirm": True}, headers=op).json()
    assert not r["ok"] and "above maximum" in next(ch for ch in r["checks"] if ch["name"] == "Parameters")["detail"]
    # dry run sends nothing
    assert client.get(f"/api/commands?asset_id={cv['id']}&status=SENT,ACKNOWLEDGED", headers=op).json() == []


def test_four_eyes_approval(client, live, demo_admin):
    wait_online(live)
    op = login(client, "operator@demo.example.com")
    eng = login(client, "engineer@demo.example.com")
    cv = demo_asset(client, op, "CV-201")
    r = client.post(f"/api/assets/{cv['id']}/commands", json={"control": "speed_setpoint", "params": {"value": 1.1}, "confirm": True}, headers=op).json()
    assert r["status"] == "PENDING_APPROVAL", r
    assert client.post(f"/api/commands/{r['id']}/approve", headers=op).status_code == 403  # can't self-approve (and no perm)
    a = client.post(f"/api/commands/{r['id']}/approve", headers=eng)
    assert a.status_code == 200, a.text
    c = wait_done(client, op, r["id"])
    assert c["status"] == "COMPLETED" and c["approved_by"] == "engineer@demo.example.com" and c["verified"], c
    # engineer's own request can't be approved by themself either
    time.sleep(2.1)
    r = client.post(f"/api/assets/{cv['id']}/commands", json={"control": "speed_setpoint", "params": {"value": 1.2}, "confirm": True}, headers=eng).json()
    assert client.post(f"/api/commands/{r['id']}/approve", headers=eng).status_code == 403
    assert client.post(f"/api/commands/{r['id']}/cancel", headers=eng).json()["status"] == "CANCELLED"


def test_interlock_fails_closed(client, live, demo_admin):
    wait_online(live)
    eng = login(client, "engineer@demo.example.com")
    cv = demo_asset(client, eng, "CV-302")
    fid = cv["factory_id"]
    t = type_by_key(client, demo_admin, "temperature_sensor")
    src = client.post("/api/assets", json={"factory_id": fid, "asset_type_id": t["id"], "code": "TT-NODATA", "name": "No data"}, headers=demo_admin).json()
    lk = client.post(f"/api/assets/{cv['id']}/interlocks", json={"control_key": "start", "source_asset_id": src["id"], "measurement": "temp",
                                                                 "operator": "<", "value": "50", "message": "Too hot"}, headers=eng)
    assert lk.status_code == 201, lk.text
    r = client.post(f"/api/assets/{cv['id']}/commands/validate", json={"control": "start", "confirm": True}, headers=eng).json()
    il = next(ch for ch in r["checks"] if ch["name"].startswith("Interlock"))
    assert not r["ok"] and not il["ok"] and "fail closed" in il["detail"]
    # stop is never blocked by a start interlock
    r = client.post(f"/api/assets/{cv['id']}/commands/validate", json={"control": "stop", "confirm": True}, headers=eng).json()
    assert r["ok"], r
    client.delete(f"/api/interlocks/{lk.json()['id']}", headers=eng)
    client.delete(f"/api/assets/{src['id']}", headers=demo_admin)


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_modbus_plc_end_to_end(client, live, new_org, factory):
    """Real Modbus TCP: platform → PLC run coil → PLC ramps → telemetry verifies. PLC E-stop overrides."""
    from labsim.plc import Line3Plc

    plc = Line3Plc()
    port = _free_port()
    # Wrap the task in a list: the portal would otherwise await it (and the server never returns).
    (task,) = client.portal.call(lambda: [__import__("asyncio").ensure_future(plc.run("127.0.0.1", port))])
    h, _ = new_org()
    f = factory(h)
    conv = client.post("/api/assets", json={"factory_id": f["id"], "asset_type_id": type_by_key(client, h, "conveyor")["id"], "code": "CV-1", "name": "Conv"}, headers=h).json()
    panel = client.post("/api/assets", json={"factory_id": f["id"], "asset_type_id": type_by_key(client, h, "control_panel")["id"], "code": "CP-1", "name": "Panel"}, headers=h).json()
    smap = "map=0=stopped;1=running;2=fault;3=maintenance;4=emergency_stop"
    d = client.post("/api/devices", headers=h, json={
        "factory_id": f["id"], "asset_id": conv["id"], "name": "PLC conveyor", "protocol": "modbus_tcp", "enabled": True,
        "connection_config": {"host": "127.0.0.1", "port": port, "unit_id": 1},
        "point_mappings": [{"point": f"hr:1:uint16:{smap}", "measurement": "state"}, {"point": "hr:2", "measurement": "speed_mps", "scale": 0.01}],
        "control_mappings": [{"control": "start", "point": "co:0", "value": True}, {"control": "stop", "point": "co:0", "value": False}]})
    assert d.status_code == 201, d.text
    p = client.post("/api/devices", headers=h, json={
        "factory_id": f["id"], "asset_id": panel["id"], "name": "PLC panel", "protocol": "modbus_tcp", "enabled": True,
        "connection_config": {"host": "127.0.0.1", "port": port, "unit_id": 1},
        "point_mappings": [{"point": "hr:30:uint16:map=0=healthy;1=tripped", "measurement": "estop_status"}]}).json()
    # writes to input tables are refused at configuration time
    bad = client.patch(f"/api/devices/{d.json()['id']}", headers=h, json={"control_mappings": [{"control": "start", "point": "ir:0", "value": 1}]})
    assert bad.status_code == 422
    client.post(f"/api/assets/{conv['id']}/interlocks", headers=h, json={"control_key": "start", "source_asset_id": panel["id"],
                                                                        "measurement": "estop_status", "operator": "==", "value": "healthy"})
    client.portal.call(live.refresh_devices)
    wait_online(live, {d.json()["id"], p["id"]})
    assert client.post(f"/api/devices/{d.json()['id']}/test", headers=h).json()["ok"]

    c = wait_done(client, h, client.post(f"/api/assets/{conv['id']}/commands", json={"control": "start", "confirm": True}, headers=h).json()["id"])
    assert c["status"] == "COMPLETED" and c["verified"], c
    assert plc.status()["line_run_request"] is True

    plc.press_estop()  # physical E-stop: the PLC drops the output itself
    time.sleep(1.2)
    assert plc.status()["line_run_request"] is False
    time.sleep(2.2)
    r = client.post(f"/api/assets/{conv['id']}/commands", json={"control": "start", "confirm": True}, headers=h).json()
    assert r["status"] == "REJECTED" and "estop_status" in r["result_message"]
    diag = client.get(f"/api/devices/{d.json()['id']}/diagnostics", headers=h).json()
    assert diag["online"] and diag["samples"] > 0
    for dev in (d.json()["id"], p["id"]):
        client.patch(f"/api/devices/{dev}", json={"enabled": False}, headers=h)
    client.portal.call(lambda: task.cancel())


def test_restart_recovery(client, demo_admin):
    from app.models.base import utcnow

    a = demo_asset(client, demo_admin, "CV-101")
    with SessionLocal() as db:
        cmd = ControlCommand(org_id=a["asset_type"]["id"] and client.get("/api/auth/me", headers=demo_admin).json()["organization"]["id"],
                             factory_id=a["factory_id"], asset_id=a["id"], control_key="start", status="SENT",
                             requested_by="x@example.com", requested_at=utcnow(), events=[])
        db.add(cmd)
        db.commit()
        cid = cmd.id
    assert ControlEngine(None, SessionLocal).recover() >= 1
    c = client.get(f"/api/commands/{cid}", headers=demo_admin).json()
    assert c["status"] == "FAILED" and "state unknown" in c["result_message"]

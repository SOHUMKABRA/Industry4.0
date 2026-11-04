import asyncio
import socket
import uuid

import pytest

from app.core.db import SessionLocal
from app.telemetry.alerts import AlertEngine, AssetMeta
from tests.conftest import auth, login

DEFS = {"temp": {"key": "temp", "label": "Temperature", "unit": "°C", "warn_high": 70, "alarm_high": 80},
        "state": {"key": "state", "label": "State"}}


def test_alert_lifecycle_unit():
    events = []
    eng = AlertEngine(lambda o, f, rec: events.append(rec))
    m = AssetMeta("a1", "o1", "f1", "TT-1", "Sensor", DEFS)
    t = 1000.0
    eng.evaluate(m, "temp", 60, "live", t)
    assert not eng.active
    eng.evaluate(m, "temp", 72, "live", t + 1)
    eng.evaluate(m, "temp", 69, "live", t + 2)  # brief excursion: suppressed by the on-delay
    eng.evaluate(m, "temp", 72, "live", t + 3)
    assert not eng.active
    eng.evaluate(m, "temp", 72.5, "live", t + 6.5)
    (alert,) = eng.active.values()
    assert alert.severity == "warning"
    eng.mark_acked(alert.id, "op@x", __import__("datetime").datetime.now())
    eng.evaluate(m, "temp", 85, "live", t + 7)  # escalation is immediate and re-arms acknowledgement
    assert alert.severity == "alarm" and alert.acked is False
    eng.evaluate(m, "temp", 69.5, "live", t + 8)  # inside limit but within 2 % deadband: stays active
    eng.evaluate(m, "temp", 65, "live", t + 9)
    eng.evaluate(m, "temp", 65, "live", t + 15)  # off-delay not yet elapsed
    assert eng.active
    eng.evaluate(m, "temp", 65, "live", t + 20)
    assert not eng.active and events[-1]["active"] is False
    eng.evaluate(m, "state", "fault", "live", t + 21)  # equipment faults raise immediately
    assert next(iter(eng.active.values())).record["kind"] == "state"
    eng.evaluate(m, "state", "running", "live", t + 22)
    eng.evaluate(m, "state", "running", "live", t + 25.5)
    assert not eng.active
    eng.device_comm("o1", "f1", "d1", "a1", "Dev", False, "live")
    assert ("d1", "comm", "") in eng.active
    eng.device_comm("o1", "f1", "d1", "a1", "Dev", True, "live")
    assert not eng.active


def test_alert_persistence_and_ack_api(client, demo_admin):
    from app.main import app
    from app.telemetry.runtime import TelemetryRuntime

    rt = TelemetryRuntime(SessionLocal)
    app.state.telemetry = rt
    try:
        fid = client.get("/api/factories", headers=demo_admin).json()[0]["id"]
        me = client.get("/api/auth/me", headers=demo_admin).json()
        a = client.get(f"/api/assets?factory_id={fid}&q=TT-101", headers=demo_admin).json()[0]
        meta = AssetMeta(a["id"], me["organization"]["id"], fid, "TT-101", "x", DEFS)
        rt.alerts.evaluate(meta, "temp", 90, "simulated", 100.0)
        rt.alerts.evaluate(meta, "temp", 90, "simulated", 104.0)
        rt.flush()
        active = client.get(f"/api/alerts?factory_id={fid}", headers=demo_admin).json()
        assert active[0]["severity"] == "alarm" and not active[0]["acked"]
        viewer = login(client, "viewer@demo.example.com")
        assert client.post(f"/api/alerts/{active[0]['id']}/ack", headers=viewer).status_code == 403
        op = login(client, "operator@demo.example.com")
        r = client.post(f"/api/alerts/{active[0]['id']}/ack", headers=op).json()
        assert r["acked"] and r["acked_by"] == "operator@demo.example.com"
        rt.alerts.evaluate(meta, "temp", 40, "simulated", 105.0)
        rt.alerts.evaluate(meta, "temp", 40, "simulated", 120.0)
        rt.flush()
        assert client.get(f"/api/alerts?factory_id={fid}", headers=demo_admin).json() == []
        assert client.get(f"/api/alerts?factory_id={fid}&state=history", headers=demo_admin).json()[0]["cleared_at"]
    finally:
        app.state.telemetry = None


def test_user_management_and_passwords(client, new_org):
    h, me = new_org()
    email = f"tech{uuid.uuid4().hex[:6]}@acme.example.com"
    r = client.post("/api/users", json={"email": email, "name": "Tech", "role": "operator"}, headers=h).json()
    temp = r["temporary_password"]
    assert temp and r["user"]["must_change_password"]
    tok = client.post("/api/auth/login", json={"email": email, "password": temp}).json()
    th = auth(tok["access_token"])
    assert tok["me"]["user"]["must_change_password"] is True
    assert client.get("/api/users", headers=th).status_code == 403
    assert client.post("/api/auth/change-password", json={"current_password": "wrong", "new_password": "newpass123"}, headers=th).status_code == 400
    assert client.post("/api/auth/change-password", json={"current_password": temp, "new_password": "newpass123"}, headers=th).status_code == 204
    assert client.post("/api/auth/login", json={"email": email, "password": "newpass123"}).json()["me"]["user"]["must_change_password"] is False
    # last admin protection
    assert client.patch(f"/api/users/{me['user']['id']}", json={"role": "viewer"}, headers=h).status_code == 409
    uid = r["user"]["id"]
    assert client.patch(f"/api/users/{uid}", json={"is_active": False}, headers=h).json()["is_active"] is False
    assert client.post("/api/auth/login", json={"email": email, "password": "newpass123"}).status_code == 401


def test_login_rate_limit(client):
    email = f"victim{uuid.uuid4().hex[:6]}@acme.example.com"
    codes = [client.post("/api/auth/login", json={"email": email, "password": "nope"}).status_code for _ in range(10)]
    assert codes[:8] == [401] * 8 and codes[-1] == 429


def test_security_headers(client):
    r = client.get("/api/health")
    assert r.headers["x-frame-options"] == "DENY" and "default-src 'self'" in r.headers["content-security-policy"]
    assert r.json()["version"] == "1.1.0"


def test_schema_sync_adds_columns(tmp_path):
    from sqlalchemy import create_engine, inspect, text

    from app.core.schema_sync import sync_columns

    eng = create_engine(f"sqlite:///{tmp_path}/old.db")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE devices (id VARCHAR(36) PRIMARY KEY, name VARCHAR(200))"))
        c.execute(text("INSERT INTO devices (id, name) VALUES ('d1', 'old')"))
    added = sync_columns(eng)
    assert "devices.control_mappings" in added
    cols = {c["name"] for c in inspect(eng).get_columns("devices")}
    assert {"control_mappings", "enabled", "protocol"} <= cols
    with eng.connect() as c:
        assert c.execute(text("SELECT name, control_mappings FROM devices")).one() == ("old", "[]")


def test_mqtt_adapter_with_broker():
    from amqtt.broker import Broker

    from app.adapters.mqtt import MqttAdapter

    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()

    async def run():
        import aiomqtt

        broker = Broker({"listeners": {"default": {"type": "tcp", "bind": f"127.0.0.1:{port}"}}})
        await broker.start()
        try:
            a = MqttAdapter({"host": "127.0.0.1", "port": port, "topic_filter": "t/#"})
            assert (await a.test_connection())[0]
            got = []
            await a.start(["t/dev#v", "t/raw"], got.extend)
            await asyncio.sleep(0.5)
            async with aiomqtt.Client("127.0.0.1", port) as c:
                await c.publish("t/dev", '{"v": 4.5, "seq": 3, "ts": 1700000000000}')
                await c.publish("t/raw", "12.5")
                await c.publish("t/other", "1")
                await asyncio.sleep(0.5)
            assert {(x.point, x.value) for x in got} == {("t/dev#v", 4.5), ("t/raw", 12.5)}
            assert next(x for x in got if x.point == "t/dev#v").seq == 3
            ack = await a.write_command("t/cmd", "running")
            assert ack.accepted
            await a.stop()
            bad = MqttAdapter({"host": "127.0.0.1", "port": 1})
            assert not (await bad.test_connection())[0]
        finally:
            await broker.shutdown()

    asyncio.run(run())

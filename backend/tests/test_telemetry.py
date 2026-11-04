import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.adapters.base import Sample
from app.adapters.simulated import SimulatedAdapter
from app.core.db import SessionLocal
from app.main import app
from app.telemetry.runtime import TelemetryRuntime


@pytest.fixture
def runtime(client):
    rt = TelemetryRuntime(SessionLocal, poll_s=1.0)
    app.state.telemetry = rt
    yield rt
    app.state.telemetry = None


def demo_ids(client, h):
    fid = client.get("/api/factories", headers=h).json()[0]["id"]
    assets = {a["code"]: a for a in client.get(f"/api/assets?factory_id={fid}", headers=h).json()}
    return fid, assets


def demo_ctxs(runtime, client, h):
    org = client.get("/api/auth/me", headers=h).json()["organization"]["id"]
    return [c for c in runtime.devices.values() if c.org_id == org]


def test_runtime_loads_enabled_bound_devices(runtime, client, demo_admin):
    asyncio.run(runtime.refresh_devices())
    ctxs = demo_ctxs(runtime, client, demo_admin)
    assert len(ctxs) == 23
    assert all(c.source == "simulated" for c in ctxs)


def test_ingest_mapping_dedupe_and_ordering(runtime, client, demo_admin):
    asyncio.run(runtime.refresh_devices())
    ctx = next(c for c in runtime.devices.values() if "temp" in [m for m, _, _ in c.mappings.values()])
    ctx.mappings["temp"] = ("temp", 2.0, 1.0)  # scale/offset
    now = datetime.now(UTC)
    out = runtime.ingest(ctx, [Sample("temp", 10.0, now, seq=5)])
    assert out[0].value == 21.0 and out[0].source == "simulated"
    # duplicate sequence ignored
    assert runtime.ingest(ctx, [Sample("temp", 99.0, now, seq=5)]) == []
    assert runtime.stats["duplicates"] == 1
    # older timestamp: kept for history, not for latest value
    before = len(runtime._buffer)
    assert runtime.ingest(ctx, [Sample("temp", 1.0, now - timedelta(seconds=10), seq=6)]) == []
    assert len(runtime._buffer) == before + 1
    assert runtime.latest[(ctx.asset_id, "temp")].value == 21.0
    # bad quality / unmapped points are not ingested
    assert runtime.ingest(ctx, [Sample("temp", None, now, quality="bad", seq=7), Sample("nope", 1, now, seq=8)]) == []


def test_poll_flush_history_and_snapshot(runtime, client, demo_admin):
    asyncio.run(runtime.refresh_devices())

    ctxs = demo_ctxs(runtime, client, demo_admin)

    async def poll_twice():
        for _ in range(2):
            await asyncio.gather(*(runtime.poll_device(c) for c in ctxs))
            await asyncio.sleep(0.01)

    asyncio.run(poll_twice())
    assert runtime.flush() > 0
    fid, assets = demo_ids(client, demo_admin)
    snap = client.get(f"/api/live/snapshot?factory_id={fid}", headers=demo_admin).json()
    keys = {(p[0], p[1]) for p in snap["points"]}
    assert (assets["MTR-101"]["id"], "rpm") in keys
    assert all(p[5] == "simulated" for p in snap["points"])
    assert all(d["online"] for d in snap["devices"])
    h = client.get(f"/api/assets/{assets['MTR-101']['id']}/history?measurement=rpm&minutes=5&buckets=10", headers=demo_admin).json()
    assert h["points"] and h["points"][0]["avg"] > 1000
    st = client.get(f"/api/assets/{assets['CV-101']['id']}/history?measurement=state&minutes=5", headers=demo_admin).json()
    assert st["points"][-1]["last"] == "running"


def test_disabled_device_values_are_dropped(runtime, client, demo_admin):
    asyncio.run(runtime.refresh_devices())
    ctx = next(iter(runtime.devices.values()))
    asyncio.run(runtime.poll_device(ctx))
    assert any(k[0] == ctx.asset_id for k in runtime.latest)
    client.patch(f"/api/devices/{ctx.id}", json={"enabled": False}, headers=demo_admin)
    asyncio.run(runtime.refresh_devices())
    assert ctx.id not in runtime.devices
    assert not any(k[0] == ctx.asset_id and k[1] in [m for m, _, _ in ctx.mappings.values()] for k in runtime.latest)
    client.patch(f"/api/devices/{ctx.id}", json={"enabled": True}, headers=demo_admin)


def test_simulated_states_gate_signals():
    a = SimulatedAdapter({"profile": "conveyor_intermittent", "seed": 7})
    t0 = 1_000_000.0
    states = {a.value_at("state", t0 + s) for s in range(0, 300, 5)}
    assert {"running", "stopped", "fault"} <= states
    for s in range(0, 300, 5):
        st = a.value_at("state", t0 + s)
        speed = a.value_at("speed_mps", t0 + s)
        assert (speed == 0.0) == (st != "running")


def test_websocket_requires_ticket_and_streams(runtime, client, demo_admin):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/live/ws?ticket=bogus") as ws:
            ws.receive_text()
    asyncio.run(runtime.refresh_devices())
    asyncio.run(runtime.poll_device(next(iter(runtime.devices.values()))))
    fid, _ = demo_ids(client, demo_admin)
    ticket = client.post("/api/live/ticket", headers=demo_admin).json()["ticket"]
    with client.websocket_connect(f"/api/live/ws?ticket={ticket}") as ws:
        ws.send_json({"type": "subscribe", "factory_id": fid})
        snap = ws.receive_json()
        assert snap["type"] == "snapshot" and snap["points"]
        ws.send_json({"type": "ping", "t": 42})
        msgs = [ws.receive_json() for _ in range(2)]
        assert {"type": "pong", "t": 42} in msgs or any(m.get("type") == "pong" for m in msgs)
    # ticket is single-use
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/api/live/ws?ticket={ticket}") as ws:
            ws.receive_text()


def test_websocket_cannot_subscribe_other_tenant(runtime, client, new_org, factory, demo_admin):
    h, _ = new_org()
    f = factory(h)
    ticket = client.post("/api/live/ticket", headers=demo_admin).json()["ticket"]
    with client.websocket_connect(f"/api/live/ws?ticket={ticket}") as ws:
        ws.send_json({"type": "subscribe", "factory_id": f["id"]})
        assert ws.receive_json()["type"] == "error"


def test_dashboards(client, demo_admin, new_org, factory):
    from tests.conftest import login

    fid, assets = demo_ids(client, demo_admin)
    ds = client.get(f"/api/dashboards?factory_id={fid}", headers=demo_admin).json()
    assert ds and ds[0]["widgets"]
    operator = login(client, "operator@demo.example.com")
    r = client.post("/api/dashboards", json={"factory_id": fid, "name": "Mine", "widgets": [
        {"id": "a", "type": "value", "asset_id": assets["TT-101"]["id"], "measurement": "temp"}]}, headers=operator)
    assert r.status_code == 201
    mine = r.json()["id"]
    assert client.patch(f"/api/dashboards/{mine}", json={"name": "Renamed"}, headers=operator).status_code == 200
    # operators can't change other people's dashboards
    assert client.patch(f"/api/dashboards/{ds[0]['id']}", json={"name": "x"}, headers=operator).status_code == 403
    # widgets can't point at another tenant's assets
    h, _ = new_org()
    f2 = factory(h)
    r = client.post("/api/dashboards", json={"factory_id": f2["id"], "name": "x", "widgets": [
        {"id": "a", "type": "value", "asset_id": assets["TT-101"]["id"], "measurement": "temp"}]}, headers=h)
    assert r.status_code == 422
    assert client.delete(f"/api/dashboards/{mine}", headers=operator).status_code == 204

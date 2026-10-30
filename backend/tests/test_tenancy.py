"""One organization must never see or modify another's data."""

from tests.conftest import type_by_key


def test_cross_tenant_isolation(client, new_org, factory, demo_admin):
    a_headers, _ = new_org()
    b_headers, _ = new_org()
    fa = factory(a_headers, "A plant")
    t = type_by_key(client, a_headers, "temperature_sensor")
    asset = client.post(
        "/api/assets",
        json={"factory_id": fa["id"], "asset_type_id": t["id"], "code": "TT-1", "name": "Temp"},
        headers=a_headers,
    ).json()
    dev = client.post(
        "/api/devices",
        json={"factory_id": fa["id"], "name": "sim", "protocol": "simulated", "connection_config": {"profile": "temperature"}},
        headers=a_headers,
    ).json()

    # Lists are scoped
    assert client.get("/api/factories", headers=b_headers).json() == []
    assert client.get("/api/assets", headers=b_headers).json() == []
    assert client.get("/api/devices", headers=b_headers).json() == []
    assert all(x["id"] != t["id"] for x in client.get("/api/asset-types", headers=b_headers).json())
    assert client.get("/api/audit", headers=b_headers).json()[0]["action"] == "org.create"

    # Direct access by id is 404, never 403
    for url in (f"/api/factories/{fa['id']}", f"/api/assets/{asset['id']}", f"/api/devices/{dev['id']}",
                f"/api/asset-types/{t['id']}", f"/api/factories/{fa['id']}/summary"):
        assert client.get(url, headers=b_headers).status_code == 404, url
    assert client.patch(f"/api/assets/{asset['id']}", json={"name": "x"}, headers=b_headers).status_code == 404
    assert client.delete(f"/api/assets/{asset['id']}", headers=b_headers).status_code == 404
    assert client.post(f"/api/devices/{dev['id']}/test", headers=b_headers).status_code == 404

    # Cannot reference another org's objects when creating
    fb = factory(b_headers, "B plant")
    r = client.post(
        "/api/assets",
        json={"factory_id": fb["id"], "asset_type_id": t["id"], "code": "X", "name": "X"},
        headers=b_headers,
    )
    assert r.status_code == 404
    r = client.post(
        "/api/devices",
        json={"factory_id": fb["id"], "asset_id": asset["id"], "name": "x", "protocol": "simulated",
              "connection_config": {"profile": "temperature"}},
        headers=b_headers,
    )
    assert r.status_code == 404

    # Asset codes are unique per org, not globally
    tb = type_by_key(client, b_headers, "temperature_sensor")
    r = client.post(
        "/api/assets",
        json={"factory_id": fb["id"], "asset_type_id": tb["id"], "code": "TT-1", "name": "Temp"},
        headers=b_headers,
    )
    assert r.status_code == 201

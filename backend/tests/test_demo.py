def test_demo_factory_seeded(client, demo_admin):
    factories = client.get("/api/factories", headers=demo_admin).json()
    assert [f["name"] for f in factories] == ["Riverside Plant"]
    fid = factories[0]["id"]
    s = client.get(f"/api/factories/{fid}/summary", headers=demo_admin).json()
    assert s["asset_count"] == 23 and s["device_count"] == 9 and s["areas"] == 3
    assert s["live_data_available"] is False
    structure = client.get(f"/api/factories/{fid}", headers=demo_admin).json()
    assert len(structure["floors"][0]["areas"]) == 3
    lines = client.get("/api/assets?category=production", headers=demo_admin).json()
    assert len(lines) == 3


def test_production_refuses_default_secrets():
    import pytest

    from app.core.config import Settings

    with pytest.raises(RuntimeError):
        Settings(twin_env="production").check_production_safety()


def test_timestamps_are_utc_aware(client, demo_admin):
    """Naive timestamps get read as local time by browsers."""
    a = client.get("/api/assets?limit=1", headers=demo_admin).json()[0]
    assert a["created_at"].endswith(("Z", "+00:00"))
    e = client.get("/api/audit?limit=1", headers=demo_admin).json()[0]
    assert e["at"].endswith(("Z", "+00:00"))

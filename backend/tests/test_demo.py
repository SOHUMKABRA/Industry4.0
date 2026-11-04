def test_demo_factory_seeded(client, demo_admin):
    factories = client.get("/api/factories", headers=demo_admin).json()
    assert [f["name"] for f in factories] == ["Riverside Plant"]
    fid = factories[0]["id"]
    s = client.get(f"/api/factories/{fid}/summary", headers=demo_admin).json()
    assert s["asset_count"] == 23 and s["device_count"] == 23 and s["areas"] == 3
    assert s["live_data_available"] is False
    structure = client.get(f"/api/factories/{fid}", headers=demo_admin).json()
    assert len(structure["floors"][0]["areas"]) == 3
    lines = client.get("/api/assets?category=production", headers=demo_admin).json()
    assert len(lines) == 3


def test_production_refuses_default_secrets():
    import pytest

    from app.core.config import DEV_SECRET, Settings

    with pytest.raises(RuntimeError):
        Settings(_env_file=None, twin_env="production", secret_key=DEV_SECRET, credential_key="").check_production_safety()
    with pytest.raises(RuntimeError):
        Settings(_env_file=None, twin_env="production", secret_key="x" * 40, credential_key="").check_production_safety()
    Settings(_env_file=None, twin_env="production", secret_key="x" * 40, credential_key="k").check_production_safety()


def test_timestamps_are_utc_aware(client, demo_admin):
    """Naive timestamps get read as local time by browsers."""
    a = client.get("/api/assets?limit=1", headers=demo_admin).json()[0]
    assert a["created_at"].endswith(("Z", "+00:00"))
    e = client.get("/api/audit?limit=1", headers=demo_admin).json()[0]
    assert e["at"].endswith(("Z", "+00:00"))


def test_demo_seeders_are_idempotent_with_replaced_devices():
    """Re-running every seeder must not re-create simulators that were renamed or replaced."""
    from app.core.db import SessionLocal
    from app.models import Device
    from app.seed.demo_field import ensure_field_devices
    from app.seed.demo_layout import ensure_demo_extras

    with SessionLocal() as db:
        d = db.query(Device).filter(Device.name == "CV-301 simulator").one()
        d.name = "CV-301 simulator (replaced by field device)"
        d.enabled = False
        db.commit()
        before = db.query(Device).count()
        ensure_demo_extras(db)
        ensure_field_devices(db)
        ensure_demo_extras(db)
        assert db.query(Device).count() == before
        d.name = "CV-301 simulator"
        d.enabled = True
        db.commit()

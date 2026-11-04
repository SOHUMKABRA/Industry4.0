import uuid

from tests.conftest import login, type_by_key


def oid():
    return str(uuid.uuid4())


def obj(**kw):
    return {"id": oid(), "kind": "wall", "name": "W", "position": [0, 0, 0], "size": [1, 1, 1]} | kw


def test_demo_layout_seeded(client, demo_admin):
    fid = client.get("/api/factories", headers=demo_admin).json()[0]["id"]
    s = client.get(f"/api/factories/{fid}/scene", headers=demo_admin).json()
    assert s["scene"]["version"] >= 1
    kinds = {o["kind"] for o in s["objects"]}
    assert {"asset", "wall", "pillar", "walkway", "safety_zone"} <= kinds
    assert len([o for o in s["objects"] if o["kind"] == "asset"]) == 23


def test_save_versioning_and_restore(client, new_org, factory):
    h, _ = new_org()
    f = factory(h)
    t = type_by_key(client, h, "motor")
    a = client.post("/api/assets", json={"factory_id": f["id"], "asset_type_id": t["id"], "code": "M1", "name": "M"}, headers=h).json()
    s = client.get(f"/api/factories/{f['id']}/scene", headers=h).json()
    sid = s["scene"]["id"]
    assert s["scene"]["version"] == 0 and s["objects"] == []

    v1 = [obj(), obj(kind="asset", asset_id=a["id"], name="Motor", position=[3, 0, 4])]
    r = client.put(f"/api/scenes/{sid}", json={"base_version": 0, "message": "first", "objects": v1}, headers=h)
    assert r.status_code == 200 and r.json()["scene"]["version"] == 1
    assert len(r.json()["objects"]) == 2

    # Stale base version is rejected (no silent overwrite)
    assert client.put(f"/api/scenes/{sid}", json={"base_version": 0, "objects": []}, headers=h).status_code == 409
    r = client.put(f"/api/scenes/{sid}", json={"base_version": 1, "message": "cleared", "objects": []}, headers=h)
    assert r.json()["scene"]["version"] == 2 and r.json()["objects"] == []

    versions = client.get(f"/api/scenes/{sid}/versions", headers=h).json()
    assert [v["version"] for v in versions] == [2, 1]
    r = client.post(f"/api/scenes/{sid}/versions/1/restore", headers=h)
    assert r.status_code == 200
    assert r.json()["scene"]["version"] == 3 and len(r.json()["objects"]) == 2

    # Deleting the asset removes its visual; restoring an old version skips it
    client.delete(f"/api/assets/{a['id']}", headers=h)
    assert len(client.get(f"/api/factories/{f['id']}/scene", headers=h).json()["objects"]) == 1
    r = client.post(f"/api/scenes/{sid}/versions/1/restore", headers=h).json()
    assert len(r["objects"]) == 1


def test_scene_validation(client, new_org, factory):
    h, _ = new_org()
    f = factory(h)
    other = factory(h, "Other")
    t = type_by_key(client, h, "motor")
    a_other = client.post("/api/assets", json={"factory_id": other["id"], "asset_type_id": t["id"], "code": "X", "name": "X"}, headers=h).json()
    a = client.post("/api/assets", json={"factory_id": f["id"], "asset_type_id": t["id"], "code": "Y", "name": "Y"}, headers=h).json()
    sid = client.get(f"/api/factories/{f['id']}/scene", headers=h).json()["scene"]["id"]
    bad = [
        [obj(kind="asset", asset_id=a_other["id"])],             # asset in another factory
        [obj(kind="asset")],                                     # asset object without asset
        [obj(asset_id=a["id"])],                                 # wall with asset
        [obj(kind="asset", asset_id=a["id"]), obj(kind="asset", asset_id=a["id"])],  # placed twice
        [obj(size=[0, 1, 1])],
        [obj(color="red")],
    ]
    dup = obj()
    bad.append([dup, dup])
    for objs in bad:
        assert client.put(f"/api/scenes/{sid}", json={"base_version": 0, "objects": objs}, headers=h).status_code == 422, objs


def test_scene_permissions_and_tenancy(client, new_org, factory, demo_admin):
    h, _ = new_org()
    f = factory(h)
    sid = client.get(f"/api/factories/{f['id']}/scene", headers=h).json()["scene"]["id"]
    assert client.put(f"/api/scenes/{sid}", json={"base_version": 0, "objects": []}, headers=demo_admin).status_code == 404
    assert client.get(f"/api/scenes/{sid}/versions", headers=demo_admin).status_code == 404
    viewer = login(client, "viewer@demo.example.com")
    demo_sid = client.get(f"/api/factories/{client.get('/api/factories', headers=viewer).json()[0]['id']}/scene", headers=viewer).json()["scene"]["id"]
    assert client.put(f"/api/scenes/{demo_sid}", json={"base_version": 1, "objects": []}, headers=viewer).status_code == 403


def test_model_upload(client, new_org):
    h, _ = new_org()
    glb = b"glTF" + b"\x02\x00\x00\x00" + b"\x00" * 64
    r = client.post("/api/models", files={"file": ("pump.glb", glb, "model/gltf-binary")}, headers=h)
    assert r.status_code == 201, r.text
    mid = r.json()["id"]
    assert client.get(f"/api/models/{mid}/file", headers=h).content == glb
    assert client.post("/api/models", files={"file": ("x.glb", b"not a glb file", "x")}, headers=h).status_code == 422
    assert client.post("/api/models", files={"file": ("x.fbx", b"x", "x")}, headers=h).status_code == 422
    assert client.post("/api/models", files={"file": ("x.exe", b"MZ", "x")}, headers=h).status_code == 422
    h2, _ = new_org()
    assert client.get(f"/api/models/{mid}/file", headers=h2).status_code == 404
    assert client.delete(f"/api/models/{mid}", headers=h).status_code == 204

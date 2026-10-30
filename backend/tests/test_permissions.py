from tests.conftest import login


def test_role_matrix(client, demo_admin):
    viewer = login(client, "viewer@demo.example.com")
    operator = login(client, "operator@demo.example.com")
    engineer = login(client, "engineer@demo.example.com")
    factory_id = client.get("/api/factories", headers=viewer).json()[0]["id"]
    device_id = client.get("/api/devices", headers=viewer).json()[0]["id"]

    assert client.post("/api/factories", json={"name": "x"}, headers=viewer).status_code == 403
    assert client.post("/api/factories", json={"name": "x"}, headers=operator).status_code == 403
    assert client.get("/api/audit", headers=operator).status_code == 403
    assert client.post(f"/api/devices/{device_id}/test", headers=viewer).status_code == 403
    assert client.post(f"/api/devices/{device_id}/test", headers=operator).status_code == 200
    assert client.patch(f"/api/devices/{device_id}", json={"name": "y"}, headers=operator).status_code == 403
    # Engineers configure but cannot delete whole factories
    assert client.delete(f"/api/factories/{factory_id}", headers=engineer).status_code == 403

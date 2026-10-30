from tests.conftest import auth


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_register_login_me(client, new_org):
    headers, me = new_org()
    assert me["user"]["role"] == "admin"
    assert "asset.write" in me["permissions"]
    r = client.get("/api/auth/me", headers=headers)
    assert r.status_code == 200
    assert r.json()["organization"]["id"] == me["organization"]["id"]


def test_duplicate_email_rejected(client):
    body = {"organization_name": "Dup Co", "name": "A", "email": "dup@acme.example.com", "password": "password123"}
    assert client.post("/api/auth/register", json=body).status_code == 201
    assert client.post("/api/auth/register", json=body | {"email": "DUP@acme.example.com"}).status_code == 409


def test_bad_password(client):
    r = client.post("/api/auth/login", json={"email": "admin@demo.example.com", "password": "wrong-password"})
    assert r.status_code == 401


def test_requires_token(client):
    assert client.get("/api/factories").status_code == 401
    assert client.get("/api/factories", headers=auth("garbage")).status_code == 401

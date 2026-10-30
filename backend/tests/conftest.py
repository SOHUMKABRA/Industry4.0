import os
import tempfile
import uuid

_tmp = tempfile.mkdtemp(prefix="twin-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["SEED_DEMO"] = "true"
os.environ["TWIN_ENV"] = "development"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

DEMO_PW = "demo1234"


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def login(client, email: str, password: str = DEMO_PW) -> dict:
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return auth(r.json()["access_token"])


@pytest.fixture(scope="session")
def demo_admin(client):
    return login(client, "admin@demo.example.com")


@pytest.fixture
def new_org(client):
    """Register a fresh organization; returns (headers, me)."""

    def make(lib: bool = True):
        email = f"u{uuid.uuid4().hex[:8]}@acme.example.com"
        r = client.post(
            "/api/auth/register",
            json={"organization_name": "Acme " + email[:9], "name": "Owner", "email": email,
                  "password": "password123", "install_standard_library": lib},
        )
        assert r.status_code == 201, r.text
        return auth(r.json()["access_token"]), r.json()["me"]

    return make


@pytest.fixture
def factory(client):
    def make(headers, name="Plant"):
        r = client.post("/api/factories", json={"name": name}, headers=headers)
        assert r.status_code == 201, r.text
        return r.json()

    return make


def type_by_key(client, headers, key):
    return next(t for t in client.get("/api/asset-types", headers=headers).json() if t["key"] == key)

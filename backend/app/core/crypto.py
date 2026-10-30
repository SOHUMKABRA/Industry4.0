"""Encryption at rest for device credentials.

Credentials are write-only through the API: they are encrypted here on the way
in, decrypted only inside adapters, and never serialized into responses.
"""

import base64
import hashlib
import json
from functools import lru_cache

from cryptography.fernet import Fernet

from app.core.config import get_settings


@lru_cache
def _fernet() -> Fernet:
    s = get_settings()
    if s.credential_key:
        return Fernet(s.credential_key.encode())
    # Development fallback: derive a key from SECRET_KEY. Production startup
    # refuses to run without an explicit CREDENTIAL_KEY (see Settings).
    digest = hashlib.sha256(("cred:" + s.secret_key).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_json(data: dict) -> str:
    return _fernet().encrypt(json.dumps(data).encode()).decode()


def decrypt_json(token: str | None) -> dict:
    if not token:
        return {}
    return json.loads(_fernet().decrypt(token.encode()))

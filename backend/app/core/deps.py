from collections.abc import Callable
from typing import Annotated, TypeVar

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.permissions import Perm, has_perm
from app.core.security import decode_access_token
from app.models import User

bearer = HTTPBearer(auto_error=False)

DB = Annotated[Session, Depends(get_db)]


def current_user(
    db: DB, creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
) -> User:
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED, "Not authenticated", {"WWW-Authenticate": "Bearer"}
    )
    if creds is None:
        raise unauthorized
    try:
        payload = decode_access_token(creds.credentials)
    except jwt.PyJWTError:
        raise unauthorized from None
    user = db.get(User, payload.get("sub"))
    if user is None or not user.is_active or user.org_id != payload.get("org"):
        raise unauthorized
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require(perm: Perm) -> Callable[[User], User]:
    def dep(user: CurrentUser) -> User:
        if not has_perm(user.role, perm):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing permission: {perm}")
        return user

    return dep


T = TypeVar("T")


def get_owned(db: Session, model: type[T], obj_id: str | None, user: User, what: str = "") -> T:
    """Fetch a tenant-owned row by id. Another org's id is reported as 404,
    never 403, so ids do not leak across tenants."""
    obj = db.get(model, obj_id) if obj_id else None
    if obj is None or getattr(obj, "org_id", None) != user.org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{what or model.__name__} not found")
    return obj

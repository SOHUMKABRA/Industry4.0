import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select

from app.core.deps import DB, CurrentUser, get_owned, require
from app.core.permissions import Perm, Role
from app.core.security import hash_password, verify_password
from app.models import User
from app.schemas.common import ORMModel
from app.services import audit

router = APIRouter(tags=["users"])
Admin = Annotated[User, Depends(require(Perm.USER_MANAGE))]
RoleStr = str


class UserAdminOut(ORMModel):
    id: str
    email: str
    name: str
    role: str
    is_active: bool
    must_change_password: bool


class UserCreate(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=200)
    role: Role
    password: str | None = Field(default=None, min_length=8, max_length=200)


class UserPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    role: Role | None = None
    is_active: bool | None = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=200)


def _other_active_admins(db, user: User, exclude_id: str) -> int:
    return db.scalar(select(func.count()).select_from(User).where(
        User.org_id == user.org_id, User.role == Role.ADMIN, User.is_active.is_(True), User.id != exclude_id)) or 0


@router.get("/users", response_model=list[UserAdminOut])
def list_users(user: Admin, db: DB):
    return db.scalars(select(User).where(User.org_id == user.org_id).order_by(User.name)).all()


@router.post("/users", status_code=201)
def create_user(body: UserCreate, user: Admin, db: DB):
    email = body.email.lower()
    if db.scalar(select(User).where(func.lower(User.email) == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    temp = body.password or secrets.token_urlsafe(9)
    u = User(org_id=user.org_id, email=email, name=body.name, role=body.role, password_hash=hash_password(temp),
             must_change_password=body.password is None)
    db.add(u)
    db.flush()
    audit.record(db, user, "user.create", "user", u.id, f"Created user {email} ({body.role})")
    db.commit()
    return {"user": UserAdminOut.model_validate(u), "temporary_password": None if body.password else temp}


@router.patch("/users/{user_id}", response_model=UserAdminOut)
def update_user(user_id: str, body: UserPatch, user: Admin, db: DB):
    u = get_owned(db, User, user_id, user, "User")
    changes = body.model_dump(exclude_unset=True)
    demoting = ("role" in changes and changes["role"] != Role.ADMIN) or changes.get("is_active") is False
    if u.role == Role.ADMIN and demoting and _other_active_admins(db, user, u.id) == 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "The organization must keep at least one active admin")
    if u.id == user.id and changes.get("is_active") is False:
        raise HTTPException(status.HTTP_409_CONFLICT, "You can't deactivate your own account")
    before = {k: getattr(u, k) for k in changes}
    for k, v in changes.items():
        setattr(u, k, v)
    audit.record(db, user, "user.update", "user", u.id, f"Updated user {u.email}", audit.diff(before, changes))
    db.commit()
    return u


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: str, user: Admin, db: DB):
    u = get_owned(db, User, user_id, user, "User")
    temp = secrets.token_urlsafe(9)
    u.password_hash = hash_password(temp)
    u.must_change_password = True
    audit.record(db, user, "user.reset_password", "user", u.id, f"Reset password for {u.email}")
    db.commit()
    return {"temporary_password": temp}


@router.post("/auth/change-password", status_code=204)
def change_password(body: PasswordChange, user: CurrentUser, db: DB):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    if body.current_password == body.new_password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose a different password")
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    audit.record(db, user, "user.change_password", "user", user.id, "Changed own password")
    db.commit()

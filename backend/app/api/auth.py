import re
import secrets

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.core.deps import DB, CurrentUser
from app.core.permissions import ROLE_PERMISSIONS, Role
from app.core.security import create_access_token, hash_password, verify_password
from app.models import Organization, User
from app.schemas.auth import LoginIn, MeOut, OrgOut, RegisterIn, TokenOut, UserOut
from app.seed.library import install_standard_library
from app.services import audit

router = APIRouter(prefix="/auth", tags=["auth"])


def me_for(db, user: User) -> MeOut:
    org = db.get(Organization, user.org_id)
    return MeOut(
        user=UserOut.model_validate(user),
        organization=OrgOut.model_validate(org),
        permissions=sorted(ROLE_PERMISSIONS[Role(user.role)]),
    )


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "org"


@router.post("/register", response_model=TokenOut, status_code=201)
def register(body: RegisterIn, db: DB):
    """Create a new organization with the caller as its first admin."""
    email = body.email.lower()
    if db.scalar(select(User).where(func.lower(User.email) == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    slug = _slugify(body.organization_name)
    if db.scalar(select(Organization).where(Organization.slug == slug)):
        slug = f"{slug}-{secrets.token_hex(3)}"
    org = Organization(name=body.organization_name, slug=slug)
    db.add(org)
    db.flush()
    user = User(
        org_id=org.id, email=email, name=body.name,
        password_hash=hash_password(body.password), role=Role.ADMIN,
    )
    db.add(user)
    if body.install_standard_library:
        install_standard_library(db, org.id)
    db.flush()
    audit.record(db, user, "org.create", "organization", org.id, f"Created organization {org.name}")
    db.commit()
    return TokenOut(access_token=create_access_token(user.id, org.id), me=me_for(db, user))


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: DB):
    user = db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    return TokenOut(access_token=create_access_token(user.id, user.org_id), me=me_for(db, user))


@router.get("/me", response_model=MeOut)
def me(user: CurrentUser, db: DB):
    return me_for(db, user)

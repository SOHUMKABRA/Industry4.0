from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import ORMModel


class RegisterIn(BaseModel):
    organization_name: str = Field(min_length=2, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    install_standard_library: bool = True


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(ORMModel):
    id: str
    org_id: str
    email: str
    name: str
    role: str


class OrgOut(ORMModel):
    id: str
    name: str
    slug: str


class MeOut(BaseModel):
    user: UserOut
    organization: OrgOut
    permissions: list[str]


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    me: MeOut

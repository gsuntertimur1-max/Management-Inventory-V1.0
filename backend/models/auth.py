import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field

Role = Literal["admin", "operator", "viewer"]


def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class LoginRequest(BaseModel):
    username: str
    password: str


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=40)
    full_name: str = ""
    role: Role = "viewer"
    password: str = Field(min_length=6)


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[Role] = None
    password: Optional[str] = Field(default=None, min_length=6)


class UserPublic(BaseModel):
    id: str
    username: str
    full_name: str = ""
    role: Role
    created_at: datetime


class User(UserPublic):
    id: str = Field(default_factory=_uid)
    password_hash: str
    salt: str
    created_at: datetime = Field(default_factory=_now)

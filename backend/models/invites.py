"""Undangan tim: admin mengundang staf gudang agar bisa masuk dengan akun Google."""
import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, EmailStr, Field

from models.auth import Role

InviteStatus = str  # "MENUNGGU" | "DITERIMA" | "KEDALUWARSA"


def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class InviteCreate(BaseModel):
    email: EmailStr
    full_name: str = ""
    role: Role = "viewer"
    message: str = ""


class Invite(BaseModel):
    id: str = Field(default_factory=_uid)
    email: str
    full_name: str = ""
    role: Role = "viewer"
    message: str = ""
    status: InviteStatus = "MENUNGGU"
    invite_link: str = ""
    email_sent: bool = False
    email_error: str = ""
    invited_by: str = ""
    accepted_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=_now)


class InviteSendResult(BaseModel):
    invite: Invite
    email_sent: bool
    detail: str

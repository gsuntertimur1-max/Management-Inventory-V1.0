"""Undangan tim via email (Resend) — staf yang diundang langsung masuk pakai akun Google."""
import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request

from lib.auth import ROLE_LABELS, principal
from lib.db import db
from models.invites import Invite, InviteCreate, InviteSendResult

logger = logging.getLogger(__name__)
router = APIRouter()

SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "onboarding@resend.dev")
COMPANY = "Bulog Gudang Sunter Timur I & II"


def _clean(doc: Dict[str, Any]) -> Dict[str, Any]:
    doc.pop("_id", None)
    return doc


def _app_url(request: Request) -> str:
    """URL publik yang benar-benar dipakai pengunjung (APP_URL di .env bisa basi)."""
    forwarded_host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip() or request.url.scheme
    if forwarded_host:
        return f"{proto}://{forwarded_host.split(',')[0].strip()}"
    return os.environ.get("APP_URL", "").rstrip("/")


def _email_html(invite: Invite, link: str) -> str:
    note = (
        f'<p style="margin:0 0 16px;color:#334155;font-size:14px;line-height:22px;">'
        f'"{invite.message}"</p>'
        if invite.message
        else ""
    )
    return f"""<!doctype html>
<html><body style="margin:0;padding:24px;background:#f1f5f9;font-family:Arial,Helvetica,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;margin:0 auto;background:#ffffff;border-radius:12px;border:1px solid #e2e8f0;">
    <tr><td style="padding:24px 24px 8px;">
      <p style="margin:0;font-size:12px;letter-spacing:2px;text-transform:uppercase;color:#64748b;">Undangan Tim Gudang</p>
      <h1 style="margin:6px 0 0;font-size:20px;color:#0f172a;">{COMPANY}</h1>
    </td></tr>
    <tr><td style="padding:8px 24px 0;">
      <p style="margin:0 0 16px;color:#334155;font-size:14px;line-height:22px;">
        Halo{(' ' + invite.full_name) if invite.full_name else ''}, Anda diundang untuk mengakses
        sistem penyimpanan stok {COMPANY} sebagai
        <strong>{ROLE_LABELS.get(invite.role, invite.role)}</strong>.
      </p>
      {note}
      <p style="margin:0 0 20px;color:#334155;font-size:14px;line-height:22px;">
        Tidak perlu password. Klik tombol di bawah, lalu pilih
        <strong>"Masuk dengan Google"</strong> menggunakan email <strong>{invite.email}</strong>.
      </p>
      <table role="presentation" cellpadding="0" cellspacing="0"><tr>
        <td style="background:#2563eb;border-radius:8px;">
          <a href="{link}" style="display:inline-block;padding:12px 22px;color:#ffffff;font-size:14px;font-weight:bold;text-decoration:none;">Masuk ke Aplikasi Gudang</a>
        </td>
      </tr></table>
      <p style="margin:20px 0 0;color:#64748b;font-size:12px;line-height:20px;">
        Jika tombol tidak berfungsi, buka tautan ini: <br />
        <a href="{link}" style="color:#2563eb;">{link}</a>
      </p>
    </td></tr>
    <tr><td style="padding:20px 24px 24px;">
      <p style="margin:0;color:#94a3b8;font-size:11px;">
        Undangan dikirim oleh {invite.invited_by or 'administrator gudang'}. Abaikan email ini bila Anda tidak mengenalinya.
      </p>
    </td></tr>
  </table>
</body></html>"""


async def _send_invite_email(invite: Invite, link: str) -> Tuple[bool, str]:
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    if not api_key:
        return False, (
            "RESEND_API_KEY belum diisi di backend/.env, jadi email tidak dikirim. "
            "Bagikan tautan undangan di bawah secara manual (WhatsApp/chat)."
        )
    try:
        import resend

        resend.api_key = api_key
        params = {
            "from": SENDER_EMAIL,
            "to": [invite.email],
            "subject": f"Undangan akses sistem stok {COMPANY}",
            "html": _email_html(invite, link),
        }
        # SDK Resend sinkron → jalankan di thread agar event loop FastAPI tidak terblokir.
        result = await asyncio.to_thread(resend.Emails.send, params)
        return True, f"Undangan terkirim ke {invite.email} (id: {result.get('id', '-')})"
    except Exception as exc:  # noqa: BLE001 - kegagalan email tidak boleh membatalkan undangan
        logger.error("Gagal mengirim undangan ke %s: %s", invite.email, exc)
        return False, f"Email gagal dikirim: {exc}. Bagikan tautan undangan secara manual."


@router.get("/invites", response_model=List[Invite])
async def list_invites() -> List[Invite]:
    docs = await db.invites.find().sort("created_at", -1).to_list(500)
    return [Invite(**_clean(d)) for d in docs]


@router.post("/invites", response_model=InviteSendResult)
async def create_invite(payload: InviteCreate, request: Request, user=Depends(principal)) -> InviteSendResult:
    email = str(payload.email).strip().lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email ini sudah punya akun di aplikasi")
    if await db.invites.find_one({"email": email, "status": "MENUNGGU"}):
        raise HTTPException(status_code=400, detail="Undangan untuk email ini masih menunggu")

    link = f"{_app_url(request)}/login"
    invite = Invite(
        email=email,
        full_name=payload.full_name.strip(),
        role=payload.role,
        message=payload.message.strip(),
        invite_link=link,
        invited_by=getattr(user, "full_name", "") or getattr(user, "username", ""),
    )
    sent, detail = await _send_invite_email(invite, link)
    invite.email_sent = sent
    invite.email_error = "" if sent else detail
    await db.invites.insert_one(invite.model_dump())
    return InviteSendResult(invite=invite, email_sent=sent, detail=detail)


@router.post("/invites/{invite_id}/resend", response_model=InviteSendResult)
async def resend_invite(invite_id: str, request: Request) -> InviteSendResult:
    doc = await db.invites.find_one({"id": invite_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Undangan tidak ditemukan")
    invite = Invite(**_clean(doc))
    if invite.status == "DITERIMA":
        raise HTTPException(status_code=400, detail="Undangan ini sudah diterima")

    link = f"{_app_url(request)}/login"
    sent, detail = await _send_invite_email(invite, link)
    await db.invites.update_one(
        {"id": invite_id},
        {"$set": {"email_sent": sent, "email_error": "" if sent else detail, "invite_link": link}},
    )
    invite.email_sent, invite.email_error, invite.invite_link = sent, "" if sent else detail, link
    return InviteSendResult(invite=invite, email_sent=sent, detail=detail)


@router.delete("/invites/{invite_id}")
async def delete_invite(invite_id: str) -> Dict[str, Any]:
    res = await db.invites.delete_one({"id": invite_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Undangan tidak ditemukan")
    return {"ok": True, "id": invite_id}


async def claim_invite(email: str) -> str:
    """Dipakai saat login Google: kembalikan peran undangan bila ada, lalu tandai diterima."""
    doc = await db.invites.find_one({"email": email.strip().lower(), "status": "MENUNGGU"})
    if not doc:
        return ""
    await db.invites.update_one(
        {"id": doc["id"]},
        {"$set": {"status": "DITERIMA", "accepted_at": datetime.now(timezone.utc)}},
    )
    return str(doc.get("role", "viewer"))

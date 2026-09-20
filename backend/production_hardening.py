from __future__ import annotations

import hashlib
import hmac
import io
import json
import logging
import zipfile
from datetime import datetime, timedelta, timezone

from bson import json_util
from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.server import JWT_SECRET, ROLE_SUPERADMIN, canonical_role, client, db, get_current_user, operational_now
from backend.role_four_config import has_role_permission

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)

BACKUP_SCHEMA_VERSION = 1
MAX_BACKUP_BYTES = 25 * 1024 * 1024
MAX_RESTORE_DOCS = 100_000

BACKUP_COLLECTIONS = [
    "users",
    "settings",
    "products",
    "suppliers",
    "transactions",
    "surat_jalan",
    "purchase_orders",
    "outbound_loads",
    "outbound_documents",
    "stack_allocations",
    "stack_history",
    "stack_treatments",
    "stack_lots",
    "stack_lot_movements",
    "stock_opnames",
    "supplier_returns",
    "loading_cost_settlements",
    "unloading_cost_settlements",
    "operational_postcommit_issues",
    "consignment_layouts",
    "consignment_layout_history",
    "consignment_movements",
    "consignment_operation_history",
    "consignment_opnames",
    "consignment_damaged_balances",
    "consignment_damaged_movements",
    "consignment_damaged_opnames",
    "bazar_trips",
    "bazar_package_templates",
    "bazar_package_batches",
    "bazar_package_loads",
    "bazar_external_nd",
    "bazar_external_nd_lots",
    "ecom_orders",
    "marketplace_accounts",
    "marketplace_sku_mappings",
    "marketplace_sync_logs",
    "marketplace_webhook_events",
    "counters",
]


class MaintenanceBody(BaseModel):
    enabled: bool
    note: str = ""


async def require_superadmin(user: dict = Depends(get_current_user)) -> dict:
    if canonical_role(user.get("role")) != ROLE_SUPERADMIN:
        raise HTTPException(status_code=403, detail="Hanya Superadmin yang dapat mengelola backup/recovery")
    return user


def _manifest_payload(manifest: dict) -> bytes:
    unsigned = {key: value for key, value in manifest.items() if key != "signature"}
    return json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sign_manifest(manifest: dict) -> str:
    return hmac.new(JWT_SECRET.encode("utf-8"), _manifest_payload(manifest), hashlib.sha256).hexdigest()


async def _build_backup_zip() -> tuple[io.BytesIO, dict]:
    output = io.BytesIO()
    manifest = {
        "schemaVersion": BACKUP_SCHEMA_VERSION,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "operationalTime": operational_now().isoformat(),
        "database": db.name,
        "collections": {},
        "containsSensitiveData": True,
    }

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in BACKUP_COLLECTIONS:
            buffer = io.StringIO()
            count = 0
            cursor = db[name].find({})
            async for document in cursor:
                buffer.write(json_util.dumps(document, json_options=json_util.CANONICAL_JSON_OPTIONS))
                buffer.write("\n")
                count += 1
                if count > MAX_RESTORE_DOCS:
                    raise HTTPException(status_code=413, detail=f"Collection {name} terlalu besar untuk backup logis aplikasi")
            raw = buffer.getvalue().encode("utf-8")
            path = f"collections/{name}.jsonl"
            archive.writestr(path, raw)
            manifest["collections"][name] = {
                "count": count,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
            }

        manifest["signature"] = _sign_manifest(manifest)
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))

    output.seek(0)
    return output, manifest


def _parse_backup(content: bytes) -> tuple[dict, dict[str, list[dict]]]:
    if len(content) > MAX_BACKUP_BYTES:
        raise HTTPException(status_code=413, detail="File backup terlalu besar")
    try:
        archive = zipfile.ZipFile(io.BytesIO(content), "r")
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail="File backup ZIP tidak valid") from exc

    try:
        manifest = json.loads(archive.read("manifest.json"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="manifest.json backup tidak ditemukan atau rusak") from exc

    if int(manifest.get("schemaVersion", 0) or 0) != BACKUP_SCHEMA_VERSION:
        raise HTTPException(status_code=400, detail="Versi backup tidak kompatibel")
    signature = str(manifest.get("signature") or "")
    if not hmac.compare_digest(signature, _sign_manifest(manifest)):
        raise HTTPException(status_code=400, detail="Signature backup tidak valid; file mungkin telah diubah")

    collections: dict[str, list[dict]] = {}
    total_docs = 0
    for name, meta in (manifest.get("collections") or {}).items():
        if name not in BACKUP_COLLECTIONS:
            raise HTTPException(status_code=400, detail=f"Collection backup tidak diizinkan: {name}")
        path = f"collections/{name}.jsonl"
        try:
            raw = archive.read(path)
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=f"Data collection {name} tidak ditemukan") from exc
        if hashlib.sha256(raw).hexdigest() != str(meta.get("sha256") or ""):
            raise HTTPException(status_code=400, detail=f"Checksum collection {name} tidak sesuai")
        rows = []
        for line in raw.splitlines():
            if line.strip():
                rows.append(json_util.loads(line))
        if len(rows) != int(meta.get("count", -1)):
            raise HTTPException(status_code=400, detail=f"Jumlah dokumen collection {name} tidak sesuai manifest")
        collections[name] = rows
        total_docs += len(rows)
        if total_docs > MAX_RESTORE_DOCS:
            raise HTTPException(status_code=413, detail="Total dokumen backup terlalu besar untuk restore aplikasi")
    return manifest, collections


@router.get("/admin/maintenance")
async def maintenance_status(user: dict = Depends(require_superadmin)):
    doc = await db.settings.find_one({"_id": "app"}, {"_id": 0, "maintenanceMode": 1, "maintenanceNote": 1, "maintenanceUpdatedAt": 1, "maintenanceUpdatedBy": 1}) or {}
    return {
        "enabled": bool(doc.get("maintenanceMode", False)),
        "note": doc.get("maintenanceNote", ""),
        "updatedAt": doc.get("maintenanceUpdatedAt", ""),
        "updatedBy": doc.get("maintenanceUpdatedBy", ""),
    }


@router.post("/admin/maintenance")
async def set_maintenance(body: MaintenanceBody, user: dict = Depends(require_superadmin)):
    await db.settings.update_one(
        {"_id": "app"},
        {"$set": {
            "maintenanceMode": bool(body.enabled),
            "maintenanceNote": body.note.strip(),
            "maintenanceUpdatedAt": datetime.now(timezone.utc).isoformat(),
            "maintenanceUpdatedBy": user.get("name", ""),
        }},
        upsert=True,
    )
    return {"enabled": bool(body.enabled), "note": body.note.strip()}


@router.get("/admin/backups/export")
async def export_backup(user: dict = Depends(require_superadmin)):
    output, manifest = await _build_backup_zip()
    stamp = operational_now().strftime("%Y%m%d_%H%M%S")
    filename = f"pepeg_backup_{stamp}.zip"
    logger.warning("Backup logis PEPEG dibuat oleh %s: %s dokumen", user.get("name", ""), sum(v["count"] for v in manifest["collections"].values()))
    return StreamingResponse(
        output,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/admin/backups/validate")
async def validate_backup(file: UploadFile = File(...), user: dict = Depends(require_superadmin)):
    content = await file.read(MAX_BACKUP_BYTES + 1)
    manifest, collections = _parse_backup(content)
    return {
        "valid": True,
        "schemaVersion": manifest["schemaVersion"],
        "createdAt": manifest.get("createdAt", ""),
        "database": manifest.get("database", ""),
        "collections": {name: len(rows) for name, rows in collections.items()},
        "totalDocuments": sum(len(rows) for rows in collections.values()),
        "containsSensitiveData": bool(manifest.get("containsSensitiveData", False)),
    }


@router.post("/admin/backups/restore")
async def restore_backup(
    file: UploadFile = File(...),
    confirmation: str = Header(default="", alias="X-PEPEG-RESTORE-CONFIRM"),
    user: dict = Depends(require_superadmin),
):
    if confirmation != "RESTORE_PEPEG":
        raise HTTPException(status_code=400, detail="Header konfirmasi restore tidak valid")
    settings = await db.settings.find_one({"_id": "app"}, {"_id": 0, "maintenanceMode": 1}) or {}
    if not settings.get("maintenanceMode"):
        raise HTTPException(status_code=409, detail="Aktifkan Maintenance Mode sebelum restore")
    active_loads = await db.outbound_loads.count_documents({"status": {"$in": ["Menunggu", "Sedang Dimuat"]}})
    if active_loads:
        raise HTTPException(status_code=409, detail=f"Restore ditolak: masih ada {active_loads} pemuatan aktif")

    content = await file.read(MAX_BACKUP_BYTES + 1)
    manifest, collections = _parse_backup(content)

    try:
        async with await client.start_session() as session:
            async with session.start_transaction():
                for name in BACKUP_COLLECTIONS:
                    rows = collections.get(name, [])
                    await db[name].delete_many({}, session=session)
                    if rows:
                        await db[name].insert_many(rows, ordered=True, session=session)
    except Exception as exc:
        logger.exception("Restore backup gagal dan transaksi dibatalkan")
        raise HTTPException(status_code=500, detail="Restore gagal; perubahan database dibatalkan") from exc

    # Semua sesi lama dicabut setelah restore agar token dari keadaan sebelum
    # pemulihan tidak dapat menulis ke database yang baru dipulihkan.
    await db.users.update_many({}, {"$inc": {"auth_version": 1}})
    await db.user_sessions.delete_many({})
    await db.login_attempts.delete_many({})
    await db.operation_requests.delete_many({})
    await db.operation_locks.delete_many({})

    # Maintenance selalu tetap aktif setelah restore agar operator tidak langsung menulis
    # sebelum Superadmin memeriksa integritas hasil pemulihan.
    await db.settings.update_one(
        {"_id": "app"},
        {"$set": {
            "maintenanceMode": True,
            "maintenanceNote": "Restore selesai; periksa Kontrol Integritas sebelum membuka sistem.",
            "maintenanceUpdatedAt": datetime.now(timezone.utc).isoformat(),
            "maintenanceUpdatedBy": user.get("name", ""),
        }},
        upsert=True,
    )
    return {
        "restored": True,
        "createdAt": manifest.get("createdAt", ""),
        "totalDocuments": sum(len(rows) for rows in collections.values()),
        "maintenanceMode": True,
    }


@router.get("/admin/recovery-status")
async def recovery_status(user: dict = Depends(require_superadmin)):
    now = datetime.now(timezone.utc)
    stale_processing = await db.operation_requests.count_documents({
        "status": "PROCESSING",
        "createdAt": {"$lt": now.replace(microsecond=0) - timedelta(minutes=10)},
    })
    open_postcommit = await db.operational_postcommit_issues.count_documents({"status": "OPEN"})
    active_locks = await db.operation_locks.count_documents({"expiresAt": {"$gt": now}})
    active_loads = await db.outbound_loads.count_documents({"status": {"$in": ["Menunggu", "Sedang Dimuat"]}})
    maintenance = await db.settings.find_one({"_id": "app"}, {"_id": 0, "maintenanceMode": 1}) or {}
    return {
        "maintenanceMode": bool(maintenance.get("maintenanceMode", False)),
        "activeLoads": active_loads,
        "activeLocks": active_locks,
        "staleProcessingRequests": stale_processing,
        "openPostCommitIssues": open_postcommit,
        "healthy": stale_processing == 0 and open_postcommit == 0,
    }

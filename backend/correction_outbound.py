from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.server import db, new_id, now_iso, require_admin
from backend.operational_guards import operation_guard

router = APIRouter(prefix="/api")


class OutboundMetadataCorrectionInput(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
    party: Optional[str] = Field(default=None, max_length=200)
    polisi: Optional[str] = Field(default=None, max_length=50)
    pengambil: Optional[str] = Field(default=None, max_length=200)
    keterangan: Optional[str] = Field(default=None, max_length=1000)


@router.get("/operational-corrections/outbound")
async def list_completed_outbound_for_correction(user: dict = Depends(require_admin)):
    loads = await db.outbound_loads.find({"status": "Selesai"}, {"_id": 0}).sort("completed_at", -1).to_list(500)
    return [{
        "id": load.get("id", ""), "bonNo": load.get("bon_no", ""), "antrian": load.get("antrian", ""),
        "documents": load.get("documents") or [load.get("ref", "")], "party": load.get("party", ""),
        "polisi": load.get("polisi", ""), "pengambil": load.get("pengambil", ""), "keterangan": load.get("keterangan", ""),
        "suratJalanNo": load.get("surat_jalan_no", ""), "completedAt": load.get("completed_at", ""),
        "correctionHistory": load.get("correction_history", []),
        "items": [{"name": item.get("name", ""), "sku": item.get("sku", ""), "qty": item.get("qty", 0), "unit": item.get("unit", ""), "stackCode": item.get("stackCode", ""), "documentNo": item.get("documentNo", "")} for item in load.get("items", [])],
    } for load in loads]


@router.put("/operational-corrections/outbound/{load_id}")
async def correct_completed_outbound_metadata(load_id: str, body: OutboundMetadataCorrectionInput, user: dict = Depends(require_admin)):
    async with operation_guard([f"outbound-correction:{load_id}"]):
        load = await db.outbound_loads.find_one({"id": load_id}, {"_id": 0})
        if not load:
            raise HTTPException(status_code=404, detail="Data pengeluaran tidak ditemukan")
        if load.get("status") != "Selesai":
            raise HTTPException(status_code=400, detail="Koreksi dokumen selesai hanya tersedia setelah pemuatan selesai")

        changes = {}
        if body.party is not None:
            party = body.party.strip()
            if not party:
                raise HTTPException(status_code=400, detail="Penerima barang tidak boleh dikosongkan")
            changes["party"] = party
            changes["penerima"] = party
        if body.polisi is not None: changes["polisi"] = body.polisi.strip()
        if body.pengambil is not None: changes["pengambil"] = body.pengambil.strip()
        if body.keterangan is not None: changes["keterangan"] = body.keterangan.strip()
        if not changes:
            raise HTTPException(status_code=400, detail="Tidak ada metadata dokumen yang berubah")

        before = {"party": load.get("party", ""), "penerima": load.get("penerima", ""), "polisi": load.get("polisi", ""), "pengambil": load.get("pengambil", ""), "keterangan": load.get("keterangan", "")}
        after = {**before, **changes}
        if all(str(after.get(key, "")) == str(before.get(key, "")) for key in before):
            raise HTTPException(status_code=400, detail="Tidak ada perubahan dibanding data saat ini")

        time = now_iso()
        event = {"id": new_id(), "time": time, "by": user.get("name", ""), "reason": body.reason.strip(), "before": before, "after": after}
        sj = None
        if load.get("surat_jalan_id"):
            sj = await db.surat_jalan.find_one({"id": load["surat_jalan_id"]}, {"_id": 0})
        if not sj:
            sj = await db.surat_jalan.find_one({"load_id": load_id}, {"_id": 0})
        txns = await db.transactions.find({"load_id": load_id, "type": "KELUAR"}, {"_id": 0, "id": 1, "penerima": 1, "polisi": 1, "pengambil": 1, "keterangan": 1}).to_list(5000)

        audit_id = new_id()
        load_updated = sj_updated = tx_updated = False
        try:
            result = await db.outbound_loads.update_one({"id": load_id, "status": "Selesai"}, {"$set": {**changes, "last_correction_at": time, "last_correction_by": user.get("name", "")}, "$push": {"correction_history": event}})
            if result.matched_count == 0:
                raise HTTPException(status_code=409, detail="Data pengeluaran berubah saat koreksi. Muat ulang lalu coba kembali.")
            load_updated = True

            if sj:
                sj_changes = {}
                if "party" in changes or "penerima" in changes: sj_changes["penerima"] = after["party"]
                for key in ("polisi", "pengambil", "keterangan"):
                    if key in changes: sj_changes[key] = changes[key]
                if sj_changes:
                    await db.surat_jalan.update_one({"id": sj["id"]}, {"$set": sj_changes})
                    sj_updated = True

            txn_changes = {}
            if "party" in changes or "penerima" in changes: txn_changes["penerima"] = after["party"]
            for key in ("polisi", "pengambil", "keterangan"):
                if key in changes: txn_changes[key] = changes[key]
            if txn_changes:
                await db.transactions.update_many({"load_id": load_id, "type": "KELUAR"}, {"$set": txn_changes})
                tx_updated = True

            await db.transactions.insert_one({"id": audit_id, "operation_id": audit_id, "load_id": load_id, "time": time, "ref": load.get("ref", ""), "bon_no": load.get("bon_no", ""), "antrian": load.get("antrian", ""), "type": "KOREKSI", "kondisi": "DOKUMEN", "document_type": "KOREKSI_DOKUMEN_KELUAR", "product": "Metadata pengeluaran", "sku": "", "change": 0, "unit": "", "penerima": after.get("party", ""), "polisi": after.get("polisi", ""), "pengambil": after.get("pengambil", ""), "operator": user.get("name", ""), "keterangan": body.reason.strip(), "correction_reason": body.reason.strip(), "correction_event_id": event["id"]})
        except Exception:
            await db.transactions.delete_one({"id": audit_id})
            if tx_updated:
                for txn in txns:
                    await db.transactions.update_one({"id": txn["id"]}, {"$set": {"penerima": txn.get("penerima", ""), "polisi": txn.get("polisi", ""), "pengambil": txn.get("pengambil", ""), "keterangan": txn.get("keterangan", "")}})
            if sj_updated and sj:
                await db.surat_jalan.update_one({"id": sj["id"]}, {"$set": {"penerima": sj.get("penerima", ""), "polisi": sj.get("polisi", ""), "pengambil": sj.get("pengambil", ""), "keterangan": sj.get("keterangan", "")}})
            if load_updated:
                await db.outbound_loads.update_one({"id": load_id}, {"$set": {**before, "correction_history": list(load.get("correction_history") or [])}, "$unset": {"last_correction_at": "", "last_correction_by": ""}})
            raise

        return await db.outbound_loads.find_one({"id": load_id}, {"_id": 0})

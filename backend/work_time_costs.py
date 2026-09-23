from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException


def normalize_unloading_group(value: str) -> str:
    text = str(value or "").strip().upper()
    if not text or "RTR" in text:
        return ""
    if "MANDOR 2" in text or "GRUP 2" in text or "MP1" in text or "21-24" in text:
        return "MANDOR 2 - MP1/GBB 21-24"
    if "MANDOR 1" in text or "GRUP 1" in text or "17-20" in text:
        return "MANDOR 1 - GBB 17-20"
    return ""


def holiday_from_settings(when: datetime, holidays: list[dict] | None = None) -> bool:
    if when.weekday() >= 5:
        return True
    target = when.strftime("%Y-%m-%d")
    return any(bool(row.get("active", True)) and str(row.get("date") or "").strip() == target for row in (holidays or []))


def local_datetime(value, tzinfo):
    if isinstance(value, datetime):
        return value.astimezone(tzinfo) if value.tzinfo else value.replace(tzinfo=tzinfo)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Waktu kerja tidak valid") from exc
    return parsed.astimezone(tzinfo) if parsed.tzinfo else parsed.replace(tzinfo=tzinfo)


def work_split(started_at: datetime, completed_at: datetime, qty: float, normal_before_cutoff: float | None = None) -> dict:
    qty = float(qty or 0)
    if qty < 0:
        raise HTTPException(status_code=400, detail="Kuantitas pekerjaan tidak valid")
    cutoff = started_at.replace(hour=16, minute=0, second=0, microsecond=0)

    if started_at >= cutoff:
        overtime_qty = qty
    elif completed_at <= cutoff:
        overtime_qty = 0.0
    else:
        if normal_before_cutoff is None:
            raise HTTPException(
                status_code=400,
                detail="Pekerjaan melewati pukul 16.00. Isi kuantitas yang sudah selesai sampai pukul 16.00.",
            )
        normal_qty = float(normal_before_cutoff)
        if normal_qty < -1e-9 or normal_qty > qty + 1e-9:
            raise HTTPException(
                status_code=400,
                detail=f"Kuantitas selesai sampai 16.00 harus antara 0 dan {qty:g}",
            )
        overtime_qty = max(qty - normal_qty, 0.0)

    regular_qty = max(qty - overtime_qty, 0.0)
    if overtime_qty <= 1e-9:
        status = "NORMAL"
    elif regular_qty <= 1e-9:
        status = "LEMBUR_PENUH"
    else:
        status = "LEMBUR_PARSIAL"
    return {"regularQty": regular_qty, "overtimeQty": overtime_qty, "workStatus": status}


def handling_fee(
    product: dict,
    qty: float,
    overtime_qty: float,
    when: datetime,
    prefix: str,
    payer_mode: str,
    charge_mode_override: str = "",
    holiday_override: bool | None = None,
) -> dict:
    qty = float(qty or 0)
    overtime_qty = min(max(float(overtime_qty or 0), 0.0), qty)
    regular_qty = max(qty - overtime_qty, 0.0)
    holiday = bool(holiday_override) if holiday_override is not None else when.weekday() >= 5

    components = {"labor": 0.0, "daily": 0.0, "warehouse": 0.0}
    breakdown = {}
    keys = {"labor": "Labor", "daily": "Daily", "warehouse": "Warehouse"}
    for target, suffix in keys.items():
        base = float(product.get(f"{prefix}Fee{suffix}", 0) or 0) * qty
        overtime = float(product.get(f"{prefix}Overtime{suffix}", 0) or 0) * overtime_qty
        holiday_fee = float(product.get(f"{prefix}Holiday{suffix}", 0) or 0) * qty if holiday else 0.0
        holiday_overtime = (
            float(product.get(f"{prefix}HolidayOvertime{suffix}", 0) or 0) * overtime_qty
            if holiday and overtime_qty > 0
            else 0.0
        )
        component_total = base + overtime + holiday_fee + holiday_overtime
        components[target] = component_total
        breakdown[target] = {
            "base": base,
            "overtime": overtime,
            "holiday": holiday_fee,
            "holidayOvertime": holiday_overtime,
            "total": component_total,
        }

    mode = str(charge_mode_override or product.get(f"{prefix}FeeChargeMode") or "TIDAK_ADA").strip().upper()
    theoretical_components = dict(components)
    theoretical_breakdown = {key: dict(value) for key, value in breakdown.items()}
    theoretical_total = sum(theoretical_components.values())
    theoretical_base_total = sum(row["base"] for row in theoretical_breakdown.values())
    theoretical_overtime_total = sum(row["overtime"] for row in theoretical_breakdown.values())
    theoretical_holiday_total = sum(row["holiday"] for row in theoretical_breakdown.values())
    theoretical_holiday_overtime_total = sum(row["holidayOvertime"] for row in theoretical_breakdown.values())

    # TERMASUK berarti biaya telah diselesaikan langsung di luar flow pembayaran
    # harian PEPEG (mis. sudah termasuk SO/dokumen). Jangan membentuk kewajiban
    # Buruh/UH/Gudang lagi agar tidak terjadi pembayaran ganda.
    settlement_excluded = mode == "TERMASUK"
    if settlement_excluded:
        components = {"labor": 0.0, "daily": 0.0, "warehouse": 0.0}
        breakdown = {
            key: {"base": 0.0, "overtime": 0.0, "holiday": 0.0, "holidayOvertime": 0.0, "total": 0.0}
            for key in theoretical_breakdown
        }

    total = sum(components.values())
    base_total = sum(row["base"] for row in breakdown.values())
    overtime_total = sum(row["overtime"] for row in breakdown.values())
    holiday_total = sum(row["holiday"] for row in breakdown.values())
    holiday_overtime_total = sum(row["holidayOvertime"] for row in breakdown.values())
    work_status = "NORMAL" if overtime_qty <= 1e-9 else "LEMBUR_PENUH" if regular_qty <= 1e-9 else "LEMBUR_PARSIAL"
    return {
        "mode": mode,
        **components,
        "total": total,
        "chargeable": total if mode == payer_mode else 0.0,
        "breakdown": breakdown,
        "baseTotal": base_total,
        "overtimeTotal": overtime_total,
        "holidayTotal": holiday_total,
        "holidayOvertimeTotal": holiday_overtime_total,
        "settlementExcluded": settlement_excluded,
        "settlementReason": "SUDAH_DIBAYAR_LANGSUNG" if settlement_excluded else "",
        # Nilai teoritis disimpan hanya sebagai jejak audit; tidak dipakai
        # dalam rekap atau pembayaran Buruh/UH harian.
        "auditTheoreticalCost": {
            **theoretical_components,
            "total": theoretical_total,
            "baseTotal": theoretical_base_total,
            "overtimeTotal": theoretical_overtime_total,
            "holidayTotal": theoretical_holiday_total,
            "holidayOvertimeTotal": theoretical_holiday_overtime_total,
        } if settlement_excluded else {},
        "overtime": overtime_qty > 1e-9,
        "holiday": holiday,
        "regularQty": regular_qty,
        "overtimeQty": overtime_qty,
        "workStatus": work_status,
    }

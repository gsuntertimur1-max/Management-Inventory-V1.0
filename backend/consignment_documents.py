from __future__ import annotations

from collections import OrderedDict, defaultdict
import io

from fastapi import APIRouter, Depends, HTTPException
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.pdfbase.pdfmetrics import stringWidth

from backend.server import db, get_current_user, next_sequence, operational_now
from backend.role_four_config import has_role_permission, role_destination
from backend.pdf_documents import THERMAL_LOGO, _date, _measure_unit, _num
from backend.outbound_pdf_multi import _draw_sj_half, _group_items, _pdf_response, _sj_item_rows, _sj_paginate

router = APIRouter(prefix="/api")
BAZAR = "Gudang Bazar"


def document_series_code(kind: str) -> str:
    value = str(kind or "").strip().upper()
    if value == "BAZAR":
        return "BZR"
    if value in {"PAKET", "PAKET BAZAR"}:
        return "PKT"
    raise ValueError("Jenis dokumen Bazar tidak valid")


def _month_key(value: str) -> str:
    text = str(value or "").strip()
    if len(text) >= 7 and text[4] == "-":
        return text[:7].replace("-", "")
    return operational_now().strftime("%Y%m")


async def _next_document_number(kind: str, doc_type: str, event_date: str) -> str:
    series = document_series_code(kind)
    month = _month_key(event_date)
    seq = await next_sequence(f"consignment-doc:{doc_type}:{series}:{month}")
    return f"{doc_type}/{series}/{month}/{seq:04d}"


async def next_bazar_document_numbers(kind: str, event_date: str) -> dict:
    return {
        "suratJalanNo": await _next_document_number(kind, "SJ", event_date),
        "bonNo": await _next_document_number(kind, "BM", event_date),
    }


def _ensure_bazar_access(user: dict) -> None:
    scoped = role_destination(user.get("role"))
    if scoped and scoped != BAZAR:
        raise HTTPException(status_code=403, detail=f"Akun ini hanya memiliki akses ke {scoped}")
    if not has_role_permission(user.get("role"), "bazarOps"):
        raise HTTPException(status_code=403, detail="Tidak memiliki akses operasional Bazar")


async def _ensure_numbers(collection, doc: dict, kind: str, date_field: str) -> dict:
    patch = {}
    event_date = str(doc.get(date_field) or operational_now().strftime("%Y-%m-%d"))
    if not doc.get("suratJalanNo"):
        patch["suratJalanNo"] = await _next_document_number(kind, "SJ", event_date)
    if not doc.get("bonNo"):
        patch["bonNo"] = await _next_document_number(kind, "BM", event_date)
    if patch:
        await collection.update_one({"id": doc["id"]}, {"$set": patch})
        doc = {**doc, **patch}
    return doc


async def _product_metadata(product_id: str) -> dict:
    return await db.products.find_one({"id": product_id}, {"_id": 0}) or {}


async def _trip_items(trip: dict) -> list[dict]:
    rows = []
    for item in trip.get("items", []):
        product = await _product_metadata(item.get("productId", ""))
        qty = float(item.get("loadedQty", 0) or 0)
        weight = float(item.get("weight", product.get("weight", 0)) or 0)
        rows.append({
            "productId": item.get("productId", ""),
            "sku": item.get("sku", product.get("sku", "")),
            "name": item.get("name", product.get("name", "")),
            "unit": item.get("unit", product.get("unit", "")),
            "channel": item.get("channel", product.get("channel", "KOM")),
            "weight": weight,
            "measureUnit": item.get("measureUnit", product.get("measureUnit", "kg")) or "kg",
            "secondary": item.get("secondary", product.get("secondary", "")),
            "secondaryQty": float(item.get("secondaryQty", product.get("secondaryQty", 0)) or 0),
            "stackCode": item.get("stackCode") or "18/A01-BAZAR",
            "documentNo": trip.get("tripNo", ""),
            "qty": qty,
            "berat": qty * weight,
        })
    return rows


async def _package_items(load: dict) -> list[dict]:
    source = load.get("documentItems") or []
    if source:
        result = []
        for item in source:
            product = await _product_metadata(item.get("productId", ""))
            qty = float(item.get("qty", 0) or 0)
            weight = float(item.get("weight", product.get("weight", 0)) or 0)
            result.append({
                **item,
                "weight": weight,
                "measureUnit": item.get("measureUnit", product.get("measureUnit", "kg")) or "kg",
                "secondary": item.get("secondary", product.get("secondary", "")),
                "secondaryQty": float(item.get("secondaryQty", product.get("secondaryQty", 0)) or 0),
                "documentNo": item.get("documentNo") or load.get("loadNo", ""),
                "stackCode": item.get("stackCode") or "AREA PAKET BAZAR",
                "berat": qty * weight,
            })
        return result

    totals = defaultdict(float)
    for loaded in load.get("items", []):
        for component in loaded.get("components", []):
            totals[component.get("productId", "")] += float(loaded.get("loadedQty", 0) or 0) * float(component.get("qty", 0) or 0)
    rows = []
    for product_id, qty in totals.items():
        product = await _product_metadata(product_id)
        weight = float(product.get("weight", 0) or 0)
        rows.append({
            "productId": product_id,
            "sku": product.get("sku", ""),
            "name": product.get("name", ""),
            "unit": product.get("unit", ""),
            "channel": product.get("channel", "KOM"),
            "weight": weight,
            "measureUnit": product.get("measureUnit", "kg") or "kg",
            "secondary": product.get("secondary", ""),
            "secondaryQty": float(product.get("secondaryQty", 0) or 0),
            "stackCode": "AREA PAKET BAZAR",
            "documentNo": load.get("loadNo", ""),
            "qty": qty,
            "berat": qty * weight,
        })
    return rows


def _wrap_text(text: str, font_name: str, font_size: float, max_width: float) -> list[str]:
    words = str(text or "").split()
    if not words:
        return [""]
    lines = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if stringWidth(candidate, font_name, font_size) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _render_bon(load: dict, label: str):
    grouped = _group_items(load)
    width = 72 * mm
    left = 4 * mm
    right = width - 4 * mm
    content_width = right - left
    mid = width / 2
    table_label_w = 18 * mm
    table_number_w = 24 * mm
    colly_row_h = 7.2 * mm
    tonase_row_h = 7.2 * mm
    loading_row_h = 8.5 * mm
    table_h = (2 * colly_row_h) + tonase_row_h + loading_row_h

    content_height_mm = 112.0
    for document_no, rows in grouped.items():
        content_height_mm += len(_wrap_text(f"Dokumen: {document_no}", "Helvetica-Bold", 8.5, content_width)) * 4.0 + 2.0
        for item in rows.values():
            content_height_mm += len(_wrap_text(str(item.get("name", "")), "Helvetica-Bold", 8.5, content_width)) * 4.2
            content_height_mm += len(_wrap_text(f"Tumpukan: {item.get('stack', '-')}", "Helvetica-Bold", 8.0, content_width)) * 4.0
            content_height_mm += (table_h / mm) + 6.0

    fields = [
        ("Tanggal", _date(load.get("started_at") or load.get("created_at"), True)),
        ("Dokumen", ", ".join(load.get("documents") or [load.get("ref", "-")])),
        ("Tujuan", load.get("party", "-")),
        ("No Polisi", load.get("polisi", "-")),
        ("Sopir", load.get("pengambil", "-")),
        ("Unit", load.get("unit_loading", "-")),
        ("Rute", " -> ".join(dict.fromkeys(str(item.get("stackCode") or "-") for item in load.get("items", []))) or "-"),
    ]
    value_width = right - (22 * mm)
    for _, value in fields:
        content_height_mm += max(0, len(_wrap_text(str(value), "Helvetica-Bold", 8.0, value_width)) - 1) * 4.0

    height = max(210 * mm, content_height_mm * mm)
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(width, height))
    if THERMAL_LOGO.exists():
        c.drawImage(str(THERMAL_LOGO), (width - 32 * mm) / 2, height - 20 * mm, width=32 * mm, height=13.5 * mm, preserveAspectRatio=True, mask="auto")

    y = height - 27 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(mid, y, "BON PEMUATAN")
    y -= 4.2 * mm
    c.setFont("Helvetica", 6.5)
    c.drawCentredString(mid, y, "GBB SUNTER TIMUR I & II")
    y -= 5.2 * mm
    c.setFont("Helvetica", 6.5)
    c.drawCentredString(mid, y, "NOMOR BON MUAT")
    y -= 4.5 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(mid, y, str(load.get("bon_no", "-")))
    y -= 5.0 * mm
    c.setFont("Helvetica-Bold", 8.5)
    c.drawCentredString(mid, y, label)
    y -= 5.5 * mm

    c.setDash(2, 2)
    c.line(left, y, right, y)
    c.setDash()
    y -= 5.2 * mm

    value_x = 22 * mm
    value_width = right - value_x
    for field_label, value in fields:
        c.setFont("Helvetica", 8.0)
        c.drawString(left, y, field_label)
        lines = _wrap_text(str(value), "Helvetica-Bold", 8.0, value_width)
        c.setFont("Helvetica-Bold", 8.0)
        for index, line in enumerate(lines):
            if index > 0:
                y -= 4.0 * mm
            c.drawString(value_x, y, line)
        y -= 4.8 * mm

    y -= 1.0 * mm
    c.setDash(2, 2)
    c.line(left, y, right, y)
    c.setDash()
    y -= 5.0 * mm
    c.setFont("Helvetica-Bold", 7.0)
    c.drawString(left, y, "RINCIAN PEMUATAN PER DOKUMEN")
    y -= 5.0 * mm

    weight_totals = OrderedDict()
    for document_no, rows in grouped.items():
        c.setFont("Helvetica-Bold", 8.5)
        for line in _wrap_text(f"Dokumen: {document_no}", "Helvetica-Bold", 8.5, content_width):
            c.drawString(left, y, line)
            y -= 4.0 * mm
        y -= 1.2 * mm

        for item in rows.values():
            qty = float(item.get("qty", 0) or 0)
            measure = _measure_unit(item)
            weight_value = float(item.get("berat", 0) or 0)
            weight_totals[measure] = weight_totals.get(measure, 0.0) + weight_value

            c.setFont("Helvetica-Bold", 8.5)
            for line in _wrap_text(str(item.get("name", "")), "Helvetica-Bold", 8.5, content_width):
                c.drawString(left, y, line)
                y -= 4.2 * mm
            c.setFont("Helvetica-Bold", 8.0)
            for line in _wrap_text(f"Tumpukan: {item.get('stack', '-')}", "Helvetica-Bold", 8.0, content_width):
                c.drawString(left, y, line)
                y -= 4.0 * mm
            y -= 1.0 * mm

            secondary_qty = float(item.get("secondaryQty", 0) or 0)
            secondary_name = str(item.get("secondary") or "").strip()
            primary_unit = str(item.get("unit") or "pcs").strip()
            full_secondary = int(qty // secondary_qty) if secondary_qty > 0 else 0
            loose_primary = qty - (full_secondary * secondary_qty) if secondary_qty > 0 else qty
            secondary_number = _num(full_secondary) if secondary_qty > 0 else "-"
            secondary_unit = secondary_name if secondary_qty > 0 and secondary_name else "-"
            loose_number = _num(loose_primary)
            loading_location = str(item.get("stack", "") or load.get("unit_loading") or "-")

            table_left = left
            table_right = right
            table_width = table_right - table_left
            unit_w = table_width - table_label_w - table_number_w
            table_top = y
            table_bottom = table_top - table_h
            x_label = table_left + table_label_w
            x_number = x_label + table_number_w

            c.setLineWidth(0.7)
            c.rect(table_left, table_bottom, table_width, table_h, fill=0, stroke=1)
            c.line(x_label, table_bottom, x_label, table_top)
            c.line(x_number, table_bottom + loading_row_h, x_number, table_top)
            y_loading_top = table_bottom + loading_row_h
            y_tonase_top = y_loading_top + tonase_row_h
            y_colly_second_top = y_tonase_top + colly_row_h
            c.line(table_left, y_loading_top, table_right, y_loading_top)
            c.line(table_left, y_tonase_top, table_right, y_tonase_top)
            c.line(x_label, y_colly_second_top, table_right, y_colly_second_top)

            label_center = table_left + (table_label_w / 2)
            c.setFont("Helvetica-Bold", 7.0)
            c.drawCentredString(label_center, y_tonase_top + colly_row_h - 1.2 * mm, "Colly:")
            c.drawCentredString(label_center, y_loading_top + (tonase_row_h / 2) - 1.2 * mm, "Tonase:")
            c.drawCentredString(label_center, table_bottom + (loading_row_h / 2) - 1.2 * mm, "Pemuatan:")

            number_center = x_label + table_number_w / 2
            unit_center = x_number + unit_w / 2
            c.setFont("Helvetica-Bold", 10)
            c.drawCentredString(number_center, table_top - 4.9 * mm, secondary_number)
            c.drawCentredString(number_center, y_colly_second_top - 4.9 * mm, loose_number)
            c.setFont("Helvetica-Bold", 7.5)
            c.drawCentredString(unit_center, table_top - 4.8 * mm, secondary_unit)
            c.drawCentredString(unit_center, y_colly_second_top - 4.8 * mm, primary_unit)
            c.setFont("Helvetica-Bold", 10)
            c.drawCentredString(number_center, y_tonase_top - 5.0 * mm, _num(weight_value))
            c.setFont("Helvetica-Bold", 7.5)
            c.drawCentredString(unit_center, y_tonase_top - 4.8 * mm, measure)

            loading_center = x_label + (table_number_w + unit_w) / 2
            loading_font = 8.5
            while loading_font > 7.0 and stringWidth(loading_location, "Helvetica-Bold", loading_font) > ((table_number_w + unit_w) - 3 * mm):
                loading_font -= 0.5
            c.setFont("Helvetica-Bold", loading_font)
            c.drawCentredString(loading_center, table_bottom + 3.0 * mm, loading_location)
            y = table_bottom - 5.0 * mm

    c.setFont("Helvetica-Bold", 7.0)
    c.drawCentredString(mid, y, "TOTAL PEMUATAN")
    y -= 3.8 * mm
    c.setFont("Helvetica", 6.0)
    c.drawCentredString(mid, y, f"{len(grouped)} Dokumen | {sum(len(rows) for rows in grouped.values())} Produk")
    y -= 3.6 * mm
    physical_text = "Fisik: " + " + ".join(f"{_num(value)} {unit}" for unit, value in weight_totals.items())
    for line in _wrap_text(physical_text, "Helvetica", 6.0, content_width):
        c.drawCentredString(mid, y, line)
        y -= 3.6 * mm
    y -= 1.5 * mm
    c.setFont("Helvetica-Bold", 6.5)
    c.drawCentredString(mid, y, "Serahkan bon ini kepada petugas pemuatan")
    y -= 4.0 * mm
    c.setFont("Helvetica", 5.5)
    c.drawCentredString(mid, y, f"Dicetak: {_date(operational_now().isoformat(), True)}")
    c.save()
    return _pdf_response(buffer, f"bon_pemuatan_{str(load.get('bon_no', 'bazar')).replace('/', '-')}_72mm.pdf")


async def _render_sj(sj: dict):
    settings = await db.settings.find_one({"_id": "app"}, {"_id": 0}) or {}
    warehouse_head = settings.get("warehouseHead") or "Irsa Maulian Nugraha"
    grouped = _sj_item_rows(sj)
    page_w, page_h = landscape(A4)
    half_w = page_w / 2
    product_width = 66 * mm
    document_count = max(1, len(sj.get("documents") or [sj.get("ref", "")]))
    fixed_height = (94 + max(document_count - 1, 0) * 4.4) * mm
    bottom_reserved = 58 * mm
    detail_height = max(35 * mm, page_h - fixed_height - bottom_reserved)
    pages = _sj_paginate(grouped, product_width, detail_height)

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=landscape(A4))
    total_pages = len(pages)
    for page_index, page_rows in enumerate(pages, 1):
        _draw_sj_half(c, sj, page_rows, warehouse_head, 0, page_index, total_pages)
        _draw_sj_half(c, sj, page_rows, warehouse_head, half_w, page_index, total_pages)
        c.setStrokeColor(colors.HexColor("#B8B8B8"))
        c.setLineWidth(0.25)
        c.setDash(1.2, 2.2)
        c.line(half_w, 3 * mm, half_w, page_h - 3 * mm)
        c.setDash()
        c.setStrokeColor(colors.black)
        c.showPage()
    c.save()
    filename = str(sj.get("no") or sj.get("ref") or "bazar").replace("/", "-")
    return _pdf_response(buffer, f"surat_jalan_{filename}.pdf")


async def _trip_doc(trip: dict) -> tuple[dict, dict]:
    items = await _trip_items(trip)
    load = {
        "bon_no": trip.get("bonNo", ""),
        "created_at": trip.get("createdAt", ""),
        "started_at": trip.get("eventDate", ""),
        "documents": [trip.get("tripNo", "")],
        "ref": trip.get("tripNo", ""),
        "party": trip.get("location", ""),
        "polisi": trip.get("vehicleNo", ""),
        "pengambil": trip.get("driver", ""),
        "unit_loading": "BAZAR",
        "items": items,
    }
    sj = {
        "no": trip.get("suratJalanNo", ""),
        "ref": trip.get("tripNo", ""),
        "documents": [trip.get("tripNo", "")],
        "issued_at": trip.get("eventDate", ""),
        "penerima": trip.get("location", ""),
        "polisi": trip.get("vehicleNo", ""),
        "pengambil": trip.get("driver", ""),
        "unit_loading": "BZR",
        "items": items,
        "operator": trip.get("createdBy", ""),
    }
    return load, sj


async def _package_doc(load_row: dict) -> tuple[dict, dict]:
    items = await _package_items(load_row)
    load = {
        "bon_no": load_row.get("bonNo", ""),
        "created_at": load_row.get("createdAt", ""),
        "started_at": load_row.get("date", ""),
        "documents": [load_row.get("loadNo", "")],
        "ref": load_row.get("loadNo", ""),
        "party": load_row.get("destination", ""),
        "polisi": load_row.get("vehicleNo", ""),
        "pengambil": load_row.get("driver", ""),
        "unit_loading": "PAKET BAZAR",
        "items": items,
    }
    sj = {
        "no": load_row.get("suratJalanNo", ""),
        "ref": load_row.get("loadNo", ""),
        "documents": [load_row.get("loadNo", "")],
        "issued_at": load_row.get("date", ""),
        "penerima": load_row.get("destination", ""),
        "polisi": load_row.get("vehicleNo", ""),
        "pengambil": load_row.get("driver", ""),
        "unit_loading": "PKT",
        "items": items,
        "operator": load_row.get("createdBy", ""),
    }
    return load, sj


@router.post("/bazar/trips/{trip_id}/documents")
async def prepare_bazar_trip_documents(trip_id: str, user: dict = Depends(get_current_user)):
    _ensure_bazar_access(user)
    trip = await db.bazar_trips.find_one({"id": trip_id}, {"_id": 0})
    if not trip:
        raise HTTPException(status_code=404, detail="Perjalanan Bazar tidak ditemukan")
    return await _ensure_numbers(db.bazar_trips, trip, "BAZAR", "eventDate")


@router.post("/bazar/package-loads/{load_id}/documents")
async def prepare_bazar_package_documents(load_id: str, user: dict = Depends(get_current_user)):
    _ensure_bazar_access(user)
    load = await db.bazar_package_loads.find_one({"id": load_id}, {"_id": 0})
    if not load:
        raise HTTPException(status_code=404, detail="Pemuatan Paket Bazar tidak ditemukan")
    return await _ensure_numbers(db.bazar_package_loads, load, "PAKET", "date")


@router.get("/export/bazar/trips/{trip_id}/bon-muat.pdf")
async def export_bazar_trip_bon(trip_id: str, user: dict = Depends(get_current_user)):
    trip = await prepare_bazar_trip_documents(trip_id, user)
    load, _ = await _trip_doc(trip)
    return _render_bon(load, "BAZAR")


@router.get("/export/bazar/trips/{trip_id}/surat-jalan.pdf")
async def export_bazar_trip_sj(trip_id: str, user: dict = Depends(get_current_user)):
    trip = await prepare_bazar_trip_documents(trip_id, user)
    _, sj = await _trip_doc(trip)
    return await _render_sj(sj)


@router.get("/export/bazar/package-loads/{load_id}/bon-muat.pdf")
async def export_bazar_package_bon(load_id: str, user: dict = Depends(get_current_user)):
    load_row = await prepare_bazar_package_documents(load_id, user)
    load, _ = await _package_doc(load_row)
    return _render_bon(load, "PAKET BAZAR")


@router.get("/export/bazar/package-loads/{load_id}/surat-jalan.pdf")
async def export_bazar_package_sj(load_id: str, user: dict = Depends(get_current_user)):
    load_row = await prepare_bazar_package_documents(load_id, user)
    _, sj = await _package_doc(load_row)
    return await _render_sj(sj)


async def ensure_consignment_document_indexes() -> None:
    await db.bazar_trips.create_index("bonNo", unique=True, sparse=True)
    await db.bazar_trips.create_index("suratJalanNo", unique=True, sparse=True)
    await db.bazar_package_loads.create_index("bonNo", unique=True, sparse=True)
    await db.bazar_package_loads.create_index("suratJalanNo", unique=True, sparse=True)

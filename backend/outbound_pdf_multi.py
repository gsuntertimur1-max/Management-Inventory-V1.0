from collections import OrderedDict
import io

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import Paragraph, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet

from backend.server import db, get_current_user, operational_now
from backend.pdf_documents import LOGO, THERMAL_LOGO, _date, _num, _measure_unit

router = APIRouter(prefix="/api")


def _pdf_response(buffer: io.BytesIO, filename: str) -> StreamingResponse:
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


def _group_items(load: dict) -> OrderedDict:
    grouped = OrderedDict()
    for item in load.get("items", []):
        doc = str(item.get("documentNo") or load.get("ref") or "-").strip()
        by_doc = grouped.setdefault(doc, OrderedDict())
        stack = str(item.get("stackCode") or item.get("location") or "-").strip()
        key = f"{item.get('productId') or item.get('sku', '')}|{stack}|{item.get('channel', '')}"
        row = by_doc.setdefault(key, {**item, "stack": stack, "qty": 0.0, "berat": 0.0})
        row["qty"] += float(item.get("qty", 0) or 0)
        row["berat"] += float(item.get("berat", 0) or 0)
    return grouped


def _secondary_text(item: dict) -> str:
    qty = float(item.get("qty", 0) or 0)
    secondary_qty = float(item.get("secondaryQty", 0) or 0)
    if secondary_qty <= 0:
        return f"{_num(qty)} {item.get('unit', 'pcs')}"
    full = int(qty // secondary_qty)
    remainder = qty - (full * secondary_qty)
    text = f"{full} {item.get('secondary') or 'kemasan sekunder'}"
    if remainder > 1e-9:
        text += f" + {_num(remainder)} {item.get('unit', 'pcs')}"
    return text


def _loading_route(load: dict) -> str:
    seen = []
    for item in load.get("items", []):
        stack = str(item.get("stackCode") or item.get("location") or "").strip()
        if stack and stack not in seen:
            seen.append(stack)
    return " -> ".join(seen) or str(load.get("unit_loading") or "-")


@router.get("/export/bon-muat-v2/{load_id}.pdf")
async def export_bon_muat_multi_pdf(load_id: str, user: dict = Depends(get_current_user)):
    load = await db.outbound_loads.find_one({"id": load_id}, {"_id": 0})
    if not load:
        raise HTTPException(status_code=404, detail="Bon Muat tidak ditemukan")

    grouped = _group_items(load)
    width = 72 * mm
    left = 4 * mm
    right = width - 4 * mm
    content_width = right - left

    def wrap_text(text: str, font_name: str, font_size: float, max_width: float) -> list[str]:
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

    # Hitung tinggi thermal berdasarkan jumlah SO, produk, dan wrapping nama/detail.
    detail_lines = 0
    product_count = 0
    for _, rows in grouped.items():
        for item in rows.values():
            product_count += 1
            product_name = str(item.get("name", ""))
            detail = (
                f"Tumpukan {item.get('stack', '-')} | SKU {item.get('sku', '-')} | "
                f"Primer: {_num(item.get('qty', 0))} {item.get('unit','pcs')} | "
                f"Fisik: {_num(item.get('berat', 0))} {_measure_unit(item)}"
            )
            detail_lines += max(1, len(wrap_text(product_name, "Helvetica-Bold", 6.5, content_width)))
            detail_lines += max(1, len(wrap_text(detail, "Helvetica", 6.0, content_width - 2 * mm)))
            detail_lines += max(1, len(wrap_text(f"Sekunder: {_secondary_text(item)}", "Helvetica-Bold", 6.0, content_width - 2 * mm)))

    height = max(
        170 * mm,
        (124 + len(grouped) * 10 + product_count * 8 + detail_lines * 4.0) * mm,
    )
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(width, height))
    mid = width / 2

    if THERMAL_LOGO.exists():
        c.drawImage(
            str(THERMAL_LOGO),
            (width - 30 * mm) / 2,
            height - 17 * mm,
            width=30 * mm,
            height=13 * mm,
            preserveAspectRatio=True,
            mask="auto",
        )

    y = height - 23 * mm

    # Ukuran font mengikuti file acuan bon_pemuatan_BM-20260918-002.xlsx.
    c.setFont("Helvetica-Bold", 10)
    c.drawString(left, y, "BON PEMUATAN")
    y -= 4.2 * mm
    c.setFont("Helvetica", 6.5)
    c.drawString(left, y, "GBB SUNTER TIMUR I & II")

    y -= 5.5 * mm
    c.setDash(2, 2)
    c.line(left, y, right, y)
    c.setDash()
    y -= 4.5 * mm

    c.setFont("Helvetica", 6.5)
    c.drawString(left, y, "NOMOR BON MUAT")
    y -= 4.6 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(left, y, str(load.get("bon_no", "-")))

    y -= 4.8 * mm
    c.setFont("Helvetica", 6.5)
    c.drawString(left, y, "NOMOR ANTRIAN")
    y -= 8.8 * mm
    c.setFont("Helvetica-Bold", 24)
    c.drawString(left, y, str(load.get("antrian", "-")))

    y -= 6.0 * mm

    docs = ", ".join(load.get("documents") or [load.get("ref", "-")])
    fields = [
        ("Tanggal", _date(load.get("started_at") or load.get("created_at"), True)),
        ("Dokumen", docs),
        ("Tujuan", load.get("party", "-")),
        ("No Polisi", load.get("polisi", "-")),
        ("Sopir", load.get("pengambil", "-")),
        ("Unit", load.get("unit_loading", "-")),
        ("Rute", _loading_route(load)),
    ]
    value_x = 22 * mm
    for label, value in fields:
        c.setFont("Helvetica", 6.0)
        c.drawString(left, y, label)
        c.setFont("Helvetica-Bold", 6.0)
        value_text = str(value)
        value_font = 6.0
        while value_font > 5.0 and stringWidth(value_text, "Helvetica-Bold", value_font) > (right - value_x):
            value_font -= 0.25
        c.setFont("Helvetica-Bold", value_font)
        c.drawString(value_x, y, value_text)
        y -= 3.7 * mm

    y -= 1.0 * mm
    c.setDash(2, 2)
    c.line(left, y, right, y)
    c.setDash()
    y -= 4.5 * mm

    c.setFont("Helvetica-Bold", 7.0)
    c.drawString(left, y, "RINCIAN PEMUATAN PER DOKUMEN")
    y -= 5.0 * mm

    grand_qty = 0.0
    weight_totals = OrderedDict()

    for document_no, rows in grouped.items():
        # Header per SO/dokumen sama seperti file acuan.
        c.setFillColor(colors.HexColor("#E6EFF2"))
        c.rect(left, y - 5 * mm, content_width, 5 * mm, fill=1, stroke=0)
        c.setFillColor(colors.HexColor("#244B63"))
        c.setFont("Helvetica-Bold", 6.5)
        doc_text = f"DOKUMEN: {document_no}"
        c.drawString(left + 0.5 * mm, y - 3.5 * mm, doc_text)
        c.setFillColor(colors.black)
        y -= 7.0 * mm

        for item in rows.values():
            qty = float(item.get("qty", 0) or 0)
            grand_qty += qty
            measure = _measure_unit(item)
            weight_totals[measure] = weight_totals.get(measure, 0.0) + float(item.get("berat", 0) or 0)

            # Nama komoditi/merk selalu wrap, tidak dipotong.
            product_lines = wrap_text(str(item.get("name", "")), "Helvetica-Bold", 6.5, content_width)
            c.setFont("Helvetica-Bold", 6.5)
            for line in product_lines:
                c.drawString(left, y, line)
                y -= 3.6 * mm

            detail = (
                f"Tumpukan {item.get('stack', '-')} | SKU {item.get('sku', '-')} | "
                f"Primer: {_num(qty)} {item.get('unit','pcs')} | "
                f"Fisik: {_num(item.get('berat',0))} {measure}"
            )
            detail_lines_wrapped = wrap_text(detail, "Helvetica", 6.0, content_width - 2 * mm)
            c.setFont("Helvetica", 6.0)
            for line in detail_lines_wrapped:
                c.drawString(left + 1.5 * mm, y, line)
                y -= 3.4 * mm

            secondary_lines = wrap_text(
                f"Sekunder: {_secondary_text(item)}",
                "Helvetica-Bold",
                6.0,
                content_width - 2 * mm,
            )
            c.setFont("Helvetica-Bold", 6.0)
            for line in secondary_lines:
                c.drawString(left + 1.5 * mm, y, line)
                y -= 3.4 * mm

            # Jarak antar produk. Multi-produk tetap ukuran font yang sama.
            y -= 2.0 * mm

    c.setDash(2, 2)
    c.line(left, y, right, y)
    c.setDash()
    y -= 4.5 * mm

    c.setFont("Helvetica-Bold", 7.0)
    c.drawCentredString(mid, y, "TOTAL PEMUATAN")
    y -= 3.8 * mm
    c.setFont("Helvetica", 6.0)
    c.drawCentredString(mid, y, f"Primer: {_num(grand_qty)} unit/pack/pcs")
    y -= 3.6 * mm

    physical_text = "Fisik: " + " + ".join(f"{_num(value)} {unit}" for unit, value in weight_totals.items())
    physical_lines = wrap_text(physical_text, "Helvetica", 6.0, content_width)
    for line in physical_lines:
        c.drawCentredString(mid, y, line)
        y -= 3.6 * mm

    y -= 1.5 * mm
    c.setFont("Helvetica-Bold", 6.5)
    c.drawCentredString(mid, y, "Serahkan bon ini kepada petugas pemuatan")
    y -= 4.2 * mm
    c.setFont("Helvetica", 5.5)
    c.drawCentredString(mid, y, f"Dicetak: {_date(operational_now().isoformat(), True)}")

    c.save()
    return _pdf_response(buffer, f"bon_pemuatan_{load.get('bon_no', load_id)}_72mm.pdf")


def _sj_item_rows(sj: dict):
    grouped = OrderedDict()
    for item in sj.get("items", []):
        doc = str(item.get("documentNo") or sj.get("ref") or "-")
        grouped.setdefault(doc, []).append(item)
    return grouped


def _draw_sj_page(c: canvas.Canvas, sj: dict, items_by_doc: list[tuple[str, list[dict]]], warehouse_head: str, copy_label: str):
    w, h = landscape(A4)
    left, right = 14 * mm, w - 14 * mm
    if LOGO.exists():
        c.drawImage(str(LOGO), left, h - 29 * mm, width=35 * mm, height=16 * mm, preserveAspectRatio=True, mask="auto")
    c.setFont("Helvetica-Bold", 15); c.drawCentredString(w / 2, h - 18 * mm, "SURAT JALAN")
    c.setFont("Helvetica", 7); c.drawRightString(right, h - 17 * mm, copy_label)
    c.setFont("Helvetica-Bold", 8); c.drawCentredString(w / 2, h - 24 * mm, sj.get("no", ""))
    c.setFont("Helvetica", 7)
    c.drawString(left, h - 36 * mm, f"Penerima: {sj.get('penerima','-')}")
    c.drawString(left + 95 * mm, h - 36 * mm, f"Nopol / Sopir: {sj.get('polisi','-')} / {sj.get('pengambil','-')}")
    c.drawString(left, h - 42 * mm, f"Dokumen: {', '.join(sj.get('documents') or [sj.get('ref','-')])}")
    c.drawString(left, h - 48 * mm, f"Lokasi muat: {_loading_route(sj)}")

    styles = getSampleStyleSheet()
    small = ParagraphStyle("sj-multi-small", parent=styles["BodyText"], fontName="Helvetica", fontSize=6.2, leading=7.4)
    small_bold = ParagraphStyle("sj-multi-bold", parent=small, fontName="Helvetica-Bold")
    data = [[Paragraph("DOKUMEN", small_bold), Paragraph("TUMPUKAN", small_bold), Paragraph("PRODUK / SKU", small_bold), Paragraph("PRIMER", small_bold), Paragraph("SEKUNDER", small_bold), Paragraph("FISIK", small_bold)]]
    for document_no, rows in items_by_doc:
        for item in rows:
            data.append([
                Paragraph(document_no, small),
                Paragraph(str(item.get("stackCode") or item.get("location") or "-"), small),
                Paragraph(f"{item.get('name','')}<br/><font size='5'>{item.get('sku','')}</font>", small),
                Paragraph(f"{_num(item.get('qty'))} {item.get('unit','')}", small),
                Paragraph(_secondary_text(item), small),
                Paragraph(f"{_num(item.get('berat'))} {_measure_unit(item)}", small),
            ])
    table = Table(data, colWidths=[45*mm, 31*mm, 78*mm, 33*mm, 48*mm, 34*mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#527D96")), ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("GRID", (0,0), (-1,-1), .35, colors.HexColor("#777777")), ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 3), ("BOTTOMPADDING", (0,0), (-1,-1), 3),
    ]))
    table.wrapOn(c, right-left, h)
    table.drawOn(c, left, h - 55*mm - table._height)

    sign_y = 24 * mm
    c.setFont("Helvetica", 7); c.drawCentredString(left + 50*mm, sign_y + 20*mm, "Pengangkut / Pengambil")
    c.drawCentredString(right - 50*mm, sign_y + 20*mm, "Yang Menyerahkan")
    c.line(left + 25*mm, sign_y, left + 75*mm, sign_y)
    c.setFont("Helvetica-Bold", 7); c.drawCentredString(right - 50*mm, sign_y, warehouse_head)
    c.setFont("Helvetica", 5.8); c.drawString(left, 8*mm, f"Delivery Slip | Dicetak: {_date(operational_now().isoformat(), True)}")


@router.get("/export/surat-jalan/{sj_id}.pdf")
async def export_surat_jalan_multi_pdf(sj_id: str, user: dict = Depends(get_current_user)):
    sj = await db.surat_jalan.find_one({"id": sj_id}, {"_id": 0})
    if not sj:
        raise HTTPException(status_code=404, detail="Surat Jalan tidak ditemukan")
    settings = await db.settings.find_one({"_id": "app"}, {"_id": 0}) or {}
    warehouse_head = settings.get("warehouseHead") or "Irsa Maulian Nugraha"
    grouped = list(_sj_item_rows(sj).items())

    # Batasi per halaman berdasarkan jumlah baris agar tidak ada item yang terpotong.
    pages = []
    current = []
    count = 0
    for document_no, rows in grouped:
        for item in rows:
            if count >= 12:
                pages.append(current); current = []; count = 0
            current.append((document_no, [item])); count += 1
    if current or not pages:
        pages.append(current)

    buffer = io.BytesIO(); c = canvas.Canvas(buffer, pagesize=landscape(A4))
    total_pages = len(pages)
    for page_index, page_rows in enumerate(pages, 1):
        _draw_sj_page(c, sj, page_rows, warehouse_head, f"Halaman {page_index}/{total_pages}")
        c.showPage()
    c.save()
    return _pdf_response(buffer, f"surat_jalan_{(sj.get('no') or sj.get('ref') or sj_id).replace('/', '-')}.pdf")

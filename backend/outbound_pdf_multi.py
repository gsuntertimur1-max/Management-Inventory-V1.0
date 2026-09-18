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


@router.get("/export/bon-muat/{load_id}.pdf")
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
    mid = width / 2

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

    # Ukuran tabel kuantum 72 mm. Lebar dipertahankan, tinggi dirapatkan
    # agar seimbang dengan ukuran angka/font operasional.
    table_label_w = 18 * mm
    table_number_w = 24 * mm
    colly_row_h = 7.2 * mm
    tonase_row_h = 7.2 * mm
    loading_row_h = 8.5 * mm
    table_h = (2 * colly_row_h) + tonase_row_h + loading_row_h

    # Hitung tinggi kertas dinamis. Font tidak dikecilkan saat SO/produk bertambah.
    # Tambahkan ruang ekstra untuk jarak logo ke judul dan typography rincian yang diperbesar.
    content_height_mm = 116.0
    for document_no, rows in grouped.items():
        document_lines = wrap_text(f"Dokumen: {document_no}", "Helvetica-Bold", 8.5, content_width)
        content_height_mm += (len(document_lines) * 4.0) + 2.0
        for item in rows.values():
            product_lines = wrap_text(str(item.get("name", "")), "Helvetica-Bold", 8.5, content_width)
            stack_lines = wrap_text(f"Tumpukan: {item.get('stack', '-')}", "Helvetica-Bold", 8.0, content_width)
            content_height_mm += (len(product_lines) * 4.2) + (len(stack_lines) * 4.0) + (table_h / mm) + 6.0

    fields_preview = [
        ("Tanggal", _date(load.get("started_at") or load.get("created_at"), True)),
        ("Dokumen", ", ".join(load.get("documents") or [load.get("ref", "-")])),
        ("Tujuan", load.get("party", "-")),
        ("No Polisi", load.get("polisi", "-")),
        ("Sopir", load.get("pengambil", "-")),
        ("Unit", load.get("unit_loading", "-")),
        ("Rute", _loading_route(load)),
    ]
    value_width = right - (22 * mm)
    for _, value in fields_preview:
        content_height_mm += max(0, len(wrap_text(str(value), "Helvetica-Bold", 8.0, value_width)) - 1) * 4.0

    height = max(220 * mm, content_height_mm * mm)
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(width, height))

    # Logo thermal hitam, rata tengah.
    if THERMAL_LOGO.exists():
        c.drawImage(
            str(THERMAL_LOGO),
            (width - 32 * mm) / 2,
            height - 20 * mm,
            width=32 * mm,
            height=13.5 * mm,
            preserveAspectRatio=True,
            mask="auto",
        )

    y = height - 27 * mm

    # Header sampai nomor antrian rata tengah.
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

    y -= 4.6 * mm
    c.setFont("Helvetica", 6.5)
    c.drawCentredString(mid, y, "NOMOR ANTRIAN")
    y -= 8.6 * mm
    c.setFont("Helvetica-Bold", 24)
    c.drawCentredString(mid, y, str(load.get("antrian", "-")))

    y -= 6.0 * mm
    c.setDash(2, 2)
    c.line(left, y, right, y)
    c.setDash()
    y -= 5.2 * mm

    # Tanggal s.d. Rute +2 pt dari format acuan sebelumnya: 8 pt.
    fields = fields_preview
    value_x = 22 * mm
    value_width = right - value_x
    for label, value in fields:
        c.setFont("Helvetica", 8.0)
        c.drawString(left, y, label)

        value_lines = wrap_text(str(value), "Helvetica-Bold", 8.0, value_width)
        c.setFont("Helvetica-Bold", 8.0)
        for index, line in enumerate(value_lines):
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

    grand_qty = 0.0
    weight_totals = OrderedDict()

    for document_no, rows in grouped.items():
        # Thermal-friendly: tanpa blok warna. "Dokumen: ..." diperbesar 2 pt dan wrap bila perlu.
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", 8.5)
        for line in wrap_text(f"Dokumen: {document_no}", "Helvetica-Bold", 8.5, content_width):
            c.drawString(left, y, line)
            y -= 4.0 * mm
        y -= 1.2 * mm

        for item in rows.values():
            qty = float(item.get("qty", 0) or 0)
            grand_qty += qty
            measure = _measure_unit(item)
            weight_value = float(item.get("berat", 0) or 0)
            weight_totals[measure] = weight_totals.get(measure, 0.0) + weight_value

            # Nama komoditi/merk diperbesar 2 pt dan tetap wrap ke bawah.
            c.setFont("Helvetica-Bold", 8.5)
            for line in wrap_text(str(item.get("name", "")), "Helvetica-Bold", 8.5, content_width):
                c.drawString(left, y, line)
                y -= 4.2 * mm

            # Hapus pengulangan "SO: ... |"; cukup tampilkan lokasi tumpukan, +2 pt.
            c.setFont("Helvetica-Bold", 8.0)
            for line in wrap_text(f"Tumpukan: {item.get('stack', '-')}", "Helvetica-Bold", 8.0, content_width):
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
            if "/" in loading_location:
                loading_location = f"Unit {loading_location.split('/', 1)[0]}"

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

            # Colly / Tonase / Pemuatan rata tengah horizontal dan vertikal.
            label_center = table_left + (table_label_w / 2)
            c.setFont("Helvetica-Bold", 7.0)
            colly_center_y = y_tonase_top + colly_row_h
            c.drawCentredString(label_center, colly_center_y - 1.2 * mm, "Colly:")
            tonase_center_y = y_loading_top + (tonase_row_h / 2)
            c.drawCentredString(label_center, tonase_center_y - 1.2 * mm, "Tonase:")
            loading_center_y = table_bottom + (loading_row_h / 2)
            c.drawCentredString(label_center, loading_center_y - 1.2 * mm, "Pemuatan:")

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
    for line in wrap_text(physical_text, "Helvetica", 6.0, content_width):
        c.drawCentredString(mid, y, line)
        y -= 3.6 * mm

    y -= 1.5 * mm
    c.setFont("Helvetica-Bold", 6.5)
    c.drawCentredString(mid, y, "Serahkan bon ini kepada petugas pemuatan")
    y -= 4.0 * mm
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

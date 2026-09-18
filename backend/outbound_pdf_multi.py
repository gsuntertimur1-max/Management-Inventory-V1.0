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
        doc = str(item.get("documentNo") or sj.get("ref") or "-").strip()
        grouped.setdefault(doc, []).append(item)
    return grouped


def _sj_wrap(text: str, font_name: str, font_size: float, max_width: float) -> list[str]:
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


def _sj_unit_codes(sj: dict) -> str:
    seen = []
    for item in sj.get("items", []):
        stack = str(item.get("stackCode") or item.get("location") or "").strip().upper()
        if not stack:
            continue
        unit = stack.split("/", 1)[0] if "/" in stack else stack
        if unit and unit not in seen:
            seen.append(unit)
    if seen:
        return ", ".join(seen)
    fallback = str(sj.get("unit_loading") or "").strip()
    return fallback or "-"


def _sj_quantity_lines(item: dict) -> tuple[str, str]:
    qty = float(item.get("qty", 0) or 0)
    secondary_qty = float(item.get("secondaryQty", 0) or 0)
    primary_unit = str(item.get("unit") or "pcs").strip()
    if secondary_qty <= 0:
        return "-", f"{_num(qty)} {primary_unit}"
    full_secondary = int(qty // secondary_qty)
    remainder = qty - (full_secondary * secondary_qty)
    secondary_name = str(item.get("secondary") or "Kemasan").strip()
    return f"{_num(full_secondary)} {secondary_name}", f"{_num(remainder)} {primary_unit}"


def _sj_row_height(item: dict, product_width: float) -> float:
    product_lines = _sj_wrap(str(item.get("name") or ""), "Helvetica-Bold", 7.0, product_width - 4 * mm)
    return max(12 * mm, (len(product_lines) * 3.7 + 4.5) * mm)


def _sj_paginate(grouped: OrderedDict, product_width: float, max_detail_height: float) -> list[list[tuple[str, list[dict]]]]:
    pages = []
    current = []
    used = 0.0
    group_header_h = 5.5 * mm

    for document_no, rows in grouped.items():
        group_open = False
        for item in rows:
            row_h = _sj_row_height(item, product_width)
            required = row_h + (0 if group_open else group_header_h)
            if current and used + required > max_detail_height:
                pages.append(current)
                current = []
                used = 0.0
                group_open = False
                required = row_h + group_header_h

            if not group_open:
                current.append((document_no, []))
                used += group_header_h
                group_open = True

            current[-1][1].append(item)
            used += row_h

    if current or not pages:
        pages.append(current)
    return pages


def _draw_sj_half(
    c: canvas.Canvas,
    sj: dict,
    items_by_doc: list[tuple[str, list[dict]]],
    warehouse_head: str,
    x0: float,
    page_no: int,
    total_pages: int,
):
    page_w, page_h = landscape(A4)
    half_w = page_w / 2
    left = x0 + 4.5 * mm
    right = x0 + half_w - 4.5 * mm
    width = right - left
    center = (left + right) / 2
    y = page_h - 5 * mm

    # Logo BULOG berwarna di atas kode Kanwil, mengikuti contoh pengguna.
    if LOGO.exists():
        c.drawImage(
            str(LOGO),
            left,
            y - 8.3 * mm,
            width=28 * mm,
            height=8.3 * mm,
            preserveAspectRatio=True,
            mask="auto",
        )
    y -= 11 * mm

    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 7.8)
    c.drawString(left, y, "09001 - KANWIL DKI JAKARTA BANTEN")
    y -= 7 * mm

    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(center, y, "SURAT JALAN MANUAL")
    y -= 2.8 * mm
    c.setFillColor(colors.HexColor("#BDBDBD"))
    c.rect(left, y - 2.4 * mm, width, 3.1 * mm, fill=1, stroke=0)
    c.setFillColor(colors.black)
    y -= 6.5 * mm

    c.setFont("Helvetica", 8)
    c.drawCentredString(center, y, str(sj.get("no") or sj.get("ref") or "-"))
    if total_pages > 1:
        c.setFont("Helvetica", 5.2)
        c.drawRightString(right, y, f"Hal. {page_no}/{total_pages}")
    y -= 8 * mm

    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(left, y, "Penerima")
    c.setFont("Helvetica", 7.5)
    c.drawString(left + 21 * mm, y, ":")
    c.setFont("Helvetica", 8)
    penerima = str(sj.get("penerima") or "-")
    penerima_font = 8.0
    while penerima_font > 6.2 and stringWidth(penerima, "Helvetica", penerima_font) > (width - 27 * mm):
        penerima_font -= 0.2
    c.setFont("Helvetica", penerima_font)
    c.drawString(left + 25 * mm, y, penerima)
    y -= 10 * mm

    c.setFont("Helvetica-Bold", 7.3)
    c.drawString(left, y, "Gudang Asal :")
    c.drawString(right - 31 * mm, y, "Unit Gudang :")
    y -= 5 * mm
    warehouse_name = "KOMPLEKS GUDANG SUNTER TIMUR I & II"
    wh_font = 7.5
    while wh_font > 6.2 and stringWidth(warehouse_name, "Helvetica-Bold", wh_font) > (width - 35 * mm):
        wh_font -= 0.2
    c.setFont("Helvetica-Bold", wh_font)
    c.drawString(left, y, warehouse_name)
    c.setFont("Helvetica-Bold", 7.7)
    c.drawCentredString(right - 10 * mm, y, _sj_unit_codes(sj))
    y -= 9 * mm

    # Daftar seluruh dokumen sumber pada setiap copy/page.
    documents = [str(value or "").strip() for value in (sj.get("documents") or [sj.get("ref", "")]) if str(value or "").strip()]
    date_x = right - 37 * mm
    c.setFont("Helvetica-Bold", 7.2)
    c.drawString(left, y, "Dokumen Sumber")
    c.drawString(date_x, y, "Tanggal")
    y -= 1.6 * mm
    c.setLineWidth(0.45)
    c.line(left, y, right, y)
    y -= 4.2 * mm

    issued = _date(sj.get("issued_at") or sj.get("time"), True)
    c.setFont("Helvetica", 6.7)
    for document_no in documents:
        doc_font = 6.9
        while doc_font > 5.8 and stringWidth(document_no, "Helvetica", doc_font) > (date_x - left - 3 * mm):
            doc_font -= 0.2
        c.setFont("Helvetica", doc_font)
        c.drawString(left, y, document_no)
        c.setFont("Helvetica", 6.4)
        c.drawString(date_x, y, issued)
        y -= 4.4 * mm
    y -= 4.0 * mm

    # Tabel produk: Produk | Kuantitas (sekunder + sisa primer) | Kuantum fisik.
    product_w = 66 * mm
    qty_w = 31 * mm
    quantum_w = width - product_w - qty_w
    x1 = left + product_w
    x2 = x1 + qty_w

    c.setFont("Helvetica", 7.2)
    c.drawCentredString(left + product_w / 2, y, "Produk")
    c.drawCentredString(x1 + qty_w / 2, y, "Kuantitas")
    c.drawCentredString(x2 + quantum_w / 2, y, "Kuantum")
    y -= 4.6 * mm
    c.line(left, y, right, y)

    for document_no, rows in items_by_doc:
        group_h = 5.5 * mm
        c.setFillColor(colors.HexColor("#EEEEEE"))
        c.rect(left, y - group_h, width, group_h, fill=1, stroke=0)
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", 6.5)
        group_text = f"Dokumen: {document_no}"
        group_font = 6.5
        while group_font > 5.5 and stringWidth(group_text, "Helvetica-Bold", group_font) > (width - 4 * mm):
            group_font -= 0.2
        c.setFont("Helvetica-Bold", group_font)
        c.drawString(left + 2 * mm, y - 3.8 * mm, group_text)
        y -= group_h
        c.line(left, y, right, y)

        for item in rows:
            product_lines = _sj_wrap(str(item.get("name") or ""), "Helvetica-Bold", 7.0, product_w - 4 * mm)
            row_h = _sj_row_height(item, product_w)
            row_top = y
            row_bottom = y - row_h

            c.line(left, row_bottom, right, row_bottom)
            c.line(x1, row_top, x1, row_bottom)
            c.line(x2, row_top, x2, row_bottom)

            py = row_top - 4.4 * mm
            c.setFont("Helvetica-Bold", 7.0)
            for line in product_lines:
                c.drawCentredString(left + product_w / 2, py, line)
                py -= 3.7 * mm

            sku = str(item.get("sku") or "").strip()
            if sku and py > row_bottom + 2.2 * mm:
                c.setFont("Helvetica", 5.2)
                c.drawCentredString(left + product_w / 2, py, sku)

            secondary_line, remainder_line = _sj_quantity_lines(item)
            qty_center = x1 + qty_w / 2
            c.setFont("Helvetica-Bold", 7.7)
            c.drawCentredString(qty_center, row_top - 4.8 * mm, secondary_line)
            c.setFont("Helvetica", 6.8)
            c.drawCentredString(qty_center, row_top - 9.0 * mm, remainder_line)

            physical = f"{_num(item.get('berat', 0))} {_measure_unit(item)}"
            physical_font = 7.8
            while physical_font > 6.2 and stringWidth(physical, "Helvetica", physical_font) > (quantum_w - 2 * mm):
                physical_font -= 0.2
            c.setFont("Helvetica", physical_font)
            c.drawCentredString(x2 + quantum_w / 2, row_top - 6.7 * mm, physical)

            y = row_bottom

    y -= 4.2 * mm
    note = " / ".join(value for value in [str(sj.get("pengambil") or "").strip(), str(sj.get("polisi") or "").strip()] if value) or "-"
    c.setFont("Helvetica", 6.9)
    c.drawString(left, y, "Catatan/Nopol/No Kontainer :")
    note_font = 7.2
    while note_font > 6.0 and stringWidth(note, "Helvetica", note_font) > (width - 62 * mm):
        note_font -= 0.2
    c.setFont("Helvetica", note_font)
    c.drawString(left + 60 * mm, y, note)
    y -= 9 * mm

    left_sig = left + 22 * mm
    right_sig = right - 36 * mm
    c.setFont("Helvetica", 7)
    c.drawCentredString(left_sig, y, "Pengangkut,")
    c.drawCentredString(right_sig, y + 4 * mm, "Yang Menyerahkan,")
    c.setFont("Helvetica-Bold", 6.4)
    c.drawCentredString(right_sig, y, warehouse_name)
    y -= 20 * mm
    c.setFont("Helvetica-Bold", 7.1)
    c.drawCentredString(left_sig, y, str(sj.get("pengambil") or "-"))
    c.drawCentredString(right_sig, y, warehouse_head)
    y -= 8 * mm

    c.setFont("Helvetica-Bold", 12)
    c.drawString(left, y, "Delivery Tracking")
    y -= 2.6 * mm
    c.line(left, y, right, y)
    y -= 4 * mm
    c.setFont("Helvetica", 5.1)
    c.drawString(left, y, "Dicetak oleh")
    c.drawString(left + 22 * mm, y, ":")
    c.drawString(left + 25 * mm, y, str(sj.get("operator") or "Petugas Gudang"))
    y -= 3.8 * mm
    c.drawString(left, y, "Pada Waktu")
    c.drawString(left + 22 * mm, y, ":")
    c.drawString(left + 25 * mm, y, _date(operational_now().isoformat(), True))


@router.get("/export/surat-jalan/{sj_id}.pdf")
async def export_surat_jalan_multi_pdf(sj_id: str, user: dict = Depends(get_current_user)):
    sj = await db.surat_jalan.find_one({"id": sj_id}, {"_id": 0})
    if not sj:
        raise HTTPException(status_code=404, detail="Surat Jalan tidak ditemukan")

    settings = await db.settings.find_one({"_id": "app"}, {"_id": 0}) or {}
    warehouse_head = settings.get("warehouseHead") or "Irsa Maulian Nugraha"
    grouped = _sj_item_rows(sj)

    # Setengah A4 hanya punya tinggi efektif terbatas. Saat produk banyak,
    # tambahkan halaman A4 landscape berikutnya, tetap dua copy per halaman.
    page_w, page_h = landscape(A4)
    half_w = page_w / 2
    content_width = half_w - 9 * mm
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

        # Garis bantu potong tanpa tulisan.
        c.setStrokeColor(colors.HexColor("#B8B8B8"))
        c.setLineWidth(0.25)
        c.setDash(1.2, 2.2)
        c.line(half_w, 3 * mm, half_w, page_h - 3 * mm)
        c.setDash()
        c.setStrokeColor(colors.black)

        c.showPage()

    c.save()
    filename = (sj.get("no") or sj.get("ref") or sj_id).replace("/", "-")
    return _pdf_response(buffer, f"surat_jalan_{filename}_A4_landscape_2copy.pdf")

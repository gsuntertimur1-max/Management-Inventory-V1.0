import io
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import LongTable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from backend.server import db, get_current_user, operational_now

router = APIRouter(prefix="/api")
LOGO = Path(__file__).resolve().parents[1] / "backend" / "assets" / "logo-bulog-gst.png"
THERMAL_LOGO = Path(__file__).resolve().parents[1] / "backend" / "assets" / "logo-bulog-gst-thermal.png"
SOFT_HEADER = colors.HexColor("#527D96")


def _pdf_response(buffer: io.BytesIO, filename: str) -> StreamingResponse:
    buffer.seek(0)
    return StreamingResponse(buffer, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _num(value) -> str:
    number = float(value or 0)
    if abs(number - round(number)) < 1e-9:
        return f"{int(round(number)):,}".replace(",", ".")
    return f"{number:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _date(value, with_time=False) -> str:
    if not value:
        return "-"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.strftime("%d/%m/%Y, %H:%M" if with_time else "%d/%m/%Y")
    except ValueError:
        return str(value)


def _arrangement(item: dict) -> str:
    blocks = item.get("arrangements") or [{"hamparan": item.get("length", 0), "kaki": item.get("width", 0), "height": item.get("height", 0)}]
    parts = [f"{x.get('hamparan', 0)} X {x.get('kaki', 0)} X {x.get('height', 0)} = {_num(float(x.get('hamparan', 0) or 0) * float(x.get('kaki', 0) or 0) * float(x.get('height', 0) or 0))}" for x in blocks]
    if item.get("extraSecondary"):
        parts.append(f"+ {_num(item['extraSecondary'])} tambahan")
    if item.get("extraPrimary"):
        parts.append(f"+ {_num(item['extraPrimary'])} {item.get('unit', '')} lepas")
    return " ; ".join(parts)


@router.get("/export/stack-card.pdf")
async def export_stack_card_pdf(stackCode: str, user: dict = Depends(get_current_user)):
    code = stackCode.strip().upper()
    items = await db.stack_allocations.find({"stackCode": code}, {"_id": 0}).sort("productName", 1).to_list(1000)
    if not items:
        raise HTTPException(status_code=404, detail="Tumpukan belum memiliki komoditas")
    warehouse = code.split("/", 1)[0]
    treatments = await db.stack_treatments.find({"$or": [{"stackCode": code}, {"type": "SPRAYING", "warehouse": warehouse}]}, {"_id": 0}).sort("startDate", -1).to_list(5000)
    history = await db.stack_history.find({"stackCode": code}, {"_id": 0}).sort("time", -1).to_list(5000)
    spraying = next((x for x in treatments if x.get("type") == "SPRAYING"), None)
    fumigasi = next((x for x in treatments if x.get("type") != "SPRAYING"), None)
    settings = await db.settings.find_one({"_id": "app"}, {"_id": 0}) or {}
    warehouse_head = settings.get("warehouseHead") or "Irsa Maulian Nugraha"

    buffer = io.BytesIO()
    # Sisakan area header pada setiap halaman agar logo tidak tertutup tabel riwayat.
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm, topMargin=24 * mm, bottomMargin=11 * mm)
    styles = getSampleStyleSheet()
    title = ParagraphStyle("title", parent=styles["Title"], alignment=TA_CENTER, fontName="Helvetica-Bold", fontSize=15, leading=18, spaceAfter=2)
    small = ParagraphStyle("small", parent=styles["BodyText"], fontName="Helvetica", fontSize=6.5, leading=8)
    center = ParagraphStyle("center", parent=small, alignment=TA_CENTER)
    story = [Paragraph("K A R T U &nbsp; T U M P U K A N", title), Paragraph("GBB Sunter Timur I &amp; II", ParagraphStyle("sub", parent=title, fontSize=9, leading=12, spaceAfter=12)), Spacer(1, 5 * mm)]
    headers = ["NO", "TANGGAL", "GUDANG", "LOKASI", "SKU", "NAMA PRODUK", "NETTO", "KOLLY", "SPRAYING", "FUMIGASI", "KETERANGAN", "PERHITUNGAN TUMPUKAN"]
    data = [[Paragraph(x, center) for x in headers]]
    for index, item in enumerate(items, 1):
        row = [index, _date(item.get("createdAt")), warehouse, code, item.get("sku", ""), item.get("productName", ""), _num(float(item.get("primaryQty", 0) or 0) * float(item.get("weight", 0) or 0)), _num(item.get("secondaryCount", 0)), _date(spraying.get("startDate")) if spraying else "-", _date(fumigasi.get("startDate")) if fumigasi else "-", item.get("note", ""), _arrangement(item)]
        data.append([Paragraph(str(x), center if i in {0, 1, 2, 3, 4, 6, 7, 8, 9} else small) for i, x in enumerate(row)])
    widths = [8, 18, 15, 20, 22, 50, 18, 16, 22, 22, 31, 52]
    table = LongTable(data, colWidths=[x * mm for x in widths], repeatRows=1)
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), SOFT_HEADER), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("GRID", (0, 0), (-1, -1), .35, colors.HexColor("#777777")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    story += [table, Spacer(1, 10 * mm), Table([["", Paragraph(f"Jakarta, {_date(operational_now().isoformat())}<br/><br/>Kepala Gudang Sunter Timur I &amp; II<br/><br/><br/><b>{warehouse_head}</b>", ParagraphStyle("sign", parent=small, alignment=TA_CENTER, fontSize=8, leading=14))]], colWidths=[190 * mm, 65 * mm])]
    story += [PageBreak(), Paragraph("RIWAYAT PERUBAHAN SUSUNAN", title)]
    hdata = [["WAKTU", "AKSI", "PRODUK", "PERHITUNGAN", "JUMLAH PRIMER", "PETUGAS"]]
    for entry in history:
        snap = entry.get("allocation", {})
        hdata.append([_date(entry.get("time"), True), entry.get("action", ""), snap.get("productName", ""), _arrangement(snap), _num(snap.get("primaryQty", 0)), entry.get("operator", "")])
    story.append(LongTable(hdata, colWidths=[32 * mm, 34 * mm, 70 * mm, 73 * mm, 30 * mm, 35 * mm], repeatRows=1, style=[("BACKGROUND", (0, 0), (-1, 0), SOFT_HEADER), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 7), ("GRID", (0, 0), (-1, -1), .35, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story += [Spacer(1, 7 * mm), Paragraph("RIWAYAT SPRAYING DAN FUMIGASI", title)]
    tdata = [["JENIS", "LOKASI", "MULAI", "SELESAI / BUKA SUNGKUP", "KOMODITAS BERAS", "CATATAN", "PETUGAS"]]
    for entry in treatments:
        tdata.append([entry.get("type", ""), entry.get("stackCode") or f"{entry.get('warehouse')} - Semua Tumpukan", _date(entry.get("startDate")), _date(entry.get("endDate")), ", ".join(x.get("name", "") for x in entry.get("products", [])), entry.get("note", ""), entry.get("operator", "")])
    story.append(LongTable(tdata, colWidths=[30 * mm, 38 * mm, 26 * mm, 40 * mm, 57 * mm, 50 * mm, 33 * mm], repeatRows=1, style=[("BACKGROUND", (0, 0), (-1, 0), SOFT_HEADER), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 7), ("GRID", (0, 0), (-1, -1), .35, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    doc.build(story, onFirstPage=_stack_page, onLaterPages=_stack_page)
    return _pdf_response(buffer, f"kartu_tumpukan_{code.replace('/', '-')}.pdf")


def _stack_page(c: canvas.Canvas, doc):
    c.saveState()
    if LOGO.exists(): c.drawImage(str(LOGO), 14 * mm, 188 * mm, width=32 * mm, height=14 * mm, preserveAspectRatio=True, mask="auto")
    c.setFont("Helvetica", 6); c.setFillColor(colors.grey)
    c.drawString(12 * mm, 6 * mm, f"Dicetak: {_date(operational_now().isoformat())}")
    c.drawRightString(285 * mm, 6 * mm, f"Halaman {doc.page}")
    c.restoreState()


def _draw_sj_copy(c: canvas.Canvas, sj: dict, x: float, y: float, width: float, warehouse_head: str):
    pad = 4 * mm; left = x + pad; right = x + width - pad
    if LOGO.exists(): c.drawImage(str(LOGO), left, y - 17 * mm, width=28 * mm, height=13 * mm, preserveAspectRatio=True, mask="auto")
    c.setFillColor(colors.HexColor("#244B63")); c.setFont("Helvetica-Bold", 7); c.drawString(left + 31 * mm, y - 20 * mm, "09001 - KANWIL DKI JAKARTA BANTEN")
    c.setStrokeColor(colors.HexColor("#527D96")); c.setLineWidth(1.2); c.line(left, y - 22 * mm, right, y - 22 * mm); c.setFillColor(colors.HexColor("#244B63")); c.setFont("Helvetica-Bold", 15); c.drawCentredString(x + width / 2, y - 28 * mm, "SURAT JALAN")
    c.setFillColor(colors.HexColor("#E7EFF3")); c.roundRect(left, y - 35 * mm, right-left, 5 * mm, 1.2 * mm, fill=1, stroke=0); c.setFillColor(colors.black)
    c.setFont("Helvetica", 9); c.drawCentredString(x + width / 2, y - 41 * mm, sj.get("ref") or sj.get("no", ""))
    cy = y - 47 * mm
    def box(label, value, height=13 * mm, label_width=27 * mm):
        nonlocal cy
        c.rect(left, cy-height, right-left, height); c.setFont("Helvetica", 7); c.drawString(left+2*mm, cy-4*mm, label); c.setFont("Helvetica-Bold", 6.5); c.drawString(left+label_width, cy-4*mm, str(value)[:80]); cy -= height + 2*mm
    box("Penerima", sj.get("penerima", "-"))
    location = " / ".join(dict.fromkeys(str(i.get("location", "")) for i in sj.get("items", []) if i.get("location"))) or sj.get("unit_loading", "-")
    box("Gudang Asal", f"KOMPLEKS GUDANG SUNTER TIMUR I & II | Unit: {location}")
    box("Dokumen Sumber", ", ".join(sj.get("documents") or [sj.get("ref", "-")]))
    row_h = 14 * mm
    c.setFillColor(colors.HexColor("#E7EFF3")); c.rect(left, cy-6*mm, right-left, 6*mm, fill=1, stroke=1); c.setFillColor(colors.black); c.setFont("Helvetica-Bold", 7); c.drawString(left+2*mm, cy-4*mm, "Produk"); c.drawRightString(right-2*mm, cy-4*mm, "Kuantitas / Kuantum"); cy -= 6*mm
    current_doc = ""
    for item in sj.get("items", [])[:7]:
        item_doc = item.get("documentNo", "")
        if item_doc and item_doc != current_doc:
            c.setFillColor(colors.HexColor("#F3F7F9")); c.rect(left, cy-5*mm, right-left, 5*mm, fill=1, stroke=1); c.setFillColor(colors.HexColor("#244B63")); c.setFont("Helvetica-Bold", 6.5); c.drawString(left+2*mm, cy-3.3*mm, f"Dokumen: {item_doc}"); c.setFillColor(colors.black); cy -= 5*mm; current_doc = item_doc
        c.rect(left, cy-row_h, right-left, row_h); c.setFont("Helvetica-Bold", 6.5); c.drawString(left+2*mm, cy-4*mm, str(item.get("name", ""))[:54]); c.setFont("Helvetica", 5.8); c.drawString(left+2*mm, cy-8*mm, f"SKU {item.get('sku','')} | Lokasi {item.get('location','-')}"); c.setFont("Helvetica-Bold", 7); c.drawRightString(right-2*mm, cy-5*mm, f"{_num(item.get('qty'))} {item.get('unit','')} | {_num(item.get('berat'))} Kg"); c.drawRightString(right-2*mm, cy-10*mm, item.get("sec", "")); cy -= row_h
    box("Nopol / Nama Sopir", f"{sj.get('polisi', '-')} / {sj.get('pengambil', '-')}", 10*mm, 35*mm)
    c.setFont("Helvetica", 7); c.drawCentredString(left+45*mm, cy-3*mm, "Pengangkut"); c.drawCentredString(right-45*mm, cy-3*mm, "Yang Menyerahkan,"); c.setFont("Helvetica-Bold", 6.5); c.drawCentredString(left+45*mm, cy-8*mm, sj.get("pengambil", "") or "-"); c.drawCentredString(right-45*mm, cy-8*mm, "KOMPLEKS GUDANG SUNTER TIMUR I & II"); c.line(left+25*mm, cy-28*mm, left+65*mm, cy-28*mm); c.drawCentredString(right-45*mm, cy-28*mm, warehouse_head)
    footer_y = 18 * mm; c.setStrokeColor(colors.HexColor("#527D96")); c.line(left, footer_y + 11*mm, right, footer_y + 11*mm); c.setFillColor(colors.HexColor("#244B63")); c.setFont("Helvetica-Bold", 8); c.drawString(left, footer_y + 5*mm, "Delivery Tracking"); c.setFillColor(colors.black); c.setFont("Helvetica", 5.8); c.drawString(left, footer_y, "Dicetak oleh: KOMPLEKS GUDANG SUNTER TIMUR I & II"); c.drawRightString(right, footer_y, f"Tanggal cetak: {_date(operational_now().isoformat(), True)}")


@router.get("/export/surat-jalan/{sj_id}.pdf")
async def export_surat_jalan_pdf(sj_id: str, user: dict = Depends(get_current_user)):
    sj = await db.surat_jalan.find_one({"id": sj_id}, {"_id": 0})
    if not sj: raise HTTPException(status_code=404, detail="Surat Jalan tidak ditemukan")
    settings = await db.settings.find_one({"_id": "app"}, {"_id": 0}) or {}
    warehouse_head = settings.get("warehouseHead") or "Irsa Maulian Nugraha"
    buffer = io.BytesIO(); c = canvas.Canvas(buffer, pagesize=landscape(A4)); w, h = landscape(A4)
    c.setDash(2, 2); c.line(w/2, 8*mm, w/2, h-8*mm); c.setDash()
    _draw_sj_copy(c, sj, 0, h, w/2, warehouse_head); _draw_sj_copy(c, sj, w/2, h, w/2, warehouse_head); c.save()
    return _pdf_response(buffer, f"surat_jalan_{(sj.get('ref') or sj.get('no','')).replace('/', '-')}.pdf")


@router.get("/export/bon-muat/{load_id}.pdf")
async def export_bon_muat_pdf(load_id: str, user: dict = Depends(get_current_user)):
    load = await db.outbound_loads.find_one({"id": load_id}, {"_id": 0})
    if not load: raise HTTPException(status_code=404, detail="Bon Muat tidak ditemukan")
    buffer = io.BytesIO(); width, height = 80*mm, 190*mm; c = canvas.Canvas(buffer, pagesize=(width, height)); mid = width/2
    if THERMAL_LOGO.exists(): c.drawImage(str(THERMAL_LOGO), (width-34*mm)/2, height-20*mm, width=34*mm, height=15*mm, preserveAspectRatio=True, mask="auto")
    y=height-26*mm; c.setFont("Helvetica-Bold", 10); c.drawCentredString(mid, y, "BON PEMUATAN"); y-=5*mm; c.setFont("Helvetica", 6.5); c.drawCentredString(mid, y, "GBB SUNTER TIMUR I & II"); y-=7*mm; c.setDash(2,2); c.line(4*mm,y,width-4*mm,y); c.setDash(); y-=6*mm
    c.setFont("Helvetica-Bold", 7); c.drawCentredString(mid,y,"NOMOR BON MUAT"); y-=5*mm; c.setFont("Helvetica-Bold", 10); c.drawCentredString(mid,y,load.get("bon_no","-")); y-=7*mm; c.setFont("Helvetica-Bold", 7); c.drawCentredString(mid,y,"NOMOR ANTRIAN"); y-=11*mm; c.setFont("Helvetica-Bold", 27); c.drawCentredString(mid,y,load.get("antrian","-")); y-=8*mm
    c.setDash(2,2); c.line(4*mm,y,width-4*mm,y); c.setDash(); y-=6*mm; c.setFont("Helvetica", 7)
    docs = ", ".join(load.get("documents") or [load.get("ref", "-")])
    fields=[("Tanggal",_date(load.get("started_at") or load.get("created_at"),True)),("Dokumen",f"{load.get('document_type','SO')} - {docs}"),("Tujuan",load.get("party","-")),("No. Polisi",load.get("polisi","-")),("Nama Sopir",load.get("pengambil","-")),("Pemuatan",load.get("unit_loading","-"))]
    for label,value in fields: c.setFont("Helvetica",6.5); c.drawString(5*mm,y,label); c.setFont("Helvetica-Bold",6.5); c.drawString(23*mm,y,str(value)[:45]); y-=5*mm
    y-=2*mm; c.setDash(2,2); c.line(4*mm,y,width-4*mm,y); c.setDash(); y-=6*mm; c.setFont("Helvetica-Bold",7); c.drawString(5*mm,y,"BARANG"); y-=5*mm
    for item in load.get("items",[]): c.setFont("Helvetica-Bold",6.5); c.drawString(5*mm,y,str(item.get("name",""))[:48]); y-=4*mm; c.setFont("Helvetica",6.5); c.drawString(7*mm,y,f"{_num(item.get('qty'))} {item.get('unit','')} | {_num(item.get('berat'))} Kg"); y-=6*mm
    c.setDash(2,2); c.line(4*mm,y,width-4*mm,y); c.setDash(); y-=7*mm; c.setFont("Helvetica-Bold",7); c.drawCentredString(mid,y,"Serahkan bon ini kepada petugas pemuatan"); y-=5*mm; c.setFont("Helvetica",6.5); c.drawCentredString(mid,y,"Terima kasih - GBB Sunter Timur I & II"); c.save()
    return _pdf_response(buffer, f"bon_pemuatan_{load.get('bon_no','')}.pdf")

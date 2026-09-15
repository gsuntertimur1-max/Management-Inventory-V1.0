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

from backend.server import JAKARTA_TZ, db, get_current_user, operational_now
from backend.consignment import DESTINATIONS, consignment_stock

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
        parsed = parsed.replace(tzinfo=JAKARTA_TZ) if parsed.tzinfo is None else parsed.astimezone(JAKARTA_TZ)
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


def _consignment_arrangement(layout: dict, item: dict) -> str:
    blocks = layout.get("arrangements", []) if layout else []
    parts = [f"{x.get('hamparan', 0)} X {x.get('kaki', 0)} X {x.get('height', 0)} = {_num(float(x.get('hamparan', 0)) * float(x.get('kaki', 0)) * float(x.get('height', 0)))}" for x in blocks]
    if layout and layout.get("extraSecondary"):
        parts.append(f"+ {_num(layout['extraSecondary'])} {item.get('secondary', '')} tambahan")
    if layout and layout.get("extraPrimary"):
        parts.append(f"+ {_num(layout['extraPrimary'])} {item.get('unit', '')} lepas")
    return " ; ".join(parts) if parts else "Belum dicatat"


@router.get("/export/consignment-stock-card.pdf")
async def export_consignment_stock_card_pdf(destination: str, user: dict = Depends(get_current_user)):
    location = destination.strip()
    if location not in DESTINATIONS:
        raise HTTPException(status_code=400, detail="Pilih Gudang Bazar atau Gudang E-commerce")
    items = await consignment_stock(location)
    if not items:
        raise HTTPException(status_code=404, detail="Belum ada stok konsinyasi aktif pada lokasi ini")
    layouts = await db.consignment_layouts.find({"destination": location}, {"_id": 0}).to_list(5000)
    by_product = {item.get("productId"): item for item in layouts}
    settings = await db.settings.find_one({"_id": "app"}, {"_id": 0}) or {}
    warehouse_head = settings.get("warehouseHead") or "Irsa Maulian Nugraha"
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm, topMargin=24 * mm, bottomMargin=11 * mm)
    styles = getSampleStyleSheet()
    title = ParagraphStyle("cons-title", parent=styles["Title"], alignment=TA_CENTER, fontName="Helvetica-Bold", fontSize=15, leading=18, spaceAfter=2)
    small = ParagraphStyle("cons-small", parent=styles["BodyText"], fontName="Helvetica", fontSize=6.5, leading=8)
    center = ParagraphStyle("cons-center", parent=small, alignment=TA_CENTER)
    short_location = "BAZAR" if location == "Gudang Bazar" else "E-COMMERCE"
    story = [Paragraph("K A R T U &nbsp; S T O K &nbsp; K O N S I N Y A S I", title), Paragraph(f"{short_location} - GBB Sunter Timur I &amp; II", ParagraphStyle("cons-sub", parent=title, fontSize=9, leading=12, spaceAfter=12)), Spacer(1, 5 * mm)]
    headers = ["NO", "SKU", "NAMA KOMODITI", "PERKALIAN", "KEMASAN SEKUNDER", "KUANTUM PACK/PCS", "KUANTUM BERAT", "DOKUMEN TERKAIT", "KETERANGAN"]
    data = [[Paragraph(header, center) for header in headers]]
    for index, item in enumerate(items, 1):
        layout = by_product.get(item.get("productId"), {})
        calculated = (sum(float(x.get("hamparan", 0)) * float(x.get("kaki", 0)) * float(x.get("height", 0)) for x in layout.get("arrangements", [])) + float(layout.get("extraSecondary", 0) or 0)) * float(item.get("secondaryQty", 0) or 0) + float(layout.get("extraPrimary", 0) or 0)
        unmatched = max(float(item.get("qty", 0)) - calculated, 0)
        arrangement = _consignment_arrangement(layout, item)
        if unmatched > 0:
            arrangement += f"<br/><font color='#9a6700'>Belum terhitung: {_num(unmatched)} {item.get('unit', '')}</font>"
        row = [index, item.get("sku", ""), item.get("name", ""), arrangement, item.get("secondary", "-") or "-", f"{_num(item.get('qty', 0))} {item.get('unit', '')}", f"{_num(item.get('totalWeight', 0))} kg" if item.get("weight") else "-", ", ".join(item.get("documents", [])) or "-", "ND atau Memo"]
        data.append([Paragraph(str(value), center if col in {0, 1, 4, 5, 6} else small) for col, value in enumerate(row)])
    widths = [8, 22, 48, 64, 28, 32, 30, 42, 42]
    table = LongTable(data, colWidths=[width * mm for width in widths], repeatRows=1)
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), SOFT_HEADER), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("GRID", (0, 0), (-1, -1), .35, colors.HexColor("#777777")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    history = await db.consignment_layout_history.find({"destination": location}, {"_id": 0}).sort("time", -1).to_list(5000)
    story += [table, Spacer(1, 8 * mm), Paragraph("RIWAYAT PERUBAHAN PERKALIAN", title)]
    history_data = [["WAKTU", "KOMODITI", "PERKALIAN TERBARU", "CATATAN", "PETUGAS"]]
    for entry in history:
        after = entry.get("after", {})
        product = next((item for item in items if item.get("productId") == entry.get("productId")), {})
        history_data.append([_date(entry.get("time"), True), product.get("name", entry.get("productId", "")), _consignment_arrangement(after, product), entry.get("note", ""), entry.get("operator", "")])
    story += [LongTable(history_data, colWidths=[34 * mm, 66 * mm, 86 * mm, 45 * mm, 38 * mm], repeatRows=1, style=[("BACKGROUND", (0, 0), (-1, 0), SOFT_HEADER), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 7), ("GRID", (0, 0), (-1, -1), .35, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]), Spacer(1, 10 * mm), Table([["", Paragraph(f"Jakarta, {_date(operational_now().isoformat())}<br/><br/>Kepala Gudang Sunter Timur I &amp; II<br/><br/><br/><b>{warehouse_head}</b>", ParagraphStyle("cons-sign", parent=small, alignment=TA_CENTER, fontSize=8, leading=14))]], colWidths=[190 * mm, 65 * mm])]
    doc.build(story, onFirstPage=_stack_page, onLaterPages=_stack_page)
    return _pdf_response(buffer, f"kartu_stok_konsinyasi_{short_location.lower()}.pdf")


@router.get("/export/products.pdf")
async def export_products_pdf(user: dict = Depends(get_current_user)):
    products = await db.products.find({}, {"_id": 0}).sort([("name", 1), ("sku", 1)]).to_list(10000)
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), leftMargin=10*mm, rightMargin=10*mm, topMargin=23*mm, bottomMargin=11*mm)
    styles = getSampleStyleSheet()
    title = ParagraphStyle("products-title", parent=styles["Title"], alignment=TA_CENTER, fontName="Helvetica-Bold", fontSize=14, leading=17, spaceAfter=3)
    small = ParagraphStyle("products-small", parent=styles["BodyText"], fontName="Helvetica", fontSize=6.5, leading=8)
    center = ParagraphStyle("products-center", parent=small, alignment=TA_CENTER)
    story = [Paragraph("DAFTAR INVENTORI PRODUK", title), Paragraph("GBB Sunter Timur I &amp; II", ParagraphStyle("products-sub", parent=title, fontSize=8.5, leading=11, spaceAfter=9))]
    headers = ["NO", "SKU", "NAMA KOMODITI", "KATEGORI", "SALURAN", "STOK BAIK", "RUSAK", "SATUAN", "BERAT / UNIT", "LOKASI"]
    data = [[Paragraph(header, center) for header in headers]]
    for index, item in enumerate(products, 1):
        row = [index, item.get("sku", ""), item.get("name", ""), item.get("category", "-") or "-", item.get("channel", "KOM") or "KOM", _num(item.get("stock", 0)), _num(item.get("damaged", 0)), item.get("unit", ""), f"{_num(item.get('weight', 0))} kg" if item.get("weight") else "-", item.get("location", "-") or "-"]
        data.append([Paragraph(str(value), center if col in {0,1,4,5,6,7,8} else small) for col, value in enumerate(row)])
    table = LongTable(data, colWidths=[8*mm,26*mm,65*mm,38*mm,19*mm,25*mm,20*mm,22*mm,27*mm,37*mm], repeatRows=1)
    table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),SOFT_HEADER),("TEXTCOLOR",(0,0),(-1,0),colors.white),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("GRID",(0,0),(-1,-1),.35,colors.HexColor("#777777")),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4)]))
    story.append(table)
    consignment_rows = []
    for destination in DESTINATIONS:
        consignment_rows.extend(await consignment_stock(destination))
    if consignment_rows:
        story += [PageBreak(), Paragraph("STOK KONSINYASI E-COMMERCE DAN BAZAR", title), Paragraph("Stok aktif berdasarkan pengeluaran Memo / Nota Dinas yang belum memiliki SO.", ParagraphStyle("products-cons-sub", parent=title, fontSize=8, leading=11, spaceAfter=9))]
        cons_headers = ["NO", "SKU", "NAMA KOMODITI", "SALURAN", "LOKASI", "KUANTUM PACK/PCS", "KUANTUM BERAT", "DOKUMEN ND/MEMO"]
        cons_data = [[Paragraph(header, center) for header in cons_headers]]
        for index, item in enumerate(consignment_rows, 1):
            row = [index, item.get("sku", ""), item.get("name", ""), item.get("channel", "KOM"), item.get("destination", ""), f"{_num(item.get('qty', 0))} {item.get('unit', '')}", f"{_num(item.get('totalWeight', 0))} kg" if item.get("weight") else "-", ", ".join(item.get("documents", [])) or "-"]
            cons_data.append([Paragraph(str(value), center if col in {0,1,3,4,5,6} else small) for col, value in enumerate(row)])
        cons_table = LongTable(cons_data, colWidths=[8*mm,28*mm,68*mm,20*mm,33*mm,35*mm,32*mm,48*mm], repeatRows=1)
        cons_table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),SOFT_HEADER),("TEXTCOLOR",(0,0),(-1,0),colors.white),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("GRID",(0,0),(-1,-1),.35,colors.HexColor("#777777")),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4)]))
        story.append(cons_table)
    doc.build(story, onFirstPage=_stack_page, onLaterPages=_stack_page)
    return _pdf_response(buffer, "daftar_inventori_produk.pdf")


@router.get("/export/warehouse-stack-cards.pdf")
async def export_warehouse_stack_cards_pdf(warehouse: str, user: dict = Depends(get_current_user)):
    warehouse_code = warehouse.strip().upper()
    allocations = await db.stack_allocations.find({"stackCode": {"$regex": f"^{warehouse_code}/"}}, {"_id": 0}).sort([("stackCode",1),("productName",1)]).to_list(5000)
    by_stack = {}
    for item in allocations:
        by_stack.setdefault(item.get("stackCode", ""), []).append(item)
    if not by_stack:
        raise HTTPException(status_code=404, detail="Belum ada komoditas pada tumpukan gudang ini")
    settings = await db.settings.find_one({"_id":"app"},{"_id":0}) or {}
    warehouse_head = settings.get("warehouseHead") or "Irsa Maulian Nugraha"
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), leftMargin=12*mm, rightMargin=12*mm, topMargin=24*mm, bottomMargin=11*mm)
    styles = getSampleStyleSheet()
    title = ParagraphStyle("warehouse-card-title", parent=styles["Title"], alignment=TA_CENTER, fontName="Helvetica-Bold", fontSize=15, leading=18, spaceAfter=2)
    small = ParagraphStyle("warehouse-card-small", parent=styles["BodyText"], fontName="Helvetica", fontSize=6.5, leading=8)
    center = ParagraphStyle("warehouse-card-center", parent=small, alignment=TA_CENTER)
    story = []
    cards = list(by_stack.items())
    for card_index, (stack_code, items) in enumerate(cards):
        treatments = await db.stack_treatments.find({"$or":[{"stackCode":stack_code},{"type":"SPRAYING","warehouse":warehouse_code}]},{"_id":0}).sort("startDate",-1).to_list(500)
        spraying = next((x for x in treatments if x.get("type") == "SPRAYING"), None)
        fumigasi = next((x for x in treatments if x.get("type") != "SPRAYING"), None)
        story += [Paragraph("K A R T U &nbsp; T U M P U K A N", title), Paragraph(f"GBB Sunter Timur I &amp; II · {warehouse_code} · {stack_code}", ParagraphStyle("warehouse-card-sub", parent=title, fontSize=9, leading=12, spaceAfter=12)), Spacer(1,5*mm)]
        headers=["NO","TANGGAL","SKU","NAMA PRODUK","KUANTUM","KOLLY","SPRAYING","FUMIGASI","KETERANGAN","PERHITUNGAN TUMPUKAN"]
        data=[[Paragraph(x,center) for x in headers]]
        for index,item in enumerate(items,1):
            row=[index,_date(item.get("createdAt")),item.get("sku",""),item.get("productName",""),_num(float(item.get("primaryQty",0) or 0)*float(item.get("weight",0) or 0)),_num(item.get("secondaryCount",0)),_date(spraying.get("startDate")) if spraying else "-",_date(fumigasi.get("startDate")) if fumigasi else "-",item.get("note",""),_arrangement(item)]
            data.append([Paragraph(str(value),center if col in {0,1,2,4,5,6,7} else small) for col,value in enumerate(row)])
        table=LongTable(data,colWidths=[8*mm,20*mm,25*mm,58*mm,20*mm,18*mm,24*mm,24*mm,42*mm,57*mm],repeatRows=1)
        table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),SOFT_HEADER),("TEXTCOLOR",(0,0),(-1,0),colors.white),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("GRID",(0,0),(-1,-1),.35,colors.HexColor("#777777")),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)]))
        story += [table, Spacer(1,10*mm), Table([["",Paragraph(f"Jakarta, {_date(operational_now().isoformat())}<br/><br/>Kepala Gudang Sunter Timur I &amp; II<br/><br/><br/><b>{warehouse_head}</b>",ParagraphStyle("warehouse-card-sign",parent=small,alignment=TA_CENTER,fontSize=8,leading=14))]],colWidths=[190*mm,65*mm])]
        if card_index < len(cards)-1: story.append(PageBreak())
    doc.build(story,onFirstPage=_stack_page,onLaterPages=_stack_page)
    return _pdf_response(buffer,f"kartu_tumpukan_{warehouse_code}.pdf")


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
    headers = ["NO", "TANGGAL", "GUDANG", "LOKASI", "SKU", "NAMA PRODUK", "KUANTUM", "KOLLY", "SPRAYING", "FUMIGASI", "KETERANGAN", "PERHITUNGAN TUMPUKAN"]
    data = [[Paragraph(x, center) for x in headers]]
    for index, item in enumerate(items, 1):
        row = [index, _date(item.get("createdAt")), warehouse, code, item.get("sku", ""), item.get("productName", ""), f"{_num(float(item.get('primaryQty', 0) or 0) * float(item.get('weight', 0) or 0))} {item.get('measureUnit', 'kg')}", _num(item.get("secondaryCount", 0)), _date(spraying.get("startDate")) if spraying else "-", _date(fumigasi.get("startDate")) if fumigasi else "-", item.get("note", ""), _arrangement(item)]
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
        c.rect(left, cy-row_h, right-left, row_h); c.setFont("Helvetica-Bold", 6.5); c.drawString(left+2*mm, cy-4*mm, str(item.get("name", ""))[:54]); c.setFont("Helvetica", 5.8); c.drawString(left+2*mm, cy-8*mm, f"SKU {item.get('sku','')} | Lokasi {item.get('location','-')}"); c.setFont("Helvetica-Bold", 7); c.drawRightString(right-2*mm, cy-5*mm, f"{_num(item.get('qty'))} {item.get('unit','')} | {_num(item.get('berat'))} {item.get('measureUnit','kg')}"); c.drawRightString(right-2*mm, cy-10*mm, item.get("sec", "")); cy -= row_h
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
    if not load:
        raise HTTPException(status_code=404, detail="Bon Muat tidak ditemukan")

    # Bon Muat adalah instruksi fisik pemuatan: gabungkan baris produk yang sama.
    # Riwayat pengeluaran dan Surat Jalan tetap memakai baris asli beserta dokumen sumbernya.
    grouped: dict[str, dict] = {}
    for item in load.get("items", []):
        key = item.get("productId") or f"{item.get('sku', '')}|{item.get('name', '')}"
        entry = grouped.setdefault(key, {**item, "qty": 0.0, "berat": 0.0})
        entry["qty"] += float(item.get("qty", 0) or 0)
        entry["berat"] += float(item.get("berat", 0) or 0)

    buffer = io.BytesIO()
    width = 80 * mm
    height = max(150 * mm, (124 + (len(grouped) * 13)) * mm)
    c = canvas.Canvas(buffer, pagesize=(width, height))
    mid = width / 2
    if THERMAL_LOGO.exists():
        c.drawImage(str(THERMAL_LOGO), (width - 34 * mm) / 2, height - 20 * mm, width=34 * mm, height=15 * mm, preserveAspectRatio=True, mask="auto")
    y = height - 26 * mm
    c.setFont("Helvetica-Bold", 10); c.drawCentredString(mid, y, "BON PEMUATAN")
    y -= 5 * mm; c.setFont("Helvetica", 6.5); c.drawCentredString(mid, y, "GBB SUNTER TIMUR I & II")
    y -= 7 * mm; c.setDash(2, 2); c.line(4 * mm, y, width - 4 * mm, y); c.setDash(); y -= 6 * mm
    c.setFont("Helvetica-Bold", 7); c.drawCentredString(mid, y, "NOMOR BON MUAT")
    y -= 5 * mm; c.setFont("Helvetica-Bold", 10); c.drawCentredString(mid, y, load.get("bon_no", "-"))
    y -= 7 * mm; c.setFont("Helvetica-Bold", 7); c.drawCentredString(mid, y, "NOMOR ANTRIAN")
    y -= 11 * mm; c.setFont("Helvetica-Bold", 27); c.drawCentredString(mid, y, load.get("antrian", "-"))
    y -= 8 * mm; c.setDash(2, 2); c.line(4 * mm, y, width - 4 * mm, y); c.setDash(); y -= 6 * mm
    docs = ", ".join(load.get("documents") or [load.get("ref", "-")])
    fields = [
        ("Tanggal", _date(load.get("started_at") or load.get("created_at"), True)),
        ("Dokumen", f"{load.get('document_type', 'SO')} - {docs}"),
        ("Tujuan", load.get("party", "-")),
        ("No. Polisi", load.get("polisi", "-")),
        ("Nama Sopir", load.get("pengambil", "-")),
        ("Pemuatan", load.get("unit_loading", "-")),
    ]
    for label, value in fields:
        c.setFont("Helvetica", 6.5); c.drawString(5 * mm, y, label)
        c.setFont("Helvetica-Bold", 6.5); c.drawString(23 * mm, y, str(value)[:45])
        y -= 5 * mm
    y -= 2 * mm; c.setDash(2, 2); c.line(4 * mm, y, width - 4 * mm, y); c.setDash(); y -= 6 * mm
    c.setFont("Helvetica-Bold", 7); c.drawString(5 * mm, y, "BARANG YANG DIMUAT"); y -= 5 * mm

    for item in grouped.values():
        qty = float(item.get("qty", 0) or 0)
        secondary_qty = float(item.get("secondaryQty", 0) or 0)
        secondary_name = item.get("secondary") or "kemasan sekunder"
        full_secondary = int(qty // secondary_qty) if secondary_qty else 0
        remaining_primary = qty - (full_secondary * secondary_qty) if secondary_qty else qty
        c.setFont("Helvetica-Bold", 6.7); c.drawString(5 * mm, y, str(item.get("name", ""))[:48]); y -= 4 * mm
        c.setFont("Helvetica", 6.2)
        c.drawString(7 * mm, y, f"Total: {_num(qty)} {item.get('unit', 'pcs')} | {_num(item.get('berat', 0))} {item.get('measureUnit', 'kg')}")
        y -= 4 * mm
        if secondary_qty:
            detail = f"Kemasan sekunder: {full_secondary} {secondary_name}"
            if remaining_primary > 1e-9:
                detail += f" | Sisa: {_num(remaining_primary)} {item.get('unit', 'pcs')}"
        else:
            detail = f"Kemasan sekunder: - | Per pcs: {_num(qty)} {item.get('unit', 'pcs')}"
        c.setFont("Helvetica-Bold", 6.2); c.drawString(7 * mm, y, detail[:72]); y -= 6 * mm

    c.setDash(2, 2); c.line(4 * mm, y, width - 4 * mm, y); c.setDash(); y -= 6 * mm
    c.setFont("Helvetica-Bold", 7); c.drawCentredString(mid, y, "Serahkan bon ini kepada petugas pemuatan")
    y -= 5 * mm; c.setFont("Helvetica", 6.5); c.drawCentredString(mid, y, "Terima kasih - GBB Sunter Timur I & II")
    c.save()
    return _pdf_response(buffer, f"bon_pemuatan_{load.get('bon_no', '')}.pdf")

def _weighing_form_pdf(title: str, document_no: str, party: str, polisi: str, created_at: str, entries: list[dict]) -> io.BytesIO:
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    left, right = 16 * mm, width - 16 * mm
    if LOGO.exists():
        c.drawImage(str(LOGO), left, height - 31 * mm, width=38 * mm, height=18 * mm, preserveAspectRatio=True, mask="auto")
    c.setFont("Helvetica-Bold", 15); c.drawCentredString(width / 2, height - 18 * mm, "FORM TIMBANGAN")
    c.setFont("Helvetica", 8); c.drawCentredString(width / 2, height - 24 * mm, title)
    y = height - 42 * mm
    c.setFillColor(colors.HexColor("#E7EFF3")); c.rect(left, y - 15 * mm, right - left, 15 * mm, fill=1, stroke=0); c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 7); c.drawString(left + 3 * mm, y - 5 * mm, "DOKUMEN"); c.drawString(left + 92 * mm, y - 5 * mm, "TANGGAL")
    c.setFont("Helvetica", 8); c.drawString(left + 3 * mm, y - 10 * mm, document_no or "-"); c.drawString(left + 92 * mm, y - 10 * mm, _date(created_at, True))
    y -= 23 * mm
    c.setFont("Helvetica-Bold", 7); c.drawString(left, y, "PENERIMA / PENGIRIM"); c.drawString(left + 92 * mm, y, "NO. POLISI")
    c.setFont("Helvetica", 8); c.drawString(left, y - 5 * mm, party or "-"); c.drawString(left + 92 * mm, y - 5 * mm, polisi or "-")
    y -= 15 * mm
    row_h = 8 * mm
    gap = 8 * mm
    half = (right - left - gap) / 2
    groups = [(left, entries[:10], 1), (left + half + gap, entries[10:20], 11)]
    for start_x, group_entries, first_no in groups:
        number_col = start_x + 18 * mm
        end_x = start_x + half
        c.setFillColor(SOFT_HEADER); c.rect(start_x, y - row_h, half, row_h, fill=1, stroke=1); c.setFillColor(colors.white); c.setFont("Helvetica-Bold", 8)
        c.drawCentredString((start_x + number_col) / 2, y - 5.2 * mm, "NO")
        c.drawCentredString((number_col + end_x) / 2, y - 5.2 * mm, "BRUTO (KG)")
        for index in range(10):
            entry = group_entries[index] if index < len(group_entries) else {"no": first_no + index, "gross": 0}
            row_y = y - row_h * (index + 2)
            c.setFillColor(colors.black); c.rect(start_x, row_y, half, row_h, fill=0, stroke=1); c.line(number_col, row_y + row_h, number_col, row_y)
            c.setFont("Helvetica", 8); c.drawCentredString((start_x + number_col) / 2, row_y + 2.8 * mm, str(entry.get("no", first_no + index)))
            c.drawCentredString((number_col + end_x) / 2, row_y + 2.8 * mm, _num(entry.get("gross", 0)))
    y -= row_h * 11
    sign_y = 39 * mm
    c.setFont("Helvetica", 8); c.drawCentredString(left + 42 * mm, sign_y + 20 * mm, "Pengangkut / Pengambil")
    c.drawCentredString(right - 42 * mm, sign_y + 20 * mm, "Petugas Gudang")
    c.line(left + 17 * mm, sign_y, left + 67 * mm, sign_y)
    c.line(right - 67 * mm, sign_y, right - 17 * mm, sign_y)
    c.drawRightString(right, 18 * mm, f"Dicetak: {_date(operational_now().isoformat(), True)}")
    c.save()
    return buffer


@router.get("/export/weighing-form/outbound/{load_id}.pdf")
async def export_outbound_weighing_form_pdf(load_id: str, user: dict = Depends(get_current_user)):
    load = await db.outbound_loads.find_one({"id": load_id}, {"_id": 0})
    if not load or not load.get("weighing_form"):
        raise HTTPException(status_code=404, detail="Form timbangan pengeluaran tidak tersedia")
    buffer = _weighing_form_pdf("PENGELUARAN BARANG", ", ".join(load.get("documents") or [load.get("ref", "-")]), load.get("party", ""), load.get("polisi", ""), load.get("created_at", ""), load.get("weighing_entries", []))
    return _pdf_response(buffer, f"form_timbangan_keluar_{load.get('antrian', load_id)}.pdf")


@router.get("/export/weighing-form/inbound/{operation_id}.pdf")
async def export_inbound_weighing_form_pdf(operation_id: str, user: dict = Depends(get_current_user)):
    transactions = await db.transactions.find({"operation_id": operation_id, "type": "MASUK"}, {"_id": 0}).to_list(100)
    if not transactions or not transactions[0].get("weighing_form"):
        raise HTTPException(status_code=404, detail="Form timbangan pemasukan tidak tersedia")
    first = transactions[0]
    buffer = _weighing_form_pdf("PEMASUKAN BARANG", first.get("ref", "-"), first.get("penerima", ""), first.get("polisi", ""), first.get("time", ""), first.get("weighing_entries", []))
    return _pdf_response(buffer, f"form_timbangan_masuk_{operation_id}.pdf")

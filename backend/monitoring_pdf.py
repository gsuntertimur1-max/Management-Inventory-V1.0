from __future__ import annotations

import io

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from backend.consignment import _ensure_destination_access, _scope_for_user, monitoring_stock
from backend.server import get_current_user, operational_now

router = APIRouter(prefix="/api")


def _fmt(value: float) -> str:
    number = float(value or 0)
    if abs(number - round(number)) < 1e-9:
        return f"{int(round(number)):,}".replace(",", ".")
    text = f"{number:,.3f}".rstrip("0").rstrip(".")
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


@router.get("/export/monitoring-stock.pdf")
async def export_monitoring_stock_pdf(user: dict = Depends(get_current_user)):
    scope = _scope_for_user(user)
    if scope:
        _ensure_destination_access(user, scope, write=False)

    rows = await monitoring_stock(scope, include_main=not bool(scope))
    now = operational_now()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=8 * mm,
        rightMargin=8 * mm,
        topMargin=9 * mm,
        bottomMargin=9 * mm,
        title="Monitoring Stok Seluruh Lokasi",
        author="PEPEG",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "MonitoringTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=17,
        alignment=TA_CENTER,
        spaceAfter=3 * mm,
    )
    meta_style = ParagraphStyle(
        "MonitoringMeta",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.5,
        leading=9,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#555555"),
        spaceAfter=4 * mm,
    )
    cell_style = ParagraphStyle(
        "MonitoringCell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=6.8,
        leading=8.2,
        alignment=TA_LEFT,
    )
    cell_center = ParagraphStyle(
        "MonitoringCellCenter",
        parent=cell_style,
        alignment=TA_CENTER,
    )

    story = [
        Paragraph("MONITORING STOK SELURUH LOKASI", title_style),
        Paragraph(
            f"PEPEG — Gudang Sunter Timur I & II &nbsp;&nbsp;|&nbsp;&nbsp; Dicetak {now.strftime('%d-%m-%Y %H:%M')} WIB",
            meta_style,
        ),
    ]

    headers = [
        "Saluran",
        "Lokasi",
        "SKU",
        "Nama Komoditi",
        "Pack/PCS",
        "Kuantum Fisik",
        "Rusak",
        "Dokumen Memo/ND",
    ]
    data = [[Paragraph(h, cell_center) for h in headers]]

    for row in rows:
        physical = "—"
        if float(row.get("weight", 0) or 0) > 0:
            physical = f"{_fmt(row.get('totalWeight', 0))} {row.get('measureUnit', 'kg') or 'kg'}"
        data.append([
            Paragraph(str(row.get("channel", "") or "—"), cell_center),
            Paragraph(str(row.get("location", "") or "—"), cell_style),
            Paragraph(str(row.get("sku", "") or "—"), cell_style),
            Paragraph(str(row.get("name", "") or "—"), cell_style),
            Paragraph(f"{_fmt(row.get('qty', 0))} {row.get('unit', '')}".strip(), cell_style),
            Paragraph(physical, cell_style),
            Paragraph(_fmt(row.get("damaged", 0)), cell_style),
            Paragraph(", ".join(row.get("documents", []) or []) or "—", cell_style),
        ])

    if not rows:
        data.append([Paragraph("Belum ada stok untuk ditampilkan.", cell_style)] + [""] * 7)

    table = Table(
        data,
        repeatRows=1,
        colWidths=[16 * mm, 31 * mm, 24 * mm, 67 * mm, 29 * mm, 31 * mm, 20 * mm, 55 * mm],
        hAlign="CENTER",
    )
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D9EAF7")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1F1F1F")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#AAB4C0")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F9FB")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))

    story.append(table)
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(
        f"Jumlah baris monitoring: {len(rows)}. Kuantum fisik mempertahankan satuan masing-masing komoditi (kg/liter/pcs).",
        ParagraphStyle(
            "MonitoringFooter",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=7,
            leading=9,
            textColor=colors.HexColor("#666666"),
        ),
    ))

    doc.build(story)
    buffer.seek(0)
    filename = f"monitoring_stok_seluruh_lokasi_{now.strftime('%Y%m%d_%H%M')}.pdf"
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

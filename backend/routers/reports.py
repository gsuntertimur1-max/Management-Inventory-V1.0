"""Excel report exports (openpyxl workbooks streamed as .xlsx downloads)."""
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from lib.db import db

router = APIRouter()

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

HEADER_FILL = PatternFill("solid", fgColor="1E293B")
HEADER_FONT = Font(color="FFFFFF", bold=True)
TITLE_FONT = Font(bold=True, size=14)


def _write_sheet(wb: Workbook, title: str, heading: str, headers: List[str], rows: List[List[Any]]) -> None:
    ws = wb.active if wb.sheetnames == ["Sheet"] else wb.create_sheet()
    ws.title = title

    ws.append([heading])
    ws["A1"].font = TITLE_FONT
    ws.append([f"Dicetak: {datetime.now(timezone.utc).strftime('%d-%m-%Y %H:%M')} UTC"])
    ws.append([])

    ws.append(headers)
    header_row = ws.max_row
    for col in range(1, len(headers) + 1):
        cell = ws.cell(row=header_row, column=col)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center")

    for row in rows:
        ws.append(row)

    widths = [len(str(h)) for h in headers]
    for row in rows:
        for i, value in enumerate(row):
            widths[i] = max(widths[i], min(len(str(value)), 48))
    for i, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = width + 4

    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)


def _stream(wb: Workbook, filename: str) -> StreamingResponse:
    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type=XLSX_MIME,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/reports/products.xlsx")
async def export_products():
    docs = await db.products.find().sort("name", 1).to_list(2000)
    rows: List[List[Any]] = []
    for p in docs:
        stock = int(p.get("current_stock", 0))
        buy = float(p.get("purchase_price", 0))
        rows.append([
            p.get("name", ""), p.get("sku", ""), p.get("category", ""), p.get("unit", ""),
            stock, buy, float(p.get("selling_price", 0)), buy * stock,
            p.get("supplier_name", ""), p.get("location", ""),
        ])
    total_value = sum(r[7] for r in rows)
    rows.append(["TOTAL", "", "", "", sum(int(r[4]) for r in rows), "", "", total_value, "", ""])

    wb = Workbook()
    _write_sheet(
        wb, "Daftar Produk", "Laporan Daftar Produk & Nilai Stok",
        ["Nama Produk", "SKU", "Kategori", "Satuan", "Stok", "Harga Modal (Rp)",
         "Harga Jual (Rp)", "Nilai Total (Rp)", "Supplier", "Lokasi"],
        rows,
    )
    return _stream(wb, f"laporan-produk-{datetime.now(timezone.utc).date().isoformat()}.xlsx")


@router.get("/reports/transactions.xlsx")
async def export_transactions(month: Optional[str] = Query(None, description="Filter bulan YYYY-MM")):
    query: Dict[str, Any] = {}
    if month:
        query["date"] = {"$regex": f"^{month}"}
    docs = await db.transactions.find(query).sort("created_at", -1).to_list(5000)

    rows: List[List[Any]] = []
    for t in docs:
        created = t.get("created_at")
        stamp = created.strftime("%d-%m-%Y %H:%M") if isinstance(created, datetime) else t.get("date", "")
        rows.append([
            stamp, t.get("reference_no", ""), t.get("queue_no", ""), t.get("type", ""),
            t.get("product_name", ""), t.get("product_sku", ""), t.get("category", ""),
            int(t.get("quantity", 0)), int(t.get("stock_after", 0)),
            t.get("party", ""), t.get("notes", ""),
        ])

    masuk = sum(r[7] for r in rows if r[3] == "MASUK")
    keluar = sum(r[7] for r in rows if r[3] == "KELUAR")
    rows.append([])
    rows.append(["RINGKASAN", "", "", "MASUK", "", "", "", masuk, "", "", ""])
    rows.append(["RINGKASAN", "", "", "KELUAR", "", "", "", keluar, "", "", ""])

    label = f"Bulan {month}" if month else "Semua Periode"
    wb = Workbook()
    _write_sheet(
        wb, "Riwayat Transaksi", f"Laporan Riwayat Transaksi Stok — {label}",
        ["Waktu", "No. Referensi", "No. Antrian", "Tipe", "Nama Produk", "SKU", "Kategori",
         "Jumlah", "Stok Akhir", "Pihak Terkait", "Catatan"],
        rows,
    )
    suffix = month or "semua"
    return _stream(wb, f"laporan-transaksi-{suffix}.xlsx")

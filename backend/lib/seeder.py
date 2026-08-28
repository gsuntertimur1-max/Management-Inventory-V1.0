"""Sample data for GudangPro. Reload with POST /api/seed or `python seed.py`."""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from lib.db import db
from models.inventory import Product, Supplier, Transaction
from models.shipment import Shipment, ShipmentItem

SUPPLIERS: List[Dict[str, str]] = [
    {"name": "PT Mega Nusantara Distribusi", "contact_person": "Budi Santoso", "phone": "0812-3456-7890",
     "email": "budi@meganusantara.co.id", "address": "Jl. Daan Mogot No. 45, Jakarta Barat",
     "category_supplied": "Elektronik & Gadget"},
    {"name": "CV Sumber Makmur Logistik", "contact_person": "Dewi Sartika", "phone": "0813-9876-5432",
     "email": "dewi@sumbermakmur.co.id", "address": "Jl. Rungkut Industri No. 12, Surabaya",
     "category_supplied": "Peralatan Kantor"},
    {"name": "PT Prima Perkasa Mandiri", "contact_person": "Hendra Wijaya", "phone": "0821-1122-3344",
     "email": "hendra@primaperkasa.co.id", "address": "Jl. Soekarno Hatta No. 300, Bandung",
     "category_supplied": "Hardware & Perkakas"},
    {"name": "PT Agro Indo Sejahtera", "contact_person": "Siti Nurhaliza", "phone": "0856-7788-9900",
     "email": "siti@agroindo.co.id", "address": "Jl. Pemuda No. 88, Semarang",
     "category_supplied": "F&B / Bahan Makanan"},
]

# (name, sku, category, unit, purchase, selling, stock, supplier_idx, location)
PRODUCTS: List[tuple] = [
    ("Laptop ThinkPad T14 Gen 4", "ELEC-TP-001", "Elektronik & Gadget", "Unit", 14500000, 17250000, 24, 0, "Rak A-01"),
    ("Monitor LED 24\" IPS", "ELEC-MON-024", "Elektronik & Gadget", "Unit", 1850000, 2350000, 46, 0, "Rak A-02"),
    ("Mouse Wireless Ergonomis", "ELEC-MSE-110", "Elektronik & Gadget", "Pcs", 145000, 219000, 180, 0, "Rak A-03"),
    ("Printer Laser Mono A4", "ELEC-PRN-A4", "Elektronik & Gadget", "Unit", 2450000, 2980000, 12, 0, "Rak A-04"),
    ("Kertas HVS A4 80gr", "OFF-PPR-A480", "Peralatan Kantor", "Box", 178000, 235000, 320, 1, "Rak B-01"),
    ("Pulpen Gel Hitam 0.5mm", "OFF-PEN-G05", "Peralatan Kantor", "Pack", 32000, 48000, 540, 1, "Rak B-02"),
    ("Filing Cabinet 4 Drawer", "OFF-CAB-4D", "Peralatan Kantor", "Unit", 1950000, 2450000, 8, 1, "Zona Barat"),
    ("Beras Premium Pandan Wangi", "FNB-RCE-25K", "F&B / Bahan Makanan", "Kg", 15500, 18900, 1250, 3, "Rak C-01"),
    ("Minyak Goreng Kemasan 2L", "FNB-OIL-2L", "F&B / Bahan Makanan", "Pcs", 34000, 41500, 410, 3, "Rak C-02"),
    ("Gula Kristal Putih", "FNB-SGR-50K", "F&B / Bahan Makanan", "Kg", 14200, 17500, 780, 3, "Rak C-03"),
    ("Kaos Polos Cotton Combed 30s", "APP-TSH-30S", "Pakaian & Tekstil", "Pcs", 42000, 79000, 260, 1, "Rak D-01"),
    ("Kain Katun Roll 50m", "APP-FAB-R50", "Pakaian & Tekstil", "Roll", 875000, 1150000, 18, 1, "Rak D-02"),
    ("Bor Listrik Impact 13mm", "HRD-DRL-13", "Hardware & Perkakas", "Unit", 685000, 899000, 34, 2, "Rak E-01"),
    ("Semen Portland 40kg", "HRD-CMT-40", "Hardware & Perkakas", "Pcs", 62000, 74500, 520, 2, "Zona Timur"),
    ("Kunci Set Tool Kit 108pcs", "HRD-TLK-108", "Hardware & Perkakas", "Set", 415000, 549000, 27, 2, "Rak E-02"),
]

# Inbound only: (product_idx, qty, reference, notes, days_ago)
INBOUND: List[tuple] = [
    (0, 30, "PO-2026-001", "Penerimaan batch awal kuartal", 26),
    (1, 60, "PO-2026-002", "Restock monitor", 24),
    (2, 200, "PO-2026-003", "Pembelian volume besar", 22),
    (4, 400, "PO-2026-004", "Stok kertas semester ini", 18),
    (5, 600, "PO-2026-005", "Pengadaan alat tulis", 17),
    (7, 1500, "PO-2026-006", "Panen mitra tani Semarang", 15),
    (8, 500, "PO-2026-007", "Batch minyak goreng", 13),
    (10, 300, "PO-2026-008", "Produksi konveksi mitra", 11),
    (12, 40, "PO-2026-009", "Perkakas baru", 8),
    (13, 600, "PO-2026-010", "Semen proyek besar", 6),
    (14, 30, "PO-2026-011", "Tool kit tambahan", 5),
]

# Outbound documents (surat jalan) — each may carry several product lines.
# (days_ago, party, external_ref, notes, status, [(product_idx, qty), ...])
OUTBOUND: List[tuple] = [
    (20, "PT Bank Sinar Mas", "REF-018", "Pengiriman perangkat kantor cabang", "SELESAI",
     [(0, 6), (1, 8), (2, 20)]),
    (12, "CV Digital Kreatif", "REF-019", "Penjualan grosir studio desain", "SELESAI",
     [(1, 6), (2, 10)]),
    (9, "Sekolah Tunas Bangsa", "REF-021", "Order pendidikan awal tahun", "SELESAI",
     [(4, 80), (5, 60)]),
    (6, "Warung Sembako Berkah", "REF-023", "Distribusi harian sembako", "SELESAI",
     [(7, 250), (8, 90), (9, 120)]),
    (4, "Distro Anak Muda", "REF-025", "Penjualan konsinyasi", "SELESAI",
     [(10, 40), (11, 2)]),
    (2, "PT Karya Griya", "REF-027", "Pengiriman proyek perumahan", "SELESAI",
     [(13, 80), (12, 4)]),
    (0, "Rumah Makan Selera", "REF-030", "Pesanan katering mingguan", "SELESAI",
     [(7, 60), (8, 24)]),
    (0, "Toko Bangunan Jaya Abadi", "REF-031", "Muat pagi — truk B 9021 XX", "DIMUAT",
     [(13, 120), (14, 3), (12, 2)]),
    (0, "Bengkel Motor Rapi", "REF-032", "Menunggu antrian dermaga 2", "MENUNGGU",
     [(14, 4), (12, 1)]),
    (0, "Kantor Notaris Amanah", "REF-033", "Alat tulis rutin bulanan", "MENUNGGU",
     [(5, 40), (4, 15)]),
]


ADMIN_NAME = "Administrator Gudang"
OPERATOR_NAME = "Operator Gudang Siang"


async def run_seed() -> Dict[str, int]:
    """Wipe and reload the demo dataset (settings are preserved)."""
    await db.products.delete_many({})
    await db.suppliers.delete_many({})
    await db.transactions.delete_many({})
    await db.purchase_orders.delete_many({})
    await db.shipments.delete_many({})

    suppliers = [Supplier(**s) for s in SUPPLIERS]
    await db.suppliers.insert_many([s.model_dump() for s in suppliers])

    products: List[Product] = []
    for name, sku, cat, unit, buy, sell, stock, sidx, loc in PRODUCTS:
        products.append(Product(
            name=name, sku=sku, category=cat, unit=unit, purchase_price=buy,
            selling_price=sell, current_stock=stock, supplier_id=suppliers[sidx].id,
            supplier_name=suppliers[sidx].name, location=loc,
        ))
    await db.products.insert_many([p.model_dump() for p in products])

    now = datetime.now(timezone.utc)
    stock: Dict[str, int] = {p.id: p.current_stock for p in products}
    txs: List[Dict[str, Any]] = []

    # --- inbound
    for pidx, qty, ref, notes, days_ago in INBOUND:
        p = products[pidx]
        stock[p.id] += qty
        moment = now - timedelta(days=days_ago)
        txs.append(Transaction(
            product_id=p.id, product_name=p.name, product_sku=p.sku, category=p.category,
            type="MASUK", quantity=qty, stock_after=stock[p.id], party=p.supplier_name,
            reference_no=ref, notes=notes, date=moment.date().isoformat(), created_at=moment,
            created_by_name=ADMIN_NAME,
        ).model_dump())

    # --- outbound documents (oldest first so numbering reads naturally)
    shipments: List[Dict[str, Any]] = []
    per_month: Dict[str, int] = {}
    per_day: Dict[str, int] = {}
    for days_ago, party, ref, notes, status, lines in sorted(OUTBOUND, key=lambda r: -r[0]):
        moment = now - timedelta(days=days_ago)
        day = moment.date().isoformat()
        month = moment.strftime("%Y%m")
        per_month[month] = per_month.get(month, 0) + 1
        per_day[day] = per_day.get(day, 0) + 1
        doc_no = f"SJ-{month}-{per_month[month]:03d}"
        queue_no = f"A-{per_day[day]:03d}"

        items: List[ShipmentItem] = []
        for pidx, qty in lines:
            p = products[pidx]
            stock[p.id] = max(stock[p.id] - qty, 0)
            items.append(ShipmentItem(
                product_id=p.id, product_name=p.name, product_sku=p.sku,
                unit=p.unit, quantity=qty, stock_after=stock[p.id],
            ))

        shipment = Shipment(
            doc_no=doc_no, queue_no=queue_no, party=party, reference_no=ref, notes=notes,
            date=day, items=items, total_quantity=sum(i.quantity for i in items),
            status=status, created_at=moment, created_by_name=OPERATOR_NAME,
        )
        shipments.append(shipment.model_dump())

        for item in items:
            product = next(p for p in products if p.id == item.product_id)
            txs.append(Transaction(
                product_id=item.product_id, product_name=item.product_name,
                product_sku=item.product_sku, category=product.category,
                type="KELUAR", quantity=item.quantity, stock_after=item.stock_after,
                party=party, reference_no=ref, queue_no=queue_no, shipment_id=shipment.id,
                notes=notes, date=day, created_at=moment, created_by_name=OPERATOR_NAME,
            ).model_dump())

    await db.transactions.insert_many(txs)
    await db.shipments.insert_many(shipments)

    for pid, qty in stock.items():
        await db.products.update_one({"id": pid}, {"$set": {"current_stock": qty}})

    return {
        "suppliers": len(suppliers),
        "products": len(products),
        "shipments": len(shipments),
        "transactions": len(txs),
    }

"""Idempotent-by-reset sample data for GudangPro."""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from lib.db import db
from models.inventory import Product, Supplier, Transaction

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

# (product_idx, type, qty, party, ref, notes, days_ago)
MOVEMENTS: List[tuple] = [
    (0, "MASUK", 30, None, "PO-2026-001", "Penerimaan batch awal kuartal", 26),
    (0, "KELUAR", 6, "PT Bank Sinar Mas", "SJ-2026-018", "Pengiriman unit kantor cabang", 20),
    (1, "MASUK", 60, None, "PO-2026-002", "Restock monitor", 24),
    (1, "KELUAR", 14, "CV Digital Kreatif", "SJ-2026-019", "Penjualan grosir", 12),
    (2, "MASUK", 200, None, "PO-2026-003", "Pembelian volume besar", 22),
    (2, "KELUAR", 20, "Toko Komputer Jaya", "SJ-2026-020", "Penjualan retail", 9),
    (4, "MASUK", 400, None, "PO-2026-004", "Stok kertas semester ini", 18),
    (4, "KELUAR", 80, "Sekolah Tunas Bangsa", "SJ-2026-021", "Order pendidikan", 7),
    (5, "MASUK", 600, None, "PO-2026-005", "Pengadaan alat tulis", 17),
    (5, "KELUAR", 60, "Kantor Notaris Amanah", "SJ-2026-022", "Order rutin bulanan", 5),
    (7, "MASUK", 1500, None, "PO-2026-006", "Panen mitra tani Semarang", 15),
    (7, "KELUAR", 250, "Warung Sembako Berkah", "SJ-2026-023", "Distribusi harian", 4),
    (8, "MASUK", 500, None, "PO-2026-007", "Batch minyak goreng", 13),
    (8, "KELUAR", 90, "Rumah Makan Selera", "SJ-2026-024", "Pesanan katering", 3),
    (10, "MASUK", 300, None, "PO-2026-008", "Produksi konveksi mitra", 11),
    (10, "KELUAR", 40, "Distro Anak Muda", "SJ-2026-025", "Penjualan konsinyasi", 2),
    (12, "MASUK", 40, None, "PO-2026-009", "Perkakas baru", 8),
    (12, "KELUAR", 6, "CV Bangun Kokoh", "SJ-2026-026", "Proyek renovasi", 1),
    (13, "MASUK", 600, None, "PO-2026-010", "Semen proyek besar", 6),
    (13, "KELUAR", 80, "PT Karya Griya", "SJ-2026-027", "Pengiriman proyek perumahan", 1),
    (14, "MASUK", 30, None, "PO-2026-011", "Tool kit tambahan", 5),
    (14, "KELUAR", 3, "Bengkel Motor Rapi", "SJ-2026-028", "Penjualan langsung", 0),
]


async def run_seed() -> Dict[str, int]:
    """Wipe and reload the demo dataset."""
    await db.products.delete_many({})
    await db.suppliers.delete_many({})
    await db.transactions.delete_many({})
    await db.purchase_orders.delete_many({})

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
    running: Dict[str, int] = {}
    queue_per_day: Dict[str, int] = {}
    txs: List[Dict[str, Any]] = []
    for pidx, mtype, qty, party, ref, notes, days_ago in MOVEMENTS:
        p = products[pidx]
        base = running.get(p.id, p.current_stock)
        after = base + qty if mtype == "MASUK" else max(base - qty, 0)
        running[p.id] = after
        moment = now - timedelta(days=days_ago)
        day = moment.date().isoformat()
        queue_no = ""
        if mtype == "KELUAR":
            queue_per_day[day] = queue_per_day.get(day, 0) + 1
            queue_no = f"A-{queue_per_day[day]:03d}"
        txs.append(Transaction(
            product_id=p.id, product_name=p.name, product_sku=p.sku, category=p.category,
            type=mtype, quantity=qty, stock_after=after,
            party=party or (p.supplier_name if mtype == "MASUK" else ""),
            reference_no=ref, queue_no=queue_no, notes=notes, date=day, created_at=moment,
        ).model_dump())
    await db.transactions.insert_many(txs)

    for pid, stock in running.items():
        await db.products.update_one({"id": pid}, {"$set": {"current_stock": stock}})

    return {"suppliers": len(suppliers), "products": len(products), "transactions": len(txs)}

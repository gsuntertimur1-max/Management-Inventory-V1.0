# GudangPro — Aplikasi Penyimpanan Stok

Inventory/warehouse stock app (Bahasa Indonesia UI). No auth — open access.

## Stack
FastAPI + MongoDB (motor) backend, Vite + React 19 + TS + Tailwind v4 frontend.
Dark-by-default theme, Plus Jakarta Sans + JetBrains Mono.

## Data model (backend/models/inventory.py)
- **Supplier**: id, name, contact_person, phone, email, address, category_supplied, created_at
- **Product**: id, name, sku (unique), category, unit, purchase_price, selling_price,
  current_stock, supplier_id, supplier_name, location, created_at
- **Transaction**: id, product_id, product_name, product_sku, category, type (MASUK|KELUAR),
  quantity, stock_after, party, reference_no, queue_no, notes, date (ISO date str), created_at
  - `queue_no` = daily queue number for outbound only, format `A-001`, resets each date
- **PurchaseOrder** (models/purchasing.py): id, po_number (PO-YYYYMM-###), supplier_id,
  supplier_name, status (MENUNGGU|DITERIMA|DIBATALKAN), items[POItem], total, notes,
  order_date, expected_date, received_at, created_at
- **POItem**: product_id, product_name, product_sku, unit, quantity, unit_price, subtotal
- **Settings**: company_name, address, phone, email, footer_note (single doc, id="app")

## API (all on api_router, prefix /api) — backend/routers/inventory.py
- GET/POST `/suppliers`, PUT/DELETE `/suppliers/{id}`
- GET/POST `/products`, GET/PUT/DELETE `/products/{id}` (409 on duplicate SKU)
- GET/POST `/transactions` — POST adjusts product.current_stock atomically;
  400 if KELUAR quantity > current stock
- GET `/stats` — total_products, total_units, total_valuation (modal × stok),
  recent_movements (30d units), by_category[], timeline[] (7 days masuk/keluar)
- GET `/transactions/by-ids?ids=a,b,c` — batch lookup for the print surfaces
- GET/POST `/purchase-orders`, GET `/purchase-orders/{id}`, DELETE
  - POST `/purchase-orders/{id}/receive` → creates MASUK transactions + bumps stock, status DITERIMA
  - POST `/purchase-orders/{id}/cancel` → status DIBATALKAN (blocked once received)
- GET/PUT `/settings` — company header used on printed documents
- GET `/reports/products.xlsx`, GET `/reports/transactions.xlsx?month=YYYY-MM` — openpyxl downloads
- POST `/seed` — wipes and reloads demo dataset

## Pages (frontend/src/pages)
- `/` Dashboard — 4 KPI cards, 7-day area chart, stock-by-category bar chart, recent activity
- `/products` Products — table + search + category filter, create/edit/delete dialog
- `/stock-movement` Catat Stok — MASUK/KELUAR toggle, product select, qty, party, ref, notes + live preview
- `/transactions` Riwayat — table + search + type/range/category filters, totals
- `/purchase-orders` Purchase Order — buat PO multi-item ke supplier, tombol "Barang Datang"
  mengubah PO jadi transaksi MASUK otomatis; tombol batalkan
- `/settings` Pengaturan — nama/alamat/telepon/email + catatan kaki, dipakai sebagai kop cetak
- `/print/surat-jalan?ids=a,b,c` — surat jalan A4 portrait, **2 surat jalan per lembar**
  (setiap nota 148.5mm), tombol Cetak memanggil window.print()
- `/print/bon-muat/:id` — bon muat thermal 80mm dengan **nomor antrian** besar
- Ekspor Excel: tombol di halaman Produk dan Riwayat (per bulan / semua periode)

## Seed facts (backend/lib/seeder.py, `python seed.py` or POST /api/seed)
Wipes products/suppliers/transactions/purchase_orders (settings persist), then loads
4 suppliers, 15 products, 22 transactions (outbound ones carry queue_no). Sample SKUs: ELEC-TP-001, OFF-PPR-A480,
FNB-RCE-25K, HRD-CMT-40. Suppliers include "PT Mega Nusantara Distribusi".

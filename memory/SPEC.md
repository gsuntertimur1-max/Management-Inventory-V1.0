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
  quantity, stock_after, party, reference_no, notes, date (ISO date str), created_at

## API (all on api_router, prefix /api) — backend/routers/inventory.py
- GET/POST `/suppliers`, PUT/DELETE `/suppliers/{id}`
- GET/POST `/products`, GET/PUT/DELETE `/products/{id}` (409 on duplicate SKU)
- GET/POST `/transactions` — POST adjusts product.current_stock atomically;
  400 if KELUAR quantity > current stock
- GET `/stats` — total_products, total_units, total_valuation (modal × stok),
  recent_movements (30d units), by_category[], timeline[] (7 days masuk/keluar)
- POST `/seed` — wipes and reloads demo dataset

## Pages (frontend/src/pages)
- `/` Dashboard — 4 KPI cards, 7-day area chart, stock-by-category bar chart, recent activity
- `/products` Products — table + search + category filter, create/edit/delete dialog
- `/stock-movement` Catat Stok — MASUK/KELUAR toggle, product select, qty, party, ref, notes + live preview
- `/transactions` Riwayat — table + search + type/range/category filters, totals
- `/suppliers` Supplier — card grid CRUD, product-count per supplier

## Seed facts (backend/lib/seeder.py, `python seed.py` or POST /api/seed)
4 suppliers, 15 products, 22 transactions. Sample SKUs: ELEC-TP-001, OFF-PPR-A480,
FNB-RCE-25K, HRD-CMT-40. Suppliers include "PT Mega Nusantara Distribusi".

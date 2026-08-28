# Bulog Gudang Sunter Timur I & II — Aplikasi Penyimpanan Stok

## Lokasi gudang & tumpukan (backend/models/locations.py, routers/locations.py)
- 2 kompleks: **Gudang Sunter Timur I** (GBB 17–20) dan **Gudang Sunter Timur II**
  (GBB 21–24 + **MP 1**, hanya ada di kompleks II).
- Tiap unit GBB = 12 tumpukan (A/B/C × 01..04: A01.1.1, A02.1.1, A03.1.1, A04.1.1, dst).
  **MP 1 = 16 tumpukan** (A/B × 01..08). Total katalog 112 tumpukan, kode gabungan
  `GBB 23/A01.1.1`. `_normalise_stack_names()` merapikan nama lama berakhiran `.1.1.1` → `.1.1`
  (ikut memperbarui `location_code` di placements).
- Katalog di-seed startup (`ensure_locations`) ke `db.locations`; admin/pengadaan bisa
  POST `/locations` (tambah tumpukan) & DELETE `/locations/{id}` (harus kosong).
- **Placement** (`db.placements`): satu tumpukan boleh berisi banyak komoditas.
  Field: location_code, product_id, length(P)/width(L)/height(T), notes + turunan
  server-side: complex_name, unit_name, stack, product_name/sku, unit, secondary_unit,
  units_per_secondary, weight_per_unit/weight_unit, secondary_count = P×L×T,
  weight_per_secondary = weight_per_unit × units_per_secondary,
  total_units = P×L×T × units_per_secondary, total_weight, created_by_name.
- API: GET `/locations`, GET `/locations/summary`, GET `/placements` (stock:read);
  POST/PUT/DELETE `/placements` + POST `/placements/distribute` (procurement:write —
  menyebar seluruh stok produk saat ini ke tumpukan, memfaktorkan jumlah kemasan jadi P×L×T).
- Excel: GET `/reports/stock-locations.xlsx` — rekap per tumpukan + kolom P, L, T dan
  perkalian tumpukan (P×L×T), total satuan, total berat.
- Halaman `/lokasi` (`pages/StockLocations.tsx`, nav "Tumpukan Stok", stock:read; tombol
  tulis hanya untuk admin/pengadaan, viewer & penjualan read-only).

Inventory/warehouse stock app (Bahasa Indonesia UI). **Login required** (username + password).

## Kondisi barang, EXP date & logo
- **Product** menyimpan `current_stock` (= stok kondisi BAIK), `damaged_stock` (kondisi RUSAK) dan
  `expiry_date` (EXP, `YYYY-MM-DD`, opsional). Keduanya bisa diisi di dialog produk `/products`
  dan tampil sebagai kolom "Stok Baik / Stok Rusak / Tanggal EXP" di halaman Produk + Dashboard.
- **Transaction** punya `condition: BAIK|RUSAK`. POST `/transactions` menambah/mengurangi pool
  yang sesuai (`current_stock` untuk BAIK, `damaged_stock` untuk RUSAK) dan menolak 400 bila
  pool tidak cukup. Form `/stock-movement` punya pemilih "Kondisi Barang".
- Pengeluaran surat jalan (`/shipments`) **selalu** dari stok BAIK; `ShipmentItem` membawa
  `condition` + `expiry_date` (disalin dari produk saat pembuatan) untuk dicetak.
- `Stats.total_damaged` → KPI "Stok Rusak (Damage)" di dashboard.
- Excel: `products.xlsx` punya kolom Stok Baik, Stok Rusak, Tanggal EXP; `transactions.xlsx`
  punya kolom Kondisi Barang + No. Polisi Kendaraan.
- Logo: `frontend/public/logo-bulog.png` dipakai di header AppShell, halaman Login,
  kop surat jalan A4, dan bon muat thermal.

## Nomor plat kendaraan
`vehicle_plate` (otomatis di-UPPERCASE server-side) ada pada **Transaction** (stok masuk &
keluar), **ShipmentCreate/Shipment** (surat jalan), dan opsional pada body POST
`/purchase-orders/{id}/receive`. Diisi di form `/stock-movement` ("Nomor Plat Kendaraan",
berlaku untuk MASUK maupun KELUAR), lalu tampil di surat jalan A4, bon muat thermal
("No. Pol"), kolom "No. Polisi" pada Riwayat & Pengeluaran, dan kolom
"No. Polisi Kendaraan" di `reports/transactions.xlsx`.

## Auth & roles (RBAC only — single shared warehouse, no tenancy)
Roles: **admin** (everything), **penjualan** (outbound only: sales:read/write + inventory:read +
reports), **pengadaan** (procurement only: procurement:read/write + inventory:read + reports),
**viewer** (stock:read + sales:read, read-only, money masked). Legacy `operator` accounts are
auto-migrated to `penjualan` at startup (`migrate_legacy_roles`).

Actions: stock:read, sales:read, sales:write, procurement:read, procurement:write, inventory:read,
reports:read, settings:write, users:manage, data:reset. Frontend `can()` supports `"a|b"` = either.
- Sessions are httpOnly cookies (`gp_session`, 7 days) stored in `db.sessions`; role is re-read
  from `db.users` on every request, never trusted from the cookie.
- `api_router` carries a single `Depends(enforce)` gate (`lib/auth.py`) driven by a
  (method, path) → action table + `PERMISSIONS`; an unlisted path is **denied by default**.
  401 = not logged in, 403 = logged in but not permitted.
- Roles: **admin** (all incl. `settings:write`, `users:manage`, `data:reset`),
  **operator** (`stock:read`, `inventory:read/write`, `reports:read`), **viewer** (`stock:read` only).
- Viewer money masking is server-side: `purchase_price`/`selling_price` → 0 on products and
  `total_valuation` → 0 on `/stats`. The frontend also hides those columns/KPIs.
- Auth API: POST `/auth/login`, POST `/auth/logout`, GET `/auth/me` (public);
  GET/POST `/auth/users`, PATCH/DELETE `/auth/users/{id}` (admin only). Guards: at least one
  admin must remain; no self-demote/self-delete; password change kills that user's sessions.
- Credentials live in `memory/test_credentials.md` (admin/admin123, operator1/operator123,
  viewer1/viewer123). `ensure_default_admin()` runs on every startup and recreates the `admin`
  account **whenever that username is missing** (checked by username, NOT by "collection is
  empty" — the old emptiness check caused a real lockout once the user added their own admin and
  deleted the default one). Pod-side recovery: `python reset_password.py <username> <new_password>`.
- Frontend: `lib/session.ts` (`useAuth`, `useSession`, `can`), `components/RequireAuth.tsx`
  gates every route by action; `/login` is the only public page.

## Stack
FastAPI + MongoDB (motor) backend, Vite + React 19 + TS + Tailwind v4 frontend.
Dark-by-default theme, Plus Jakarta Sans + JetBrains Mono.

## Data model (backend/models/inventory.py)
- **Supplier**: id, name, contact_person, phone, email, address, category_supplied, created_at
- **Product**: id, name, sku (unique), category, unit, purchase_price, selling_price,
  current_stock, supplier_id, supplier_name, location, created_at
- **Transaction**: id, product_id, product_name, product_sku, category, type (MASUK|KELUAR),
  quantity, stock_after, party, reference_no, queue_no, shipment_id, created_by,
  created_by_name, notes, date, created_at
  - `created_by`/`created_by_name` = the logged-in user who recorded it (stamped server-side from
    the session, never from the request body); seeded rows show "Administrator Gudang" /
    "Operator Gudang Siang". Shown as the "Dicatat Oleh" column in Riwayat, Pengeluaran, and the
    transactions Excel export.
  - outbound transactions are always children of a Shipment (`shipment_id` set)
- **Shipment** (models/shipment.py) = one outbound document / surat jalan, MULTI-ITEM:
  id, doc_no (SJ-YYYYMM-###), queue_no (A-001, reset per date), party, reference_no, notes,
  date, items[ShipmentItem], total_quantity, status (MENUNGGU|DIMUAT|SELESAI), created_at
- **ShipmentItem**: product_id, product_name, product_sku, unit, quantity, stock_after
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
- POST `/products/import` — bulk create/update by SKU. Body {mode: "add"|"replace",
  supplier_id?, items:[{sku, name, quantity, category?, unit?, purchase_price?, selling_price?,
  supplier_name?, location?}]}. Unknown supplier_name is auto-created; writes a MASUK/KELUAR
  adjustment transaction (ref `IMPORT-DATA`) for every stock change. Returns
  {created, updated, units_added, suppliers_created, errors[]}
- GET `/transactions/by-ids?ids=a,b,c` — batch lookup
- POST `/shipments` — multi-item outbound: validates stock for every line, assigns doc_no +
  queue_no, writes one KELUAR transaction per line, drops stock
- GET `/shipments`, GET `/shipments/queue` (status != SELESAI, oldest first — drives the queue
  screen), GET `/shipments/by-ids?ids=`, GET `/shipments/{id}`,
  PATCH `/shipments/{id}/status` {status}
- GET/POST `/purchase-orders`, GET `/purchase-orders/{id}`, DELETE
  - POST `/purchase-orders/{id}/receive` → creates MASUK transactions + bumps stock, status DITERIMA
  - POST `/purchase-orders/{id}/cancel` → status DIBATALKAN (blocked once received)
- GET/PUT `/settings` — company header used on printed documents
- GET `/reports/products.xlsx`, GET `/reports/transactions.xlsx?month=YYYY-MM` — openpyxl downloads
- POST `/seed` — wipes and reloads demo dataset

## Pages (frontend/src/pages)
- `/` Dashboard — 4 KPI cards, **tabel "Sisa Stok per Barang (A → Z)"** (urut abjad, ada
  pencarian), 7-day area chart, stock-by-category bar chart, recent activity
- `/import` Import Data SKU — tempel CSV / unggah berkas, template CSV bisa diunduh, mode
  "tambahkan" vs "ganti stok", supplier bawaan opsional, pratinjau baris sebelum simpan
- `/products` Products — table + search + category filter, create/edit/delete dialog
- `/stock-movement` Catat Stok — MASUK/KELUAR toggle, product select, qty, party, ref, notes + live preview
- `/transactions` Riwayat — table + search + type/range/category filters, totals
- `/purchase-orders` Purchase Order — buat PO multi-item ke supplier, tombol "Barang Datang"
  mengubah PO jadi transaksi MASUK otomatis; tombol batalkan
- `/settings` Pengaturan — nama/alamat/telepon/email + catatan kaki, dipakai sebagai kop cetak
- `/shipments` Pengeluaran & Surat Jalan — daftar shipment multi-item, filter status, pilih
  beberapa untuk cetak, tombol Mulai Muat / Selesai, cetak surat jalan & bon muat per baris
- `/antrian` Layar Antrian Gudang — display untuk sopir, polling `/shipments/queue` tiap 5s:
  panel besar "Sedang Dimuat" + daftar "Menunggu Antrian" + jam berjalan
- `/print/surat-jalan?ids=a,b,c` — **ids = shipment ids**. Tiap shipment = 1 lembar A4 berisi
  **2 rangkap surat jalan yang sama** (Rangkap 1 penerima, Rangkap 2 arsip gudang), tabel
  multi-item, tanda tangan hanya Pengirim & Penerima (TANPA tanda tangan driver/pengemudi)
- `/print/bon-muat/:id` — id = shipment id; bon muat thermal 80mm, nomor antrian besar,
  daftar semua item + total muat
- Ekspor Excel: tombol di halaman Produk dan Riwayat (per bulan / semua periode)

## Seed facts (backend/lib/seeder.py, `python seed.py` or POST /api/seed)
Wipes products/suppliers/transactions/purchase_orders (settings persist), then loads
4 suppliers, 15 products, 22 transactions (outbound ones carry queue_no). Sample SKUs: ELEC-TP-001, OFF-PPR-A480,
FNB-RCE-25K, HRD-CMT-40. Suppliers include "PT Mega Nusantara Distribusi".

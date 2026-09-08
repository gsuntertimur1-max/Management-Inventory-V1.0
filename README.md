# Management Inventory BULOG

Aplikasi inventaris Gudang Sunter Timur I & II dengan frontend React, backend FastAPI, dan MongoDB. Repository ini telah disesuaikan dengan fitur pada `Emergent-Inventory` tanpa mengubah repository sumber tersebut.

## Fitur

- Dashboard persediaan
- Daftar dan impor produk
- Stok baik/rusak serta tumpukan stok
- Barang masuk dan keluar
- Riwayat transaksi dan surat jalan
- Purchase order dan supplier
- Antrean pengeluaran
- Manajemen pengguna berbasis peran

## Menjalankan secara lokal

1. Salin `backend/.env.example` menjadi `backend/.env`, lalu isi konfigurasi MongoDB, JWT, dan administrator.
2. Jalankan backend:

   ```bash
   cd backend
   python -m pip install -r requirements.txt
   uvicorn server:app --host 0.0.0.0 --port 8001 --reload
   ```

3. Di terminal lain, jalankan frontend:

   ```bash
   cd frontend
   yarn install
   yarn start
   ```

Frontend lokal mem-proxy `/api` ke `http://localhost:8001`. Backend lokal sendiri mengekspos route tanpa prefix karena Vercel Services memasang layanan tersebut pada `/api` ketika deployment.

## Deployment Vercel

1. Import repository ini sebagai project Vercel.
2. Pada **Project Settings → Build & Deployment**, pilih Framework Preset **Services**.
3. Tambahkan environment variables berikut untuk Preview dan Production:

   - `MONGO_URL`
   - `DB_NAME`
   - `JWT_SECRET`
   - `ADMIN_USERNAME`
   - `ADMIN_PASSWORD` (minimal 8 karakter, diperlukan saat admin pertama dibuat)
   - `ADMIN_EMAIL` (opsional)
   - `CORS_ORIGINS` (opsional untuk domain lain; tidak dibutuhkan pada satu domain)

4. Deploy ulang. Konfigurasi `vercel.json` membangun frontend pada `/` dan FastAPI pada `/api`.

Login Google lama tidak diaktifkan karena bergantung pada layanan Emergent. Login username/password berjalan mandiri. Endpoint kompatibilitas Google hanya aktif bila `GOOGLE_SESSION_URL` sengaja dikonfigurasi.

## Keamanan dan data

- `.env` tidak boleh di-commit. Gunakan environment variables di Vercel.
- `backend/seed_data.csv` hanya berisi header agar data stok/pemasok tidak dipublikasikan.
- Gunakan database uji yang terpisah saat verifikasi. Kode ini tidak memigrasikan atau menghapus database aktif secara otomatis.
- Bila secret pernah masuk ke riwayat Git repository publik, ganti/rotasi secret tersebut sebelum deployment.

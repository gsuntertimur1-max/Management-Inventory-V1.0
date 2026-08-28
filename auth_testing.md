# Auth-Gated App Testing Playbook (Emergent Google Auth)

Aplikasi memakai DUA jalur autentikasi yang berbagi satu koleksi sesi (`db.sessions`):
1. Password login lama: `POST /api/auth/login` → cookie httpOnly `gp_session`.
2. Emergent Google Auth: `POST /api/auth/google/session` (body `{session_id}` atau header
   `X-Session-ID`) → cookie `session_token` **dan** `gp_session` (nilai sama).

`enforce()` menerima token dari cookie `gp_session`, cookie `session_token`, atau header
`Authorization: Bearer <token>`. Peran RBAC (admin | penjualan | pengadaan | viewer) selalu
dibaca ulang dari `db.users` pada tiap request.

## Step 1: Buat user + sesi uji
```bash
mongosh --eval "
use('test_database');
var uid = 'test-user-' + Date.now();
var token = 'test_session_' + Date.now();
db.users.insertOne({
  id: uid, username: 'tester-' + Date.now(), full_name: 'Tester Google',
  role: 'admin', email: 'tester' + Date.now() + '@example.com', picture: '',
  auth_provider: 'google', password_hash: '', salt: '', created_at: new Date()
});
db.sessions.insertOne({
  token: token, user_id: uid,
  expires_at: new Date(Date.now() + 7*24*60*60*1000)
});
print('token: ' + token); print('user id: ' + uid);
"
```
Catatan: koleksi user memakai field `id` (UUID buatan sendiri) dan seluruh query
mengecualikan `_id`.

## Step 2: Uji API
```bash
curl -s https://<host>/api/auth/me -H "Authorization: Bearer <TOKEN>"
curl -s https://<host>/api/products -H "Authorization: Bearer <TOKEN>"
curl -s -b "session_token=<TOKEN>" https://<host>/api/stats
```

## Step 3: Uji browser
```js
await context.addCookies([{ name: 'session_token', value: '<TOKEN>', domain: '<host>',
  path: '/', httpOnly: true, secure: true, sameSite: 'None' }]);
await page.goto('https://<host>/');
```

## Checklist
- Tombol "Masuk dengan Google" di `/login` mengarah ke `auth.emergentagent.com` dengan
  `redirect = window.location.origin + '/'` (tidak boleh di-hardcode).
- `App.tsx` mendeteksi `useLocation().hash` berisi `session_id=` dan merender `AuthCallback`
  SEBELUM route/RequireAuth berjalan.
- Email pemilik `gsuntertimur1@gmail.com` selalu mendapat peran `admin`; akun Google lain
  dibuat sebagai `viewer`.
- Logout menghapus sesi DB dan kedua cookie.

## Bersihkan data uji
```bash
mongosh --eval "use('test_database'); db.users.deleteMany({email:/@example.com/}); db.sessions.deleteMany({token:/test_session/});"
```

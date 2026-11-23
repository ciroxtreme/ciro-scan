# ciro-scan 🐷🔍
Adaptive Security Scanner & Codebase Audit Pipeline powered by TruffleHog, Telegram Bot, & GitHub Actions.

## Fitur
- **Bot Telegram Real-Time (Pterodactyl Node.js Egg):** Berjalan sebagai daemon 24/7 di server Pterodactyl Node.js (`npm install && npm start`) tanpa antrean GitHub Actions.
- **Engine TruffleHog v3:** Menggunakan engine resmi **TruffleHog v3** dengan fitur *Live Verification* untuk memvalidasi kredensial konfigurasi aktif.
- **Pengiriman Hasil Instan:** Laporan ringkas dan dokumen `findings_active.json` / `findings_potential.json` langsung dikirim otomatis ke chat Telegram Tuan Ciro.
- **Pencarian teks bebas (`-bebas`):** Kirim `<url repo/akun> -bebas <kata>` ke bot untuk mencari string apa saja di seluruh riwayat commit tanpa scan TruffleHog.
- **Mode feed global (`/feed`):** Memindai repositori dari pengguna aktif publik GitHub terkini secara otomatis.
- **Mode dork global (`/dork`):** Mencari pola file konfigurasi via GitHub Code Search.
- **Arsitektur Task Queue:** Menerima banyak target sekaligus secara non-blocking; target berikutnya dimasukkan ke antrean otomatis.

---

## 🚀 Panduan Menjalankan di Server Pterodactyl Node.js

### 1. Persiapan File
Di server Pterodactyl baru, cukup jalankan:
```bash
git clone https://github.com/ciroxtreme/ciro-scan.git .
```
*(Atau unggah & ekstrak berkas `ciro-scan-vps.zip` ke server).*

### 2. Konfigurasi (.env)
Salin file `.env.example` menjadi `.env` jika belum ada:
```bash
cp .env.example .env
```
*(Jika menggunakan `ciro-scan-vps.zip`, file `.env` sudah otomatis terpasang token bot & ID Tuan Ciro).*

### 3. Jalankan di Pterodactyl Console
Di terminal / console Pterodactyl:
```bash
npm install
npm start
```
*(Atau cukup tekan tombol **Start** di Console panel — Startup Command default Pterodactyl Node.js adalah `npm start` atau `node startup.js`).*

Script `startup.js` akan otomatis:
1. Memeriksa & mengunduh biner resmi TruffleHog ke `./bin/trufflehog` jika belum ada.
2. Memeriksa & menginstal dependensi Python (`requests`).
3. Menjalankan daemon bot Telegram secara real-time.

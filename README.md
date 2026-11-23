# ciro-scan 🐷🔍
Adaptive Security Scanner & Codebase Audit Pipeline powered by TruffleHog, Telegram Bot, & GitHub Actions.

## Fitur
- **Bot Telegram Real-Time (Pterodactyl VPS):** Dapat dijalankan sebagai daemon bot Telegram 24/7 di server Pterodactyl terpisah tanpa harus bergantung pada antrean GitHub Actions.
- **Automasi GitHub Actions:** Mendukung pemindaian otomatis repositori Git via Cloudflare Worker Webhook (@Dicopi_bot) atau GitHub Actions workflow_dispatch.
- **Engine TruffleHog v3:** Menggunakan engine resmi **TruffleHog v3** dengan fitur *Live Verification* untuk memvalidasi token yang masih aktif.
- **Pengiriman Hasil Instan:** Laporan ringkas dan dokumen `findings_active.json` / `findings_potential.json` langsung dikirim otomatis ke chat Telegram Tuan Ciro.
- **Pencarian teks bebas (`-bebas`):** Kirim `<url repo/akun> -bebas <kata>` ke bot untuk mencari string apa saja di seluruh riwayat commit tanpa scan TruffleHog.
- **Mode feed global (`/feed`):** Memindai repositori dari pengguna aktif publik GitHub terkini secara otomatis.
- **Mode dork global (`/dork`):** Mencari pola file konfigurasi via GitHub Code Search.
- **Arsitektur Task Queue:** Menerima banyak target sekaligus secara non-blocking; target berikutnya dimasukkan ke antrean otomatis.

---

## 🚀 Panduan Menjalankan di Server Pterodactyl VPS

### 1. Persiapan File
Clone repositori ke root container server Pterodactyl:
```bash
git clone https://github.com/ciroxtreme/ciro-scan.git .
```
*(Atau ekstrak file zip `ciro-scan-vps.zip` ke server).*

### 2. Konfigurasi Kredensial (.env)
Salin file `.env.example` menjadi `.env`:
```bash
cp .env.example .env
```
Pastikan `TELEGRAM_BOT_TOKEN` dan `TELEGRAM_CHAT_ID` sudah terisi dengan benar.

### 3. Startup Server Panel
Di panel Pterodactyl (tab Startup / Console):
- Atur Startup Command: `bash startup.sh`
- Tekan tombol **Start** di Console.
Script `startup.sh` akan otomatis:
1. Mengunduh biner resmi TruffleHog ke `./bin/trufflehog` jika belum ada.
2. Memasang dependensi Python (`requirements.txt`).
3. Menjalankan daemon `bot.py`.

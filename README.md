# ciro-scan 🐷🔍
Adaptive Security Scanner & Codebase Audit Pipeline powered by TruffleHog, Telegram Bot, & GitHub Actions.

## Fitur Unggulan
- **Bot Telegram Real-Time (Pterodactyl Node.js):** Berjalan sebagai daemon 24/7 di server Pterodactyl (`npm start`) tanpa antrean GitHub Actions.
- **Mode Auto-Scan 24/7 Non-Stop (`/auto on`):** Dapat memindai secara otomatis terus-menerus tanpa perlu input manual setiap saat.
- **Pre-Bundled TruffleHog v3:** Biner resmi TruffleHog v3 sudah terpasang lokal di `./bin/trufflehog` (langsung jalan tanpa unduh).
- **Zero-PIP Pure Python Engine:** Menggunakan engine `urllib.request` bawaan, berjalan lancar di lingkungan tanpa `pip3`.
- **Pengiriman Hasil Instan:** Laporan ringkas & dokumen JSON temuan (`findings_active.json` / `findings_potential.json`) langsung terkirim otomatis ke Telegram Tuan Ciro.
- **Pencarian Teks Bebas (`-bebas`):** Kirim `<url> -bebas <kata>` untuk mencari string apa saja di riwayat commit.
- **Mode Feed & Dork Global:** Fitur cerdas menyedot feed pengguna aktif GitHub atau pencarian dork kode publik.

---

## 🚀 Panduan Menjalankan di Server Pterodactyl Node.js

### 1. Ekstrak Berkas
Ekstrak arsip `ciro-scan-vps.zip` ke root folder server Pterodactyl.

### 2. Atur GitHub PAT (Sangat Direkomendasikan)
Buka file `.env` di File Manager panel Pterodactyl:
```ini
TELEGRAM_BOT_TOKEN=9000245196:AAGZQ9mWpD_o3Sm5I4bqZ0s6Nd9O6xD4ST0
TELEGRAM_CHAT_ID=1936436999
GH_PAT=ghp_xxxxxxxxxxxxxxxxxxxx
```
> **Catatan GH_PAT:** Masukkan token GitHub Personal Access Token (PAT) Tuan Ciro ke baris `GH_PAT=` agar pemindaian `/feed` dan `/dork` tidak terbentur batas limit rate GitHub API (5000 request/jam vs 60 request/jam jika kosong).

### 3. Mulai Server
Klik tombol **Start** di Console panel Pterodactyl!

---

## 🎮 Daftar Perintah Bot Telegram:
- `/auto on` — Nyalakan pemindaian otomatis terus-menerus 24/7 (mode feed)
- `/auto off` — Matikan pemindaian otomatis
- `/auto dork` — Set auto-scan mode dork
- `/auto 60` — Ubah jeda antar ronde pemindaian otomatis (detik)
- `/feed` — Trigger satu kali pemindaian feed publik GitHub
- `/dork` — Trigger satu kali pemindaian dork code search
- `/status` — Cek status scanner, durasi, antrean, & auto-scan
- `/stop` — Batalkan pemindaian yang sedang berjalan
- `https://github.com/owner/repo` — Scan target repositori langsung
- `https://github.com/owner/repo -bebas kata` — Cari string teks bebas di commit

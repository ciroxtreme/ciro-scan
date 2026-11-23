# ciro-scan 🐷🔍
Adaptive Security Scanner & Codebase Audit Pipeline powered by TruffleHog, Telegram Bot, & GitHub Actions.

## Fitur Unggulan
- **Bot Telegram Real-Time (Pterodactyl Node.js):** Berjalan sebagai daemon 24/7 di server Pterodactyl (`npm start`) tanpa antrean GitHub Actions.
- **In-Memory Vault (Zero Plaintext PAT di Disk):** GitHub PAT disimpan terenkripsi AES-256-GCM + scrypt di `secrets.enc` dan hanya dimuat ke RAM saat runtime.
- **Multi-PAT Auto-Rolling / Fallback:** Mendukung hingga 3+ GitHub PAT sekaligus (kapasitas 15.000+ req/jam) dengan rotasi otomatis jika token terkena HTTP 403 / 429.
- **Mode Auto-Scan 24/7 Non-Stop (`/auto on`):** Dapat memindai secara otomatis terus-menerus tanpa perlu pemicu manual setiap saat.
- **Pre-Bundled TruffleHog v3:** Biner resmi TruffleHog v3 sudah terpasang lokal di `./bin/trufflehog` (langsung jalan tanpa unduh).
- **Zero-PIP Pure Python Engine:** Menggunakan engine `urllib.request` bawaan, berjalan lancar di lingkungan tanpa `pip3`.
- **Pengiriman Hasil Instan:** Laporan ringkas & dokumen JSON temuan (`findings_active.json` / `findings_potential.json`) langsung terkirim otomatis ke Telegram Tuan Ciro.
- **Pencarian Teks Bebas (`-bebas`):** Kirim `<url> -bebas <kata>` untuk mencari string apa saja di riwayat commit.
- **Mode Feed & Dork Global:** Fitur cerdas menyedot feed pengguna aktif GitHub atau pencarian dork kode publik.

---

## 🚀 Panduan Menjalankan di Server Pterodactyl Node.js

### 1. Ekstrak Berkas
Ekstrak arsip `ciro-scan-vps.zip` ke root folder server Pterodactyl.

### 2. Konfigurasi Otomatis
File `.env` sudah terisi dengan:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `VAULT_KEY`
- Berkas `secrets.enc` sudah berisi 3 token GitHub PAT terenkripsi AES-256-GCM yang siap dimuat ke RAM.

### 3. Mulai Server
Klik tombol **Start** di Console panel Pterodactyl (`npm start`)!

---

## 🎮 Daftar Perintah Bot Telegram:

### 🔄 Auto-Scan 24/7:
- `/auto on` — Nyalakan pemindaian otomatis terus-menerus 24/7 (mode feed)
- `/auto off` — Matikan pemindaian otomatis
- `/auto feed` — Set mode auto-scan ke feed publik
- `/auto dork` — Set mode auto-scan ke dork code search
- `/auto 60` — Ubah jeda antar ronde pemindaian otomatis (detik)

### 🔐 Manajemen GitHub PAT (RAM Vault):
- `/pats` — Cek status & kapasitas token yang tersimpan di RAM
- `/set_pat <token1> <token2> ...` — Simpan token baru (langsung dienkripsi ke secrets.enc)
- `/clear_pat` — Hapus seluruh token dari RAM dan disk

### 🎯 Pemindaian Manual & Kontrol:
- `/feed` — Trigger satu kali pemindaian feed publik GitHub
- `/dork` — Trigger satu kali pemindaian dork code search
- `https://github.com/owner/repo` — Scan target repositori langsung
- `username` atau `https://github.com/username` — Scan seluruh repo akun/organisasi
- `https://github.com/owner/repo -bebas kata` — Cari string teks bebas di commit
- `/status` — Cek status scanner, durasi, antrean, & auto-scan
- `/stop` — Batalkan pemindaian yang sedang berjalan
- `/help` — Tampilkan bantuan lengkap

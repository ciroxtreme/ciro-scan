# ciro-scan 🐷🔍
Adaptive Security Scanner & Codebase Audit Pipeline powered by TruffleHog & GitHub Actions.

## Fitur
- Mendukung pemindaian otomatis repositori Git via Cloudflare Worker Webhook (@Dicopi_bot) atau GitHub Actions workflow_dispatch.
- Menggunakan engine resmi **TruffleHog v3** dengan fitur *Live Verification* untuk memvalidasi token yang masih aktif.
- Hasil laporan ringkas dan file dokumen `findings_active.json` / `findings_potential.json` langsung dikirim otomatis ke chat Telegram Tuan Ciro (temuan dipisah: aktif, potensial, noise; file `findings_noise.json` hanya ada di artifact GitHub).
- **Pencarian teks bebas (`-bebas`):** kirim `<url repo/akun> -bebas <kata>` ke bot (contoh: `https://github.com/ciroxtreme -bebas password`) untuk mencari kata apa saja di seluruh history commit, tanpa scan TruffleHog. Hasilnya `text_search_results.json`.
- **Mode feed global (`feed`):** ketik `feed` ke bot (atau target `feed` di workflow_dispatch) — otomatis ambil user yang paling baru aktif dari event publik GitHub, scan sampai 50 repo mereka (maks 3 repo/user, timeout 300 detik/repo, 5 worker paralel). Jalan otomatis tiap 6 jam via cron. Urutan user = urutan kemunculan di feed (paling baru dulu).
- **Mode dork global (`/dork`):** ketik `/dork` ke bot (atau target `dork`) — cari repo berisi file sensitif (`.env`, `id_rsa`, token, dll.) di SELURUH GitHub publik via Code Search, lalu scan sampai 100 repo. Query dork jalan paralel (bukan satu-satu), jatah 100 repo dibagi rata antar query (round-robin — satu query tidak bisa memborong semua slot), scan pakai 10 worker, timeout 300 detik/repo. Butuh `GH_PAT` di secrets (code search tidak bisa anonymous).
- **Zero Token Leak:** Seluruh token bot Telegram dan Personal Access Token tersimpan di GitHub Secrets / Cloudflare Worker Secrets (tidak ada token hardcoded di repositori).

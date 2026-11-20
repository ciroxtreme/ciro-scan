# ciro-scan 🐷🔍
Adaptive Security Scanner & Codebase Audit Pipeline powered by TruffleHog & GitHub Actions.

## Fitur
- Mendukung pemindaian otomatis repositori Git via Cloudflare Worker Webhook (@Dicopi_bot) atau GitHub Actions workflow_dispatch.
- Menggunakan engine resmi **TruffleHog v3** dengan fitur *Live Verification* untuk memvalidasi token yang masih aktif.
- Hasil laporan ringkas dan file dokumen `findings_active.json` / `findings_potential.json` langsung dikirim otomatis ke chat Telegram Tuan Ciro (temuan dipisah: aktif, potensial, noise; file `findings_noise.json` hanya ada di artifact GitHub).
- **Pencarian teks bebas (`-bebas`):** kirim `<url repo/akun> -bebas <kata>` ke bot (contoh: `https://github.com/ciroxtreme -bebas password`) untuk mencari kata apa saja di seluruh history commit, tanpa scan TruffleHog. Hasilnya `text_search_results.json`.
- **Zero Token Leak:** Seluruh token bot Telegram dan Personal Access Token tersimpan di GitHub Secrets / Cloudflare Worker Secrets (tidak ada token hardcoded di repositori).

# ciro-scan 🐷🔍
Adaptive Security Scanner & Codebase Audit Pipeline powered by TruffleHog & GitHub Actions.

## Fitur
- Mendukung pemindaian otomatis repositori Git via Cloudflare Worker Webhook (@Dicopi_bot) atau GitHub Actions workflow_dispatch.
- Menggunakan engine resmi **TruffleHog v3** dengan fitur *Live Verification* untuk memvalidasi token yang masih aktif.
- Hasil laporan ringkas dan file dokumen `findings.json` langsung dikirim otomatis ke chat Telegram Tuan Ciro.
- **Zero Token Leak:** Seluruh token bot Telegram dan Personal Access Token tersimpan di GitHub Secrets / Cloudflare Worker Secrets (tidak ada token hardcoded di repositori).

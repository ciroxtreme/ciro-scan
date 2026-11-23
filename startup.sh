#!/bin/bash
# startup.sh — Entrypoint otomatis untuk Pterodactyl VPS (ciro-scan Telegram Bot)
set -e

echo "=========================================="
echo "⚡ CIRO-SCAN BOT BOOTSTRAP (PTERODACTYL)"
echo "=========================================="

# 1. Pastikan folder bin lokal ada di PATH
mkdir -p bin
export PATH="$(pwd)/bin:$PATH"

# 2. Cek & Unduh TruffleHog jika belum ada
if ! command -v trufflehog &> /dev/null && [ ! -f "bin/trufflehog" ]; then
    echo "📥 Mengunduh biner resmi TruffleHog ke ./bin/trufflehog..."
    curl -sSfL https://raw.githubusercontent.com/trufflesecurity/trufflehog/main/scripts/install.sh | sh -s -- -b ./bin
    chmod +x bin/trufflehog || true
    echo "✅ TruffleHog terpasang: $(./bin/trufflehog --version 2>/dev/null || echo 'OK')"
else
    echo "✅ TruffleHog sudah tersedia."
fi

# 3. Pastikan dependensi python terpasang
if [ -f "requirements.txt" ]; then
    echo "📦 Memeriksa dependensi Python..."
    pip install -r requirements.txt --no-cache-dir 2>/dev/null || pip3 install -r requirements.txt --no-cache-dir 2>/dev/null || true
fi

# 4. Pastikan file .env ada
if [ ! -f ".env" ] && [ -f ".env.example" ]; then
    echo "⚠️ File .env belum ditemukan, menyalin dari .env.example..."
    cp .env.example .env
fi

# 5. Jalankan bot.py
echo "🚀 Menjalankan bot.py..."
exec python3 -u bot.py

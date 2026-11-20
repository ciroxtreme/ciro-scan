import sys
import os
import json
import subprocess
import requests

TARGET_URL = sys.argv[1] if len(sys.argv) > 1 else os.getenv("TARGET_URL", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "1936436999")

def send_telegram_text(text):
    if not TELEGRAM_BOT_TOKEN:
        print("[WARN] No Telegram token configured")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        requests.post(url, json=payload, timeout=15)
    except Exception as e:
        print(f"[ERR] Failed to send Telegram message: {e}")

def send_telegram_document(file_path, caption=""):
    if not TELEGRAM_BOT_TOKEN or not os.path.exists(file_path):
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    try:
        with open(file_path, "rb") as f:
            requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption}, files={"document": f}, timeout=30)
        print(f"✅ Document sent: {file_path}")
    except Exception as e:
        print(f"[ERR] Failed to send document: {e}")

def main():
    if not TARGET_URL:
        print("❌ Error: No target URL provided.")
        sys.exit(1)

    print(f"🚀 Memulai audit TruffleHog untuk target: {TARGET_URL}")
    send_telegram_text(f"🔍 <b>TruffleHog Security Scan Dimulai!</b>\n\n🎯 <b>Target:</b> <code>{TARGET_URL}</code>\n⏳ <i>Sedang mengendus seluruh riwayat commit...</i>")

    cmd = ["trufflehog", "git", TARGET_URL, "--json", "--no-update"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    
    findings = []
    verified_count = 0
    raw_lines = res.stdout.strip().split("\n") if res.stdout.strip() else []
    
    for line in raw_lines:
        try:
            data = json.loads(line)
            is_verified = data.get("Verified", False)
            if is_verified:
                verified_count += 1
            findings.append(data)
        except Exception:
            pass

    # Simpan hasil lengkap ke findings.json
    with open("findings.json", "w") as f:
        json.dump(findings, f, indent=2)

    total_findings = len(findings)
    print(f"Audit selesai. Total temuan: {total_findings} (Verified live: {verified_count})")

    # Buat summary teks
    summary_lines = [
        "📊 <b>LAPORAN HASIL SCAN TRUFFLEHOG</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"🎯 <b>Target:</b> <code>{TARGET_URL}</code>",
        f"🚨 <b>Verified Active Leaks:</b> <b>{verified_count}</b>",
        f"⚠️ <b>Total Potensi Temuan:</b> {total_findings}",
        "━━━━━━━━━━━━━━━━━━"
    ]

    if verified_count > 0:
        summary_lines.append("\n🔥 <b>DAFTAR TOKEN AKTIF BOCOR:</b>")
        for i, f in enumerate(findings, 1):
            if f.get("Verified"):
                det = f.get("DetectorName", "Unknown")
                commit = f.get("SourceMetadata", {}).get("Data", {}).get("Git", {}).get("commit", "")[:8]
                file_path = f.get("SourceMetadata", {}).get("Data", {}).get("Git", {}).get("file", "")
                raw = f.get("Raw", "")
                masked = raw[:8] + "..." + raw[-4:] if len(raw) > 12 else "***"
                summary_lines.append(f"{i}. <b>[{det}]</b> di <code>{file_path}</code> (commit: <code>{commit}</code>)\n   👉 Token: <code>{masked}</code>")
    else:
        summary_lines.append("\n✅ <b>STATUS: AMAN!</b> Tidak ditemukan kunci rahasia aktif yang bocor.")

    summary_text = "\n".join(summary_lines)
    send_telegram_text(summary_text)

    # Simpan file summary txt juga
    with open("scan_summary.txt", "w") as f:
        f.write(summary_text.replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", "").replace("<i>", "").replace("</i>", ""))

    # Jika ada temuan, kirimkan file findings.json langsung ke Telegram Tuan Ciro untuk dianalisis
    if total_findings > 0:
        send_telegram_document("findings.json", f"📁 File JSON Hasil Scan TruffleHog ({TARGET_URL})")

if __name__ == '__main__':
    main()

import sys
import os
import json
import subprocess
import urllib.request
import urllib.parse
import requests

TARGET_INPUT = sys.argv[1] if len(sys.argv) > 1 else os.getenv("TARGET_URL", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "1936436999")
GH_PAT = os.getenv("GH_PAT", "")

def send_telegram_text(text):
    if not TELEGRAM_BOT_TOKEN:
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
        print(f"[ERR] Send text failed: {e}")

def send_telegram_document(file_path, caption=""):
    if not TELEGRAM_BOT_TOKEN or not os.path.exists(file_path):
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    try:
        with open(file_path, "rb") as f:
            requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption}, files={"document": f}, timeout=35)
        print(f"✅ Document sent: {file_path}")
    except Exception as e:
        print(f"[ERR] Send document failed: {e}")

def resolve_target_repos(target_str):
    """
    Mendeteksi apakah target berupa:
    1. Single Repo (misal: https://github.com/ciroxtreme/cdtt)
    2. Akun/Organisasi (misal: https://github.com/ciroxtreme atau ciroxtreme)
    """
    clean = target_str.strip().rstrip("/")
    # Pola: https://github.com/owner/repo
    m_repo = re.match(r"^https?://github\.com/([^/]+)/([^/]+)/?$", clean)
    if m_repo:
        return [f"https://github.com/{m_repo.group(1)}/{m_repo.group(2)}"]

    # Pola akun: https://github.com/owner atau @owner atau owner
    m_user = re.match(r"^(?:https?://github\.com/)?@?([^/]+)/?$", clean)
    if m_user:
        owner = m_user.group(1)
        print(f"🌐 Mendeteksi target sebagai AKUN PENGGUNA/ORGANISASI: {owner}")
        api_url = f"https://api.github.com/users/{owner}/repos?per_page=100&type=public"
        headers = {"User-Agent": "CiroScan-BatchEngine"}
        if GH_PAT:
            headers["Authorization"] = f"token {GH_PAT}"
        
        try:
            req = urllib.request.Request(api_url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                repos_data = json.loads(resp.read().decode())
                urls = [r["html_url"] for r in repos_data if not r.get("fork")]
                print(f"✅ Ditemukan {len(urls)} repositori publik untuk akun '{owner}'")
                return urls
        except Exception as e:
            print(f"⚠️ Gagal mengambil daftar repo akun {owner}: {e}")
            # Fallback jika ternyata target repo non-standard
            return [clean]
    
    return [clean]

def main():
    if not TARGET_INPUT:
        print("❌ Error: No target input provided.")
        sys.exit(1)

    targets = resolve_target_repos(TARGET_INPUT)
    total_targets = len(targets)

    if total_targets == 0:
        send_telegram_text(f"⚠️ Tidak ditemukan repositori untuk target: <code>{TARGET_INPUT}</code>")
        return

    is_batch = total_targets > 1
    if is_batch:
        send_telegram_text(f"🚀 <b>TRUFFLEHOG BATCH SCAN DIMULAI!</b>\n\n👤 <b>Target Akun:</b> <code>{TARGET_INPUT}</code>\n📦 <b>Total Repositori:</b> <b>{total_targets} repo</b>\n⏳ <i>Runner sedang menyisir seluruh repositori satu per satu...</i>")
    else:
        send_telegram_text(f"🔍 <b>TruffleHog Security Scan Dimulai!</b>\n\n🎯 <b>Target:</b> <code>{targets[0]}</code>\n⏳ <i>Sedang mengendus seluruh riwayat commit...</i>")

    all_findings = []
    verified_findings = []
    repo_summaries = []

    for idx, repo_url in enumerate(targets, 1):
        repo_name = repo_url.split("/")[-1]
        print(f"[{idx}/{total_targets}] Scanning {repo_name} ({repo_url})...")
        cmd = ["trufflehog", "git", repo_url, "--json", "--no-update"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        
        repo_verified = 0
        repo_total = 0
        raw_lines = res.stdout.strip().split("\n") if res.stdout.strip() else []
        for line in raw_lines:
            try:
                data = json.loads(line)
                data["_scanned_repo"] = repo_name
                is_verified = data.get("Verified", False)
                if is_verified:
                    repo_verified += 1
                    verified_findings.append(data)
                all_findings.append(data)
                repo_total += 1
            except Exception:
                pass
        
        repo_summaries.append({
            "repo": repo_name,
            "url": repo_url,
            "verified": repo_verified,
            "total": repo_total
        })

    # Simpan laporan json
    with open("findings.json", "w") as f:
        json.dump(all_findings, f, indent=2)

    total_verified = len(verified_findings)
    total_leaks = len(all_findings)

    # Susun Pesan Ringkasan
    msg_lines = [
        "📊 <b>LAPORAN HASIL AUDIT TRUFFLEHOG</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"🎯 <b>Target:</b> <code>{TARGET_INPUT}</code>",
        f"📦 <b>Repo Discan:</b> <b>{total_targets} repositori</b>",
        f"🚨 <b>Verified Active Leaks:</b> <b>{total_verified}</b>",
        f"⚠️ <b>Total Potensi Temuan:</b> {total_leaks}",
        "━━━━━━━━━━━━━━━━━━"
    ]

    if is_batch:
        msg_lines.append("\n📋 <b>RINGKASAN STATUS REPO:</b>")
        for s in repo_summaries:
            icon = "❌" if s["verified"] > 0 else "✅"
            msg_lines.append(f"{icon} <code>{s['repo']}</code> : <b>{s['verified']} aktif bocor</b> ({s['total']} potensi)")

    if total_verified > 0:
        msg_lines.append("\n🔥 <b>DETAIL TOKEN AKTIF BOCOR:</b>")
        for i, f in enumerate(verified_findings[:15], 1):
            det = f.get("DetectorName", "Unknown")
            rname = f.get("_scanned_repo", "")
            commit = f.get("SourceMetadata", {}).get("Data", {}).get("Git", {}).get("commit", "")[:8]
            raw = f.get("Raw", "")
            masked = raw[:8] + "..." + raw[-4:] if len(raw) > 12 else "***"
            msg_lines.append(f"{i}. <b>[{det}]</b> di <code>{rname}</code> (commit: <code>{commit}</code>)\n   👉 Token: <code>{masked}</code>")
        if total_verified > 15:
            msg_lines.append(f"<i>...dan {total_verified - 15} temuan lainnya ada di file JSON terlampir.</i>")
    else:
        msg_lines.append("\n🏆 <b>STATUS: 100% AMAN!</b> Tidak ada kunci rahasia aktif yang bocor!")

    report_text = "\n".join(msg_lines)
    send_telegram_text(report_text)

    # Kirim file JSON jika ada temuan
    if total_leaks > 0:
        send_telegram_document("findings.json", f"📁 File JSON Temuan Audit ({TARGET_INPUT})")

if __name__ == "__main__":
    main()

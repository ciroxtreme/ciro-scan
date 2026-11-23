#!/usr/bin/env python3
"""
ciro-scan Telegram Bot Daemon for Pterodactyl VPS.
Real-time Codebase & Secret Scanner runner with task queue, non-blocking execution,
and process control.
"""

import os
import sys
import time
import json
import signal
import queue
import threading
import subprocess
import requests

# 1. Load .env sederhana (zero-dependency)
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(ENV_PATH):
    with open(ENV_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip("'").strip('"')
            if k and k not in os.environ:
                os.environ[k] = v

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED_CHAT_ID = str(os.getenv("TELEGRAM_CHAT_ID", "1936436999")).strip()

# Pastikan folder ./bin ada di PATH (tempat biner trufflehog lokal)
BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin")
if os.path.exists(BIN_DIR) and BIN_DIR not in os.environ.get("PATH", ""):
    os.environ["PATH"] = f"{BIN_DIR}:{os.environ.get('PATH', '')}"

if not BOT_TOKEN:
    print("❌ TELEGRAM_BOT_TOKEN belum diset di .env atau environment!")
    sys.exit(1)

API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Queue dan status proses
task_queue = queue.Queue()
current_task = {
    "proc": None,
    "target": None,
    "start_time": 0,
    "lock": threading.Lock()
}

def tg_send(chat_id, text, parse_mode="HTML"):
    try:
        url = f"{API_BASE}/sendMessage"
        payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
        requests.post(url, json=payload, timeout=25)
    except Exception as e:
        print(f"⚠️ Gagal kirim Telegram: {e}")

def get_help_message():
    return (
        "🐷🔍 <b>CIRO-SCAN TELEGRAM BOT (Pterodactyl Edition)</b>\n"
        "────────────────────────────\n"
        "Engine audit kode & sanitasi k-o-n-f-i-g real-time 24/7.\n\n"
        "<b>Cara Penggunaan / Format Perintah:</b>\n\n"
        "🎯 <b>1. Target Repositori Git:</b>\n"
        "Kirim link lengkap repo:\n"
        "👉 <code>https://github.com/owner/repo</code>\n\n"
        "👤 <b>2. Target Akun / Organisasi:</b>\n"
        "Kirim username target (scan semua repo publiknya):\n"
        "👉 <code>username</code> atau <code>https://github.com/username</code>\n\n"
        "🔍 <b>3. Mode Pencarian Bebas (-bebas):</b>\n"
        "Cari teks bebas di seluruh riwayat commit:\n"
        "👉 <code>https://github.com/owner/repo -bebas kata_kunci</code>\n\n"
        "🌐 <b>4. Mode Feed Global:</b>\n"
        "Audit repo user aktif terkini dari feed publik GitHub:\n"
        "👉 Kirim <code>/feed</code> atau <code>feed</code>\n\n"
        "🕵️ <b>5. Mode Dork Global:</b>\n"
        "Pencarian pola konfigurasi publik via Code Search:\n"
        "👉 Kirim <code>/dork</code> atau <code>dork</code>\n\n"
        "<b>Perintah Kontrol:</b>\n"
        "• <code>/status</code> — Cek status pemindaian & antrean\n"
        "• <code>/stop</code> — Batalkan proses yang sedang berjalan\n"
        "• <code>/help</code> — Buka panduan ini kembali"
    )

def worker_loop():
    while True:
        target_info = task_queue.get()
        if not target_info:
            break
        
        chat_id, target_input, search_kw = target_info
        with current_task["lock"]:
            current_task["target"] = target_input + (f" -bebas {search_kw}" if search_kw else "")
            current_task["start_time"] = time.time()
        
        print(f"\n🚀 [WORKER] Memulai scan target: {current_task['target']}")
        env = os.environ.copy()
        env["TARGET_URL"] = target_input
        if search_kw:
            env["SEARCH_KEYWORD"] = search_kw
        else:
            env.pop("SEARCH_KEYWORD", None)
        
        # Panggil scan_engine.py
        cmd = [sys.executable, "-u", "scan_engine.py", target_input]
        if search_kw:
            cmd.extend(["-bebas", search_kw])
            
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=os.path.dirname(os.path.abspath(__file__)),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            with current_task["lock"]:
                current_task["proc"] = proc
            
            # Stream log ke stdout console Pterodactyl
            for line in proc.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
            
            proc.wait()
            rc = proc.returncode
            print(f"🏁 [WORKER] Selesai dengan return code: {rc}")
            
        except Exception as e:
            print(f"❌ Error saat menjalankan scan_engine: {e}")
            tg_send(chat_id, f"❌ <b>Terjadi kesalahan pada worker:</b> {e}")
        finally:
            with current_task["lock"]:
                current_task["proc"] = None
                current_task["target"] = None
                current_task["start_time"] = 0
            task_queue.task_done()

def handle_message(msg):
    chat_id = str(msg.get("chat", {}).get("id", ""))
    text = (msg.get("text") or "").strip()
    
    if chat_id != ALLOWED_CHAT_ID:
        print(f"⛔ Pesan ditolak dari chat ID asing: {chat_id}")
        tg_send(chat_id, "⛔ <i>Akses ditolak. Bot privat khusus Tuan Ciro.</i>")
        return
    
    if not text:
        return
    
    print(f"📩 Pesan diterima: {text}")
    lower = text.lower()
    
    if lower in ("/start", "/help", "help", "menu"):
        tg_send(chat_id, get_help_message())
        return
    
    if lower == "/status":
        with current_task["lock"]:
            is_running = current_task["proc"] is not None
            running_target = current_task["target"]
            start_t = current_task["start_time"]
        
        qsize = task_queue.qsize()
        if is_running:
            dur = int(time.time() - start_t)
            tg_send(chat_id, (
                "⚡ <b>STATUS CIRO-SCAN BOT:</b>\n"
                "────────────────────────────\n"
                f"🔄 <b>Sedang Memindai:</b> <code>{running_target}</code>\n"
                f"⏱️ <b>Durasi:</b> {dur} detik\n"
                f"📦 <b>Antrean Menunggu:</b> {qsize} tugas"
            ))
        else:
            tg_send(chat_id, (
                "💤 <b>STATUS CIRO-SCAN BOT:</b>\n"
                "────────────────────────────\n"
                "✨ <b>Status:</b> IDLE (Siaga menerima target baru)\n"
                f"📦 <b>Antrean Menunggu:</b> {qsize} tugas"
            ))
        return

    if lower == "/stop":
        with current_task["lock"]:
            proc = current_task["proc"]
            target = current_task["target"]
        
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                tg_send(chat_id, f"🛑 <i>Membatalkan pemindaian untuk:</i> <code>{target}</code>...")
                # Tunggu sebentar, jika masih hidup paksa kill
                time.sleep(2)
                if proc.poll() is None:
                    proc.kill()
            except Exception as e:
                tg_send(chat_id, f"⚠️ Gagal menghentikan proses: {e}")
        else:
            tg_send(chat_id, "ℹ️ Tidak ada pemindaian yang sedang berjalan.")
        return

    # Parse target dan opsi -bebas
    target_input = text
    search_kw = ""
    
    if "-bebas" in text:
        parts = text.split("-bebas", 1)
        target_input = parts[0].strip()
        search_kw = parts[1].strip()
    
    # Hapus awalan command slash jika ada (misal: /feed -> feed, /dork -> dork)
    if target_input.startswith("/"):
        target_input = target_input[1:]
    
    with current_task["lock"]:
        is_running = current_task["proc"] is not None
    
    task_queue.put((chat_id, target_input, search_kw))
    qsize = task_queue.qsize()
    
    kw_info = f" (Pencarian teks: <code>{search_kw}</code>)" if search_kw else ""
    if is_running or qsize > 1:
        tg_send(chat_id, (
            f"⏳ <b>Ditambahkan ke Antrean (#{qsize}):</b>\n"
            f"🎯 <b>Target:</b> <code>{target_input}</code>{kw_info}\n\n"
            "<i>Tugas akan otomatis dieksekusi setelah pemindaian sebelumnya selesai.</i>"
        ))
    else:
        tg_send(chat_id, (
            f"🚀 <b>Permintaan Diterima:</b>\n"
            f"🎯 <b>Target:</b> <code>{target_input}</code>{kw_info}\n\n"
            "<i>Menyiapkan engine scanner...</i>"
        ))

def main():
    print("=" * 50)
    print("⚡ CIRO-SCAN TELEGRAM BOT DAEMON (PTERODACTYL)")
    print(f"👤 Allowed Chat ID: {ALLOWED_CHAT_ID}")
    print("=" * 50)
    
    # Jalankan worker thread
    t = threading.Thread(target=worker_loop, daemon=True)
    t.start()
    
    # Dapatkan info bot
    try:
        me = requests.get(f"{API_BASE}/getMe", timeout=15).json()
        if me.get("ok"):
            bot_user = me["result"]["username"]
            print(f"✅ Bot Terhubung: @{bot_user}")
            tg_send(ALLOWED_CHAT_ID, f"🚀 <b>Ciro-Scan Bot Online!</b> (@{bot_user})\n<i>Siaga menerima target di Pterodactyl VPS. Ketik /help untuk panduan.</i>")
        else:
            print(f"⚠️ Respon getMe tidak OK: {me}")
    except Exception as e:
        print(f"⚠️ Gagal getMe: {e}")
    
    offset = None
    # Bersihkan pending updates lama saat boot agar tidak spam
    try:
        requests.get(f"{API_BASE}/getUpdates?offset=-1", timeout=10)
    except Exception:
        pass
        
    print("👂 Menunggu pesan dari Telegram...")
    while True:
        try:
            params = {"timeout": 25}
            if offset is not None:
                params["offset"] = offset
            
            resp = requests.get(f"{API_BASE}/getUpdates", params=params, timeout=35)
            if resp.status_code != 200:
                time.sleep(3)
                continue
            
            data = resp.json()
            if not data.get("ok"):
                time.sleep(3)
                continue
            
            for update in data.get("result", []):
                offset = update["update_id"] + 1
                if "message" in update:
                    handle_message(update["message"])
                    
        except requests.exceptions.RequestException as e:
            time.sleep(3)
        except Exception as e:
            print(f"⚠️ Polling loop error: {e}")
            time.sleep(2)

if __name__ == "__main__":
    main()

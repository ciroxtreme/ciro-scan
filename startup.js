'use strict';
/**
 * startup.js — Entrypoint & Telegram Bot Daemon ciro-scan untuk Pterodactyl VPS (Node.js Egg)
 * Mendukung standar: npm install && npm start (atau node startup.js)
 */

const fs = require('fs');
const path = require('path');
const https = require('https');
const { spawn, execSync } = require('child_process');

console.log('====================================================');
console.log('🐷🔍 CIRO-SCAN TELEGRAM BOT (Pterodactyl Node.js)');
console.log('====================================================\n');

// 1. Muat .env sederhana tanpa dependency eksternal
const ENV_FILE = path.join(__dirname, '.env');
const EXAMPLE_ENV = path.join(__dirname, '.env.example');

if (!fs.existsSync(ENV_FILE) && fs.existsSync(EXAMPLE_ENV)) {
  console.log('ℹ️  File .env belum ada, menyalin dari .env.example...');
  fs.copyFileSync(EXAMPLE_ENV, ENV_FILE);
}

if (fs.existsSync(ENV_FILE)) {
  const lines = fs.readFileSync(ENV_FILE, 'utf8').split('\n');
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#') || !trimmed.includes('=')) continue;
    const idx = trimmed.indexOf('=');
    const k = trimmed.slice(0, idx).trim();
    let v = trimmed.slice(idx + 1).trim();
    if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) {
      v = v.slice(1, -1);
    }
    if (k && !process.env[k]) {
      process.env[k] = v;
    }
  }
}

const BOT_TOKEN = (process.env.TELEGRAM_BOT_TOKEN || '').trim();
const ALLOWED_CHAT_ID = String(process.env.TELEGRAM_CHAT_ID || '1936436999').trim();

if (!BOT_TOKEN) {
  console.error('❌ TELEGRAM_BOT_TOKEN belum diset di file .env atau environment server!');
  console.error('   Buka file .env lalu masukkan token bot Telegram Tuan Ciro.');
  process.exit(1);
}

// 2. Siapkan direktori ./bin untuk TruffleHog lokal
const BIN_DIR = path.join(__dirname, 'bin');
if (!fs.existsSync(BIN_DIR)) fs.mkdirSync(BIN_DIR, { recursive: true });
process.env.PATH = `${BIN_DIR}:${process.env.PATH || ''}`;

// 3. Verifikasi & Unduh TruffleHog jika belum ada
function ensureTruffleHog() {
  const localTh = path.join(BIN_DIR, 'trufflehog');
  let hasTh = false;
  try {
    execSync('trufflehog --version', { stdio: 'ignore' });
    hasTh = true;
  } catch (e) {
    if (fs.existsSync(localTh)) hasTh = true;
  }

  if (!hasTh) {
    console.log('📥 Mengunduh biner resmi TruffleHog ke ./bin/trufflehog...');
    const arch = (process.arch === 'arm64' || process.arch === 'aarch64') ? 'arm64' : 'amd64';
    const tag = 'v3.100.1';
    const ver = '3.100.1';
    const tarName = `trufflehog_${ver}_linux_${arch}.tar.gz`;
    const tarUrl = `https://github.com/trufflesecurity/trufflehog/releases/download/${tag}/${tarName}`;
    const tmpTar = path.join('/tmp', 'th.tar.gz');

    try {
      execSync(`curl -sL "${tarUrl}" -o "${tmpTar}" && tar -xzf "${tmpTar}" -C "${BIN_DIR}" trufflehog && rm -f "${tmpTar}" && chmod +x "${localTh}"`, {
        stdio: 'inherit',
      });
      console.log('✅ TruffleHog berhasil dipasang di ./bin/trufflehog\n');
    } catch (e) {
      console.warn('⚠️ Gagal unduh langsung tarball TruffleHog:', e.message);
    }
  } else {
    console.log('✅ TruffleHog siap digunakan.\n');
  }
}

// 4. Verifikasi runtime Python 3
function ensurePythonDeps() {
  try {
    const ver = execSync('python3 --version', { encoding: 'utf8' }).trim();
    console.log(`✅ Runtime ${ver} terdeteksi.\n`);
  } catch (e) {
    console.warn('⚠️ Python3 tidak ditemukan di sistem. Pastikan container mendukung python3.\n');
  }
}

ensureTruffleHog();
ensurePythonDeps();

// 5. Telegram API Client (Native HTTPS, Zero Dependency)
function telegramRequest(method, payload) {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(payload || {});
    const req = https.request({
      hostname: 'api.telegram.org',
      port: 443,
      path: `/bot${BOT_TOKEN}/${method}`,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(data),
      },
      timeout: 35000,
    }, (res) => {
      let body = '';
      res.on('data', (c) => { body += c; });
      res.on('end', () => {
        try {
          const json = JSON.parse(body);
          resolve(json);
        } catch (e) {
          resolve({ ok: false, error: body });
        }
      });
    });
    req.on('error', (e) => reject(e));
    req.on('timeout', () => {
      req.destroy();
      reject(new Error('Telegram request timeout'));
    });
    req.write(data);
    req.end();
  });
}

async function sendMessage(chatId, text, options = {}) {
  try {
    return await telegramRequest('sendMessage', {
      chat_id: chatId,
      text,
      parse_mode: options.parse_mode || 'HTML',
      disable_web_page_preview: options.disable_preview !== false,
    });
  } catch (e) {
    console.error('⚠️ Gagal kirim pesan Telegram:', e.message);
  }
}

function getHelpText() {
  return [
    '🐷🔍 <b>CIRO-SCAN TELEGRAM BOT (Pterodactyl Node.js)</b>',
    '────────────────────────────',
    'Engine audit kode & sanitasi k-o-n-f-i-g real-time 24/7.\n',
    '<b>Cara Penggunaan / Format Perintah:</b>\n',
    '🎯 <b>1. Target Repositori Git Langsung:</b>',
    'Kirim link repositori lengkap:',
    '👉 <code>https://github.com/owner/repo</code>\n',
    '👤 <b>2. Target Akun / Organisasi:</b>',
    'Kirim username untuk scan seluruh repo publiknya:',
    '👉 <code>username</code> atau <code>https://github.com/username</code>\n',
    '🔍 <b>3. Mode Pencarian Bebas (-bebas):</b>',
    'Cari teks bebas di seluruh riwayat commit tanpa TruffleHog:',
    '👉 <code>https://github.com/owner/repo -bebas kata_kunci</code>\n',
    '🌐 <b>4. Mode Feed Global:</b>',
    'Audit repo pengguna aktif terkini dari feed publik GitHub:',
    '👉 Kirim <code>/feed</code> atau <code>feed</code>\n',
    '🕵️ <b>5. Mode Dork Global:</b>',
    'Pencarian pola file konfigurasi via Code Search:',
    '👉 Kirim <code>/dork</code> atau <code>dork</code>\n',
    '🔄 <b>6. Mode Auto-Scan Terus-Menerus (24/7):</b>',
    '• <code>/auto on</code> — Nyalakan auto-scan non-stop',
    '• <code>/auto off</code> — Matikan auto-scan',
    '• <code>/auto feed</code> — Set mode feed publik',
    '• <code>/auto dork</code> — Set mode dork code search',
    '• <code>/auto 60</code> — Ubah jeda jeda antar ronde (detik)\n',
    '<b>Perintah Kontrol:</b>',
    '• <code>/status</code> — Cek status pemindaian & antrean',
    '• <code>/stop</code> — Batalkan proses yang sedang berjalan',
    '• <code>/help</code> — Buka panduan ini kembali',
  ].join('\n');
}

// 6. Sistem Antrean (Task Queue FIFO) & Eksekusi Proses
const taskQueue = [];
let isBusy = false;
let currentProcess = null;
let currentTargetLabel = null;
let taskStartTime = 0;

// Konfigurasi Auto-Scan Loop (Terus-menerus 24/7)
let autoScanEnabled = (process.env.AUTO_SCAN || '').trim().toLowerCase() === 'true';
let autoScanMode = (process.env.AUTO_SCAN_MODE || 'feed').trim().toLowerCase();
let autoScanInterval = parseInt(process.env.AUTO_SCAN_INTERVAL || '60', 10);
let autoScanTimer = null;

function scheduleNextAutoScan() {
  if (!autoScanEnabled) return;
  if (autoScanTimer) clearTimeout(autoScanTimer);
  console.log(`⏱️ [Auto-Scan] Terjadwal dalam ${autoScanInterval}s (mode: ${autoScanMode})...`);
  autoScanTimer = setTimeout(() => {
    if (!autoScanEnabled) return;
    if (taskQueue.length === 0 && !isBusy) {
      console.log(`🚀 [Auto-Scan] Memulai ronde otomatis berikutnya: ${autoScanMode}`);
      sendMessage(ALLOWED_CHAT_ID, `🔄 <b>[Auto-Scan] Ronde Baru:</b> Memulai pemindaian otomatis mode <code>${autoScanMode}</code>...`);
      taskQueue.push({
        chatId: ALLOWED_CHAT_ID,
        targetInput: autoScanMode,
        searchKw: '',
        isAuto: true,
      });
      processNextTask();
    }
  }, autoScanInterval * 1000);
}

function processNextTask() {
  if (taskQueue.length === 0) {
    isBusy = false;
    currentProcess = null;
    currentTargetLabel = null;
    taskStartTime = 0;
    if (autoScanEnabled) {
      scheduleNextAutoScan();
    }
    return;
  }

  isBusy = true;
  const { chatId, targetInput, searchKw } = taskQueue.shift();
  currentTargetLabel = targetInput + (searchKw ? ` -bebas ${searchKw}` : '');
  taskStartTime = Date.now();

  console.log(`\n🚀 [TASK] Memulai scan target: ${currentTargetLabel}`);

  const env = Object.assign({}, process.env, {
    TARGET_URL: targetInput,
    TELEGRAM_BOT_TOKEN: BOT_TOKEN,
    TELEGRAM_CHAT_ID: ALLOWED_CHAT_ID,
    PATH: `${BIN_DIR}:${process.env.PATH || ''}`,
  });

  if (searchKw) env.SEARCH_KEYWORD = searchKw;
  else delete env.SEARCH_KEYWORD;

  const args = ['-u', 'scan_engine.py', targetInput];
  if (searchKw) args.push('-bebas', searchKw);

  try {
    currentProcess = spawn('python3', args, {
      cwd: __dirname,
      env,
      stdio: 'inherit', // langsung streaming log ke Console Pterodactyl
    });

    currentProcess.on('error', (err) => {
      console.error('❌ Gagal menjalankan scan_engine.py:', err.message);
      sendMessage(chatId, `❌ <b>Gagal menjalankan scanner:</b> ${err.message}`);
    });

    currentProcess.on('close', (code) => {
      console.log(`🏁 [TASK] Selesai dengan kode keluar: ${code}`);
      currentProcess = null;
      currentTargetLabel = null;
      taskStartTime = 0;
      if (taskQueue.length > 0) {
        processNextTask();
      } else if (autoScanEnabled) {
        scheduleNextAutoScan();
      }
    });
  } catch (err) {
    console.error('❌ Exception saat spawn proses:', err.message);
    sendMessage(chatId, `❌ <b>Kesalahan sistem:</b> ${err.message}`);
    currentProcess = null;
    currentTargetLabel = null;
    taskStartTime = 0;
    if (taskQueue.length > 0) {
      processNextTask();
    } else if (autoScanEnabled) {
      scheduleNextAutoScan();
    }
  }
}

function handleIncomingMessage(msg) {
  const chatId = String((msg.chat && msg.chat.id) || '');
  const text = (msg.text || '').trim();

  // Filter Keamanan Whitelist Pemilik
  if (chatId !== ALLOWED_CHAT_ID) {
    console.warn(`⛔ Pesan ditolak dari Chat ID asing: ${chatId}`);
    sendMessage(chatId, '⛔ <i>Akses ditolak. Bot privat khusus Tuan Ciro.</i>');
    return;
  }

  if (!text) return;
  console.log(`📩 Pesan dari Tuan Ciro: "${text}"`);
  const lower = text.toLowerCase();

  if (lower === '/start' || lower === '/help' || lower === 'help' || lower === 'menu') {
    sendMessage(chatId, getHelpText());
    return;
  }

  if (lower.startsWith('/auto') || lower.startsWith('/loop')) {
    const parts = text.split(/\s+/);
    const sub = parts[1] ? parts[1].toLowerCase() : '';
    if (sub === 'off' || sub === 'stop') {
      autoScanEnabled = false;
      if (autoScanTimer) { clearTimeout(autoScanTimer); autoScanTimer = null; }
      sendMessage(chatId, '🛑 <b>Auto-Scan Dinonaktifkan.</b> Bot kembali ke mode manual.');
      return;
    }
    if (sub === 'on' || sub === 'start' || !sub) {
      autoScanEnabled = true;
      sendMessage(chatId, [
        '🔄 <b>Auto-Scan Diaktifkan!</b>',
        `🎯 Mode: <code>${autoScanMode}</code>`,
        `⏱️ Jeda Antar Ronde: <code>${autoScanInterval}s</code>`,
        '',
        '<i>Bot akan memindai secara terus-menerus 24/7 tanpa henti. Ketik <code>/auto off</code> untuk mematikan.</i>',
      ].join('\n'));
      if (!isBusy && taskQueue.length === 0) {
        scheduleNextAutoScan();
      }
      return;
    }
    if (sub === 'feed' || sub === 'dork') {
      autoScanMode = sub;
      autoScanEnabled = true;
      sendMessage(chatId, `🔄 <b>Auto-Scan diset ke mode:</b> <code>${autoScanMode}</code> (Aktif)`);
      if (!isBusy && taskQueue.length === 0) {
        scheduleNextAutoScan();
      }
      return;
    }
    const num = parseInt(sub, 10);
    if (!isNaN(num) && num >= 10) {
      autoScanInterval = num;
      sendMessage(chatId, `⏱️ <b>Jeda Auto-Scan diubah menjadi:</b> <code>${autoScanInterval} detik</code>.`);
      return;
    }
    sendMessage(chatId, [
      'ℹ️ <b>Format Perintah Auto-Scan:</b>',
      '• <code>/auto on</code> — Nyalakan auto-scan terus-menerus (mode feed)',
      '• <code>/auto off</code> — Matikan auto-scan',
      '• <code>/auto feed</code> — Set auto-scan mode feed publik',
      '• <code>/auto dork</code> — Set auto-scan mode dork code search',
      '• <code>/auto 60</code> — Ubah jeda antar ronde (detik)',
    ].join('\n'));
    return;
  }

  if (lower === '/status') {
    const autoStatus = autoScanEnabled
      ? `AKTIF (mode: <code>${autoScanMode}</code>, tiap <code>${autoScanInterval}s</code>)`
      : 'NONAKTIF';

    if (isBusy && currentTargetLabel) {
      const dur = Math.round((Date.now() - taskStartTime) / 1000);
      sendMessage(chatId, [
        '⚡ <b>STATUS CIRO-SCAN BOT:</b>',
        '────────────────────────────',
        `🔄 <b>Sedang Memindai:</b> <code>${currentTargetLabel}</code>`,
        `⏱️ <b>Durasi:</b> ${dur} detik`,
        `📦 <b>Antrean Menunggu:</b> ${taskQueue.length} tugas`,
        `🔁 <b>Auto-Scan (24/7):</b> ${autoStatus}`,
      ].join('\n'));
    } else {
      sendMessage(chatId, [
        '💤 <b>STATUS CIRO-SCAN BOT:</b>',
        '────────────────────────────',
        '✨ <b>Status:</b> IDLE (Siaga menerima target baru)',
        `📦 <b>Antrean Menunggu:</b> ${taskQueue.length} tugas`,
        `🔁 <b>Auto-Scan (24/7):</b> ${autoStatus}`,
      ].join('\n'));
    }
    return;
  }

  if (lower === '/stop') {
    if (autoScanEnabled) {
      autoScanEnabled = false;
      if (autoScanTimer) { clearTimeout(autoScanTimer); autoScanTimer = null; }
      sendMessage(chatId, '🛑 <i>Auto-Scan otomatis dinonaktifkan.</i>');
    }

    if (currentProcess && !currentProcess.killed) {
      try {
        currentProcess.kill('SIGTERM');
        sendMessage(chatId, `🛑 <i>Membatalkan pemindaian aktif:</i> <code>${currentTargetLabel}</code>...`);
        setTimeout(() => {
          if (currentProcess && !currentProcess.killed) {
            currentProcess.kill('SIGKILL');
          }
        }, 3000);
      } catch (e) {
        sendMessage(chatId, `⚠️ Gagal menghentikan proses: ${e.message}`);
      }
    } else {
      sendMessage(chatId, 'ℹ️ Tidak ada pemindaian yang sedang berjalan.');
    }
    return;
  }

  // Parsing target dan opsi pencarian bebas
  let targetInput = text;
  let searchKw = '';

  if (text.includes('-bebas')) {
    const parts = text.split('-bebas');
    targetInput = parts[0].trim();
    searchKw = parts.slice(1).join('-bebas').trim();
  }

  if (targetInput.startsWith('/')) {
    targetInput = targetInput.slice(1).trim();
  }

  const kwInfo = searchKw ? ` (Pencarian teks: <code>${searchKw}</code>)` : '';

  if (isBusy) {
    taskQueue.push({ chatId, targetInput, searchKw });
    sendMessage(chatId, [
      `⏳ <b>Ditambahkan ke Antrean (#${taskQueue.length}):</b>`,
      `🎯 <b>Target:</b> <code>${targetInput}</code>${kwInfo}`,
      '',
      '<i>Tugas akan otomatis dieksekusi setelah pemindaian sebelumnya selesai.</i>',
    ].join('\n'));
  } else {
    taskQueue.push({ chatId, targetInput, searchKw });
    sendMessage(chatId, [
      '🚀 <b>Permintaan Diterima:</b>',
      `🎯 <b>Target:</b> <code>${targetInput}</code>${kwInfo}`,
      '',
      '<i>Menyiapkan engine scanner...</i>',
    ].join('\n'));
    processNextTask();
  }
}

// 7. Loop Polling Telegram
async function startBot() {
  try {
    const me = await telegramRequest('getMe');
    if (me && me.ok) {
      console.log(`✅ Bot Telegram Online: @${me.result.username}`);
      sendMessage(ALLOWED_CHAT_ID, `🚀 <b>Ciro-Scan Bot Online!</b> (@${me.result.username})\n<i>Siaga menerima target di Pterodactyl Node.js VPS. Ketik /help untuk panduan.</i>`);
    } else {
      console.warn('⚠️ getMe response:', me);
    }
  } catch (e) {
    console.error('⚠️ Gagal menghubungi Telegram saat startup:', e.message);
  }

  // Buang pending updates lama agar tidak menumpuk saat start
  try {
    await telegramRequest('getUpdates', { offset: -1 });
  } catch (e) {}

  let offset = null;
  console.log('👂 Menunggu pesan masuk dari Telegram (Long Polling)...');

  while (true) {
    try {
      const params = { timeout: 25 };
      if (offset !== null) params.offset = offset;

      const res = await telegramRequest('getUpdates', params);
      if (res && res.ok && Array.isArray(res.result)) {
        for (const update of res.result) {
          offset = update.update_id + 1;
          if (update.message) {
            handleIncomingMessage(update.message);
          }
        }
      }
    } catch (e) {
      // Tunggu 3 detik jika error jaringan
      await new Promise((r) => setTimeout(r, 3000));
    }
  }
}

startBot().catch((err) => {
  console.error('Fatal crash pada bot:', err);
  process.exit(1);
});

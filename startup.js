'use strict';
/**
 * startup.js — Entrypoint & Telegram Bot Daemon ciro-scan untuk Pterodactyl VPS (Node.js Egg)
 * Mendukung standar: npm install && npm start (atau node startup.js)
 *
 * Fitur Utama:
 * 1. Zero external npm dependencies — Native HTTPS & Node.js Crypto.
 * 2. In-Memory Vault: GitHub PAT disimpan terenkripsi AES-256-GCM di secrets.enc,
 *    hanya didekripsi ke RAM dan di-inject ke memory child process saat scan.
 * 3. Multi-PAT Auto-Rolling: Mendukung fallback otomatis jika salah satu token kena limit.
 * 4. Auto-Scan 24/7 Loop: Pemindaian terus menerus tanpa henti dengan configurable interval.
 * 5. Task Queue FIFO: Mencegah tabrakan pemindaian bersamaan.
 */

const fs = require('fs');
const path = require('path');
const https = require('https');
const crypto = require('crypto');
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

// 3. Verifikasi & Pasang TruffleHog jika belum ada
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

// ============================================================================
// 5. In-Memory Vault (AES-256-GCM + scrypt) — Zero Plaintext PAT on Disk
// ============================================================================
const VAULT_FILE = path.join(__dirname, 'secrets.enc');
const VAULT_KEY = (process.env.VAULT_KEY || 'ciro_scan_vault_key_2026_aes_gcm').trim();
let inMemoryPats = [];

function encryptVault(dataObj, masterKey) {
  const salt = crypto.randomBytes(16);
  const iv = crypto.randomBytes(12);
  const key = crypto.scryptSync(masterKey, salt, 32);
  const cipher = crypto.createCipheriv('aes-256-gcm', key, iv);
  let enc = cipher.update(JSON.stringify(dataObj), 'utf8', 'hex');
  enc += cipher.final('hex');
  const tag = cipher.getAuthTag();
  return {
    salt: salt.toString('hex'),
    iv: iv.toString('hex'),
    tag: tag.toString('hex'),
    data: enc,
  };
}

function decryptVault(vaultObj, masterKey) {
  const salt = Buffer.from(vaultObj.salt, 'hex');
  const iv = Buffer.from(vaultObj.iv, 'hex');
  const tag = Buffer.from(vaultObj.tag, 'hex');
  const key = crypto.scryptSync(masterKey, salt, 32);
  const decipher = crypto.createDecipheriv('aes-256-gcm', key, iv);
  decipher.setAuthTag(tag);
  let dec = decipher.update(vaultObj.data, 'hex', 'utf8');
  dec += decipher.final('utf8');
  return JSON.parse(dec);
}

function loadVault() {
  if (fs.existsSync(VAULT_FILE)) {
    try {
      const raw = JSON.parse(fs.readFileSync(VAULT_FILE, 'utf8'));
      const decrypted = decryptVault(raw, VAULT_KEY);
      if (decrypted && Array.isArray(decrypted.pats)) {
        inMemoryPats = decrypted.pats.filter(p => typeof p === 'string' && p.trim().length > 0);
        console.log(`🔐 [Vault] Berhasil mendekripsi & memuat ${inMemoryPats.length} GitHub PAT ke RAM.`);
      }
    } catch (e) {
      console.warn('⚠️ [Vault] Gagal membaca/mendekripsi secrets.enc:', e.message);
    }
  }

  // Fallback membaca environment jika vault belum ada
  if (inMemoryPats.length === 0) {
    const envPats = [];
    if (process.env.GH_PAT) envPats.push(...process.env.GH_PAT.split(','));
    for (const k of ['GH_PAT_1', 'GH_PAT_2', 'GH_PAT_3']) {
      if (process.env[k]) envPats.push(process.env[k]);
    }
    inMemoryPats = Array.from(new Set(envPats.map(p => p.trim()).filter(Boolean)));
    if (inMemoryPats.length > 0) {
      console.log(`🔑 [Vault] Memuat ${inMemoryPats.length} PAT dari environment server ke RAM.`);
    }
  }
}

function saveVault(pats) {
  inMemoryPats = pats.filter(p => typeof p === 'string' && p.trim().length > 0);
  const encrypted = encryptVault({ pats: inMemoryPats }, VAULT_KEY);
  fs.writeFileSync(VAULT_FILE, JSON.stringify(encrypted, null, 2), 'utf8');
  console.log(`💾 [Vault] Berhasil menyimpan terenkripsi ke secrets.enc (${inMemoryPats.length} token di RAM).`);
}

// Inisialisasi Vault saat boot
loadVault();

// ============================================================================
// 6. Telegram API Client (Native HTTPS, Zero External Dependency)
// ============================================================================
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
  const patCount = inMemoryPats.length;
  const rateLimitStr = patCount > 0 ? `${patCount * 5000} req/jam` : '60 req/jam (anonim)';

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
    '🔐 <b>7. Manajemen GitHub PAT (In-Memory RAM):</b>',
    `• <code>/pats</code> — Cek status & rolling token (${patCount} aktif, ${rateLimitStr})`,
    '• <code>/set_pat token1 token2 ...</code> — Simpan PAT terenkripsi AES-256-GCM',
    '• <code>/clear_pat</code> — Hapus seluruh PAT dari RAM & disk\n',
    '<b>Perintah Kontrol:</b>',
    '• <code>/status</code> — Cek status pemindaian, auto-scan & antrean',
    '• <code>/stop</code> — Batalkan proses yang sedang berjalan',
    '• <code>/help</code> — Buka panduan ini kembali',
  ].join('\n');
}

// ============================================================================
// 7. Sistem Antrean (Task Queue FIFO) & Eksekusi Proses
// ============================================================================
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

  // Suntikkan environment variabel, termasuk token PAT murni dari RAM ke memory child process
  const env = Object.assign({}, process.env, {
    TARGET_URL: targetInput,
    TELEGRAM_BOT_TOKEN: BOT_TOKEN,
    TELEGRAM_CHAT_ID: ALLOWED_CHAT_ID,
    PATH: `${BIN_DIR}:${process.env.PATH || ''}`,
  });

  if (inMemoryPats.length > 0) {
    env.GH_PAT = inMemoryPats.join(',');
    inMemoryPats.forEach((pat, idx) => {
      env[`GH_PAT_${idx + 1}`] = pat;
    });
  }

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

// ============================================================================
// 8. Handler Pesan Masuk
// ============================================================================
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

  // Menu Help
  if (lower === '/start' || lower === '/help' || lower === 'help' || lower === 'menu') {
    sendMessage(chatId, getHelpText());
    return;
  }

  // Token Vault Commands
  if (lower === '/pats' || lower === '/tokens' || lower === '/token') {
    if (inMemoryPats.length === 0) {
      sendMessage(chatId, [
        '🔐 <b>Status GitHub PAT di RAM:</b>',
        '⚠️ <i>Belum ada token GitHub PAT yang tersimpan di RAM.</i>',
        '',
        'Gunakan perintah <code>/set_pat &lt;token1&gt; &lt;token2&gt; &lt;token3&gt;</code> untuk menyimpan token secara aman ke RAM (dienkripsi ke secrets.enc).',
      ].join('\n'));
      return;
    }
    const lines = [
      '🔐 <b>Status GitHub PAT di RAM (Terenkripsi AES-256-GCM di Disk):</b>',
      '────────────────────────────',
      `📊 <b>Total Token:</b> ${inMemoryPats.length} PAT aktif`,
      `⚡ <b>Kapasitas Rate Limit Gabungan:</b> ${inMemoryPats.length * 5000} req/jam`,
      `🔄 <b>Mode Rolling / Fallback:</b> Otomatis rotasi jika token kena 403 / 429`,
      '',
    ];
    inMemoryPats.forEach((p, i) => {
      const masked = p.length > 10 ? `${p.slice(0, 7)}...${p.slice(-4)}` : '***';
      lines.push(`• PAT #${i + 1}: <code>${masked}</code> (Siap di RAM)`);
    });
    lines.push('');
    lines.push('💡 <i>Token tersimpan terenkripsi penuh di secrets.enc dan hanya berada di RAM saat bot berjalan.</i>');
    sendMessage(chatId, lines.join('\n'));
    return;
  }

  if (lower.startsWith('/set_pat') || lower.startsWith('/setpat')) {
    const rawArgs = text.replace(/^\/(set_pat|setpat)/i, '').trim();
    const newTokens = rawArgs.split(/[\s,]+/).map(t => t.trim()).filter(t => t.startsWith('ghp_') || t.startsWith('github_pat_'));
    if (newTokens.length === 0) {
      sendMessage(chatId, [
        '⚠️ <b>Format Token Tidak Valid!</b>',
        'Kirim token GitHub PAT yang valid (diawali <code>ghp_</code> atau <code>github_pat_</code>):',
        '👉 <code>/set_pat ghp_token1 ghp_token2 ghp_token3</code>',
      ].join('\n'));
      return;
    }
    saveVault(newTokens);
    sendMessage(chatId, [
      '✅ <b>Berhasil Menyimpan PAT Baru!</b>',
      `🔒 <b>Jumlah Token di RAM:</b> ${inMemoryPats.length} PAT`,
      `⚡ <b>Total Kapasitas:</b> ${inMemoryPats.length * 5000} req/jam`,
      '🛡️ <i>Token langsung dienkripsi AES-256-GCM ke secrets.enc dan disiagakan di RAM.</i>',
    ].join('\n'));
    return;
  }

  if (lower === '/clear_pat' || lower === '/clearpat') {
    inMemoryPats = [];
    if (fs.existsSync(VAULT_FILE)) {
      try { fs.unlinkSync(VAULT_FILE); } catch (e) {}
    }
    sendMessage(chatId, '🗑️ <b>Semua GitHub PAT telah dihapus dari RAM dan berkas secrets.enc.</b>');
    return;
  }

  // Auto-Scan Commands
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
        '🔄 <b>Auto-Scan 24/7 Diaktifkan!</b>',
        `🎯 Mode: <code>${autoScanMode}</code>`,
        `⏱️ Jeda Antar Ronde: <code>${autoScanInterval}s</code>`,
        `🔐 Multi-PAT: <code>${inMemoryPats.length} token aktif</code> (${inMemoryPats.length * 5000} req/jam)`,
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
      sendMessage(chatId, `🔄 <b>Auto-Scan diset ke mode:</b> <code>${autoScanMode}</code> (Aktif 24/7)`);
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
      '• <code>/auto on</code> — Nyalakan auto-scan terus-menerus (24/7)',
      '• <code>/auto off</code> — Matikan auto-scan',
      '• <code>/auto feed</code> — Set auto-scan mode feed publik',
      '• <code>/auto dork</code> — Set auto-scan mode dork code search',
      '• <code>/auto 60</code> — Ubah jeda antar ronde (detik)',
    ].join('\n'));
    return;
  }

  // Status
  if (lower === '/status') {
    const autoStatus = autoScanEnabled
      ? `AKTIF (mode: <code>${autoScanMode}</code>, tiap <code>${autoScanInterval}s</code>)`
      : 'NONAKTIF';

    const patStatus = inMemoryPats.length > 0
      ? `${inMemoryPats.length} token di RAM (${inMemoryPats.length * 5000} req/jam)`
      : 'Anonim (0 token di RAM)';

    if (isBusy && currentTargetLabel) {
      const dur = Math.round((Date.now() - taskStartTime) / 1000);
      sendMessage(chatId, [
        '⚡ <b>STATUS CIRO-SCAN BOT:</b>',
        '────────────────────────────',
        `🔄 <b>Sedang Memindai:</b> <code>${currentTargetLabel}</code>`,
        `⏱️ <b>Durasi:</b> ${dur} detik`,
        `📦 <b>Antrean Menunggu:</b> ${taskQueue.length} tugas`,
        `🔁 <b>Auto-Scan (24/7):</b> ${autoStatus}`,
        `🔐 <b>GitHub PAT di RAM:</b> ${patStatus}`,
      ].join('\n'));
    } else {
      sendMessage(chatId, [
        '💤 <b>STATUS CIRO-SCAN BOT:</b>',
        '────────────────────────────',
        '✨ <b>Status:</b> IDLE (Siaga menerima target baru)',
        `📦 <b>Antrean Menunggu:</b> ${taskQueue.length} tugas`,
        `🔁 <b>Auto-Scan (24/7):</b> ${autoStatus}`,
        `🔐 <b>GitHub PAT di RAM:</b> ${patStatus}`,
      ].join('\n'));
    }
    return;
  }

  // Stop / Cancel Current Task
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

// ============================================================================
// 9. Loop Polling Telegram
// ============================================================================
async function startBot() {
  try {
    const me = await telegramRequest('getMe');
    if (me && me.ok) {
      console.log(`✅ Bot Telegram Online: @${me.result.username}`);
      sendMessage(ALLOWED_CHAT_ID, [
        `🚀 <b>Ciro-Scan Bot Online!</b> (@${me.result.username})`,
        `🔐 <b>RAM Vault:</b> ${inMemoryPats.length} GitHub PAT aktif (${inMemoryPats.length * 5000} req/jam)`,
        `🔁 <b>Auto-Scan:</b> ${autoScanEnabled ? 'AKTIF (24/7)' : 'Siaga (ketik /auto on)'}`,
        '',
        '<i>Siaga menerima target di Pterodactyl Node.js VPS. Ketik /help untuk daftar perintah.</i>',
      ].join('\n'));
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

  // Jika autoScanEnabled bernilai true dari env, jadwalkan ronde awal
  if (autoScanEnabled && !isBusy && taskQueue.length === 0) {
    scheduleNextAutoScan();
  }

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
      // Tunggu 3 detik jika terjadi gangguan jaringan
      await new Promise((r) => setTimeout(r, 3000));
    }
  }
}

startBot().catch((err) => {
  console.error('Fatal crash pada bot:', err);
  process.exit(1);
});

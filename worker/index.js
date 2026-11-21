/**
 * Cloudflare Worker: Telegram Webhook & Web API Dispatcher for TruffleHog
 *
 * Environment Variables / Secrets required in Cloudflare Worker:
 * - TELEGRAM_BOT_TOKEN : Token bot telegram (<YOUR_TELEGRAM_BOT_TOKEN>)
 * - GH_PAT             : GitHub Personal Access Token yang punya hak akses repo workflow
 * - GH_OWNER           : Akun GitHub (ciroxtreme)
 * - GH_REPO            : Nama repo (ciro-scan)
 * - ALLOWED_CHAT_ID    : ID Telegram Tuan Ciro (1936436999)
 */

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // 1. Endpoint HTTP GET/POST sederhana untuk scan via web browser / curl
    // Contoh: https://worker.dev/scan?url=https://github.com/target/repo
    // Pencarian teks bebas: https://worker.dev/scan?url=https://github.com/owner&keyword=password
    if (url.pathname === "/scan") {
      const targetUrl = url.searchParams.get("url");
      const keyword = url.searchParams.get("keyword") || "";
      if (!targetUrl) {
        return new Response("Missing 'url' parameter", { status: 400 });
      }
      const triggered = await triggerGitHubScan(targetUrl, env, keyword);
      if (triggered.ok) {
        return new Response(`🚀 Scan berhasil dipicu untuk: ${targetUrl}. Pantau hasil di Telegram!\n`);
      } else {
        return new Response(`❌ Gagal trigger GitHub Actions: ${triggered.error}\n`, { status: 500 });
      }
    }

    // 2. Webhook Telegram Bot (@Dicopi_bot)
    // Tuan Ciro tinggal chat link github langsung ke bot
    if (request.method === "POST") {
      try {
        const update = await request.json();
        if (update.message && update.message.text) {
          const chatId = String(update.message.chat.id);
          const text = update.message.text.trim();

          // Validasi keamanan: hanya proses chat dari Tuan Ciro
          if (env.ALLOWED_CHAT_ID && chatId !== String(env.ALLOWED_CHAT_ID)) {
            return new Response("Unauthorized", { status: 403 });
          }

          // Cek apakah pesan berisi link GitHub / git
          // Format bebas: <url> [-bebas <kata kunci>] — contoh:
          //   https://github.com/ciroxtreme/cdtt
          //   https://github.com/ciroxtreme -bebas password
          if (text === "feed" || text === "@feed" || text === "auto" || text === "/feed") {
            await sendTelegram(chatId, `🛰️ Memicu scan feed global (repo orang aktif terbaru)...`, env);
            const res = await triggerGitHubScan("feed", env, "");
            if (!res.ok) {
              await sendTelegram(chatId, `❌ Gagal memicu GitHub runner: <code>${esc(res.error)}</code>`, env);
            }
          } else if (text.startsWith("http://") || text.startsWith("https://") || text.startsWith("git@")) {
            const parts = text.split(/\s+/);
            const targetUrl = parts[0];
            let keyword = "";
            const flagIdx = parts.findIndex((p) => p === "-bebas");
            if (flagIdx !== -1 && parts[flagIdx + 1]) {
              keyword = parts.slice(flagIdx + 1).join(" ");
            }
            const modeText = keyword
              ? `🔍 Mode pencarian teks bebas: <code>${esc(keyword)}</code>`
              : `🚀 Memicu GitHub Actions TruffleHog Scanner...`;
            await sendTelegram(chatId, `🎯 Menerima URL: <code>${esc(targetUrl)}</code>\n${modeText}`, env);
            const res = await triggerGitHubScan(targetUrl, env, keyword);
            if (!res.ok) {
              await sendTelegram(chatId, `❌ Gagal memicu GitHub runner: <code>${esc(res.error)}</code>`, env);
            }
          } else if (text === "/start") {
            await sendTelegram(chatId, `👋 Halo Tuan Ciro! 🐷\n\nKirimkan saja link repositori Git (contoh: <code>https://github.com/user/repo</code>) langsung ke chat ini.\n\nSaya akan otomatis memicu TruffleHog runner dan mengirimkan hasil audit bocoran token beserta file JSON-nya ke sini!\n\n🔍 Mau cari kata bebas? Tambah <code>-bebas &lt;kata&gt;</code>, contoh:\n<code>https://github.com/ciroxtreme -bebas password</code>\n\n🛰️ Ketik <code>feed</code> buat scan feed global (50 repo orang aktif terbaru, otomatis).`, env);
          } else {
            await sendTelegram(chatId, `⚠️ Format salah. Kirimkan link URL Git yang valid (diawali https://github.com/...).`, env);
          }
        }
      } catch (err) {
        console.error("Worker error:", err);
      }
      return new Response("OK");
    }

    return new Response("Ciro TruffleHog Scanner Relay Worker Active! 🐷");
  }
};

function esc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

async function triggerGitHubScan(targetUrl, env, searchKeyword = "") {
  const owner = env.GH_OWNER || "ciroxtreme";
  const repo = env.GH_REPO || "ciro-scan";
  const workflow = "scan.yml";
  const url = `https://api.github.com/repos/${owner}/${repo}/actions/workflows/${workflow}/dispatches`;

  try {
    const res = await fetch(url, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${env.GH_PAT}`,
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Cloudflare-Worker-CiroScan"
      },
      body: JSON.stringify({
        ref: "main",
        inputs: {
          target_url: targetUrl,
          search_keyword: searchKeyword || ""
        }
      })
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

async function sendTelegram(chatId, htmlText, env) {
  const token = env.TELEGRAM_BOT_TOKEN;
  if (!token) return;
  const url = `https://api.telegram.org/bot${token}/sendMessage`;
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
}

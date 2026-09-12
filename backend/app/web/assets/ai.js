let lastError = null;
let loadedHistory = false;
let sending = false;
let lastAppPage = null;
let resizing = false;

const SIZE_KEY = "finup_ai_size";
const MIN_W = 280;
const MIN_H = 300;

export function rememberApiError(err) {
  if (!err || typeof err !== "object") return;
  lastError = {
    status: err.status || 0,
    message: String(err.message || "").slice(0, 300),
    path: String(err.path || "").slice(0, 120),
    at: new Date().toISOString(),
  };
}

function token() {
  return localStorage.getItem("finup_pos_token") || "";
}

function currentPage() {
  const hash = location.hash || "";
  if (hash.startsWith("#/app/")) return (hash.split("/")[2] || "dashboard").split("?")[0];
  if (hash.startsWith("#/login")) return "login";
  if (hash.startsWith("#/register")) return "register";
  if (hash.startsWith("#/platform")) return "platform";
  return "home";
}

function shouldShow() {
  return Boolean(token()) && (location.hash || "").startsWith("#/app");
}

async function aiFetch(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...(token() ? { Authorization: "Bearer " + token() } : {}),
      ...(opts.headers || {}),
    },
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const msg = typeof data.detail === "string" ? data.detail : data.message || "AI xatolik";
    throw new Error(msg);
  }
  return data;
}

function el(html) {
  const d = document.createElement("div");
  d.innerHTML = html.trim();
  return d.firstElementChild;
}

function bubble(role, text) {
  const node = document.createElement("div");
  node.className = "ai-msg ai-msg-" + role;
  node.textContent = text;
  return node;
}

function isMobile() {
  return window.matchMedia("(max-width: 640px)").matches;
}

function loadSize() {
  try {
    const s = JSON.parse(localStorage.getItem(SIZE_KEY) || "");
    if (s && Number(s.w) >= MIN_W && Number(s.h) >= MIN_H) return { w: Number(s.w), h: Number(s.h) };
  } catch (e) {
    /* ignore */
  }
  return null;
}

function saveSize(w, h) {
  try {
    localStorage.setItem(SIZE_KEY, JSON.stringify({ w: Math.round(w), h: Math.round(h) }));
  } catch (e) {
    /* ignore */
  }
}

function applySize(panel) {
  if (!panel || isMobile()) return;
  const s = loadSize();
  if (!s) return;
  const maxW = Math.max(MIN_W, window.innerWidth - 24);
  const maxH = Math.max(MIN_H, window.innerHeight - 100);
  panel.style.width = Math.min(s.w, maxW) + "px";
  panel.style.height = Math.min(s.h, maxH) + "px";
}

function collapsePanel() {
  const panel = document.getElementById("finex-ai-panel");
  if (panel) {
    panel.hidden = true;
    panel.setAttribute("hidden", "");
  }
  const btn = document.getElementById("finex-ai-toggle");
  if (btn) btn.setAttribute("aria-expanded", "false");
}

function openPanel() {
  const panel = document.getElementById("finex-ai-panel");
  if (!panel) return;
  applySize(panel);
  panel.hidden = false;
  panel.removeAttribute("hidden");
  const btn = document.getElementById("finex-ai-toggle");
  if (btn) btn.setAttribute("aria-expanded", "true");
  loadHistory();
  const input = document.getElementById("finex-ai-input");
  if (input) input.focus();
}

function bindResize(panel) {
  const handle = document.getElementById("finex-ai-resize");
  if (!handle || !panel) return;
  handle.addEventListener("pointerdown", (e) => {
    if (isMobile()) return;
    e.preventDefault();
    resizing = true;
    handle.setPointerCapture(e.pointerId);
    const startX = e.clientX;
    const startY = e.clientY;
    const startW = panel.getBoundingClientRect().width;
    const startH = panel.getBoundingClientRect().height;
    const onMove = (ev) => {
      if (!resizing) return;
      const maxW = Math.max(MIN_W, window.innerWidth - 24);
      const maxH = Math.max(MIN_H, window.innerHeight - 100);
      const w = Math.min(maxW, Math.max(MIN_W, startW + (startX - ev.clientX)));
      const h = Math.min(maxH, Math.max(MIN_H, startH + (startY - ev.clientY)));
      panel.style.width = w + "px";
      panel.style.height = h + "px";
    };
    const onUp = (ev) => {
      resizing = false;
      handle.releasePointerCapture(ev.pointerId);
      handle.removeEventListener("pointermove", onMove);
      handle.removeEventListener("pointerup", onUp);
      const box = panel.getBoundingClientRect();
      saveSize(box.width, box.height);
    };
    handle.addEventListener("pointermove", onMove);
    handle.addEventListener("pointerup", onUp);
  });
}

function ensureWidget() {
  if (document.getElementById("finex-ai-root")) return;
  const root = el(`
    <div id="finex-ai-root" hidden>
      <button type="button" id="finex-ai-toggle" class="ai-fab" aria-label="AI yordamchi" aria-expanded="false">AI</button>
      <section id="finex-ai-panel" class="ai-panel" hidden>
        <button type="button" id="finex-ai-resize" class="ai-resize" aria-label="O'lchamini o'zgartirish"></button>
        <header class="ai-head">
          <div>
            <div class="kicker">FINEX POS</div>
            <strong>AI yordamchi</strong>
          </div>
          <div class="ai-head-actions">
            <button type="button" class="btn btn-ghost btn-sm" id="finex-ai-clear">Tozalash</button>
            <button type="button" class="btn btn-ghost btn-sm" id="finex-ai-close">Yopish</button>
          </div>
        </header>
        <div id="finex-ai-status" class="ai-status muted"></div>
        <div id="finex-ai-log" class="ai-log"></div>
        <p id="finex-ai-err" class="err ai-err" hidden></p>
        <form id="finex-ai-form" class="ai-form">
          <textarea id="finex-ai-input" class="field" rows="2" placeholder="Savol yozing..." maxlength="2000"></textarea>
          <div class="ai-form-row">
            <button type="submit" class="btn btn-gold" id="finex-ai-send">Yuborish</button>
            <button type="button" class="btn btn-ghost" id="finex-ai-report">Xatoni yuborish</button>
          </div>
        </form>
      </section>
    </div>`);
  document.body.appendChild(root);

  document.getElementById("finex-ai-toggle").onclick = () => {
    const panel = document.getElementById("finex-ai-panel");
    if (!panel) return;
    if (panel.hidden) openPanel();
    else collapsePanel();
  };
  document.getElementById("finex-ai-close").onclick = () => collapsePanel();
  document.getElementById("finex-ai-form").onsubmit = (e) => {
    e.preventDefault();
    sendChat();
  };
  document.getElementById("finex-ai-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendChat();
    }
  });
  document.getElementById("finex-ai-clear").onclick = clearHistory;
  document.getElementById("finex-ai-report").onclick = reportProblem;
  bindResize(document.getElementById("finex-ai-panel"));
}

function setErr(msg) {
  const box = document.getElementById("finex-ai-err");
  if (!box) return;
  if (!msg) {
    box.hidden = true;
    box.textContent = "";
    return;
  }
  box.hidden = false;
  box.textContent = msg;
}

async function loadHistory() {
  if (loadedHistory) return;
  const log = document.getElementById("finex-ai-log");
  try {
    const st = await aiFetch("/api/ai/status");
    const stEl = document.getElementById("finex-ai-status");
    if (stEl) {
      stEl.textContent = st.online
        ? "Model: " + (st.model || st.provider)
        : "AI model ulanmagan — AI_API_KEY kerak";
    }
    const data = await aiFetch("/api/ai/history");
    log.innerHTML = "";
    (data.messages || []).forEach((m) => log.appendChild(bubble(m.role === "user" ? "user" : "bot", m.content || "")));
    if (!(data.messages || []).length) {
      log.appendChild(
        bubble(
          "bot",
          "Salom! FINEX POS bo'yicha savol bering. Masalan: yangi tovar qanday qo'shiladi, savdo qanday qilinadi, qoldiq qayerda.",
        ),
      );
    }
    loadedHistory = true;
    log.scrollTop = log.scrollHeight;
  } catch (e) {
    setErr(e.message || "Tarix yuklanmadi");
  }
}

function contextPayload() {
  return {
    page: currentPage(),
    module: currentPage(),
    last_error: lastError,
  };
}

async function sendChat() {
  if (sending) return;
  const input = document.getElementById("finex-ai-input");
  const text = (input.value || "").trim();
  if (!text) return;
  const log = document.getElementById("finex-ai-log");
  const sendBtn = document.getElementById("finex-ai-send");
  setErr("");
  log.appendChild(bubble("user", text));
  input.value = "";
  sending = true;
  sendBtn.disabled = true;
  sendBtn.textContent = "Yozilmoqda...";
  const wait = bubble("bot", "Kuting...");
  wait.classList.add("ai-pending");
  log.appendChild(wait);
  log.scrollTop = log.scrollHeight;
  try {
    const data = await aiFetch("/api/ai/chat", {
      method: "POST",
      body: JSON.stringify({ message: text, context: contextPayload() }),
    });
    wait.classList.remove("ai-pending");
    wait.textContent = data.answer || "Javob yo'q";
    wait.dataset.lastQ = text;
    wait.dataset.lastA = data.answer || "";
  } catch (e) {
    wait.classList.remove("ai-pending");
    wait.textContent = e.message || "AI hozir javob bera olmadi. POS ishlashda davom etadi.";
    setErr(e.message || "AI xatolik");
  } finally {
    sending = false;
    sendBtn.disabled = false;
    sendBtn.textContent = "Yuborish";
    log.scrollTop = log.scrollHeight;
  }
}

async function clearHistory() {
  try {
    await aiFetch("/api/ai/history", { method: "DELETE" });
    loadedHistory = false;
    const log = document.getElementById("finex-ai-log");
    log.innerHTML = "";
    await loadHistory();
  } catch (e) {
    setErr(e.message);
  }
}

async function reportProblem() {
  const log = document.getElementById("finex-ai-log");
  const lastBot = [...log.querySelectorAll(".ai-msg-bot")].pop();
  const lastUser = [...log.querySelectorAll(".ai-msg-user")].pop();
  try {
    await aiFetch("/api/ai/report", {
      method: "POST",
      body: JSON.stringify({
        question: lastUser ? lastUser.textContent : "",
        answer: lastBot ? lastBot.textContent : "",
        context: contextPayload(),
      }),
    });
    setErr("");
    log.appendChild(bubble("bot", "Xabar yuborildi. Platform egasi ko'rib chiqadi."));
    log.scrollTop = log.scrollHeight;
  } catch (e) {
    setErr(e.message || "Yuborilmadi");
  }
}

export function syncFinexAi() {
  ensureWidget();
  const root = document.getElementById("finex-ai-root");
  if (!root) return;
  const show = shouldShow();
  root.hidden = !show;
  const page = currentPage();
  if (!show) {
    collapsePanel();
    loadedHistory = false;
    lastAppPage = null;
    const log = document.getElementById("finex-ai-log");
    if (log) log.innerHTML = "";
    return;
  }
  if (lastAppPage && lastAppPage !== page) {
    collapsePanel();
  }
  lastAppPage = page;
}

function onAppHashChange() {
  if (!shouldShow()) return;
  const page = currentPage();
  if (lastAppPage && lastAppPage !== page) collapsePanel();
  lastAppPage = page;
}

window.addEventListener("hashchange", onAppHashChange);

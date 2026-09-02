let lastError = null;
let loadedHistory = false;
let sending = false;

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

function ensureWidget() {
  if (document.getElementById("finex-ai-root")) return;
  const root = el(`
    <div id="finex-ai-root" hidden>
      <button type="button" id="finex-ai-toggle" class="ai-fab" aria-label="AI yordamchi">AI</button>
      <section id="finex-ai-panel" class="ai-panel" hidden>
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
    panel.hidden = !panel.hidden;
    if (!panel.hidden) {
      loadHistory();
      document.getElementById("finex-ai-input").focus();
    }
  };
  document.getElementById("finex-ai-close").onclick = () => {
    document.getElementById("finex-ai-panel").hidden = true;
  };
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
        : "Knowledge Base (tashqi AI kaliti yo'q — lokal javob)";
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
    wait.textContent = "AI hozir javob bera olmadi. Asosiy POS ishlashda davom etadi. " + (e.message || "");
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
  if (!show) {
    const panel = document.getElementById("finex-ai-panel");
    if (panel) panel.hidden = true;
    loadedHistory = false;
  }
}

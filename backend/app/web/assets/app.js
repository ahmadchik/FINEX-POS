import { applyTheme, bindSaas, bindThemeToggle, lang, pagePlatform, pageStores, pageSuppliers, pageTransfers, setLang, t, themeToggleHtml } from "./saas.js?v=p2s6d";
import { rememberApiError, syncFinexAi } from "./ai.js?v=aiux3";

const root = document.getElementById("root");
function money(n) {
  const cur = (user()?.currency || "UZS").toUpperCase();
  const v = Number(n || 0);
  if (cur === "USD") return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(v);
  if (cur === "EUR") return new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR" }).format(v);
  if (cur === "RUB") return new Intl.NumberFormat("ru-RU", { style: "currency", currency: "RUB" }).format(v);
  if (cur === "KZT") return new Intl.NumberFormat("kk-KZ", { style: "currency", currency: "KZT" }).format(v);
  return `${v.toLocaleString("uz-UZ")} so'm`;
}
const EMPTY_STOCK_MSG = "Маҳсулотлар қўшилмаган";
const fmtDate = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso).replace("T", " ").slice(0, 16);
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
};
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function token() {
  return localStorage.getItem("finup_pos_token") || "";
}
function setAuth(data) {
  localStorage.setItem("finup_pos_token", data.access);
  localStorage.setItem("finup_pos_user", JSON.stringify(data.user));
}
function user() {
  try {
    return JSON.parse(localStorage.getItem("finup_pos_user") || "null");
  } catch {
    return null;
  }
}
function logout() {
  const imp = localStorage.getItem("finup_impersonating");
  localStorage.removeItem("finup_pos_token");
  localStorage.removeItem("finup_pos_user");
  localStorage.removeItem("finup_impersonating");
  location.hash = imp ? "#/platform" : "#/";
  render();
}

async function api(path, opts = {}) {
  const { withHeaders, headers: extraHeaders, ...rest } = opts;
  const res = await fetch(path, {
    ...rest,
    headers: {
      "Content-Type": "application/json",
      ...(token() ? { Authorization: `Bearer ${token()}` } : {}),
      ...(extraHeaders || {}),
    },
  });
  const data = await res.json().catch(() => ({}));
  if (res.status === 402) {
    if (!location.hash.includes("/settings")) location.hash = "#/app/settings";
  }
  if (!res.ok) {
    const msg = typeof data.detail === "string" ? data.detail : data.message || "Xatolik";
    rememberApiError({ path, status: res.status, message: msg });
    throw new Error(msg);
  }
  if (withHeaders) {
    return {
      data,
      headers: {
        total: Number(res.headers.get("X-Total-Count") || 0),
        page: Number(res.headers.get("X-Page") || 1),
        limit: Number(res.headers.get("X-Limit") || 0),
      },
    };
  }
  return data;
}

function can(perm) {
  return (user()?.permissions || []).includes(perm);
}

function isCompanyCabinet() {
  const u = user();
  if (!u) return false;
  if (u.cabinet) return u.cabinet === "company";
  return u.role === "OWNER" || u.role === "ADMIN";
}

function ean13Check(d12) {
  let s = 0;
  for (let i = 0; i < 12; i++) s += Number(d12[i]) * (i % 2 === 0 ? 1 : 3);
  return d12 + String((10 - (s % 10)) % 10);
}
function makeBarcode() {
  let body = "200" + String(Math.floor(Math.random() * 1e9)).padStart(9, "0");
  return ean13Check(body);
}

function nav() {
  const hash = location.hash || "#/";
  if (hash.startsWith("#/app")) return "app";
  if (hash.startsWith("#/login")) return "login";
  if (hash.startsWith("#/register")) return "register";
  if (hash.startsWith("#/platform")) return "platform";
  return "home";
}

function landing() {
  return `
    <div class="page">
      <div class="topnav">
        <div class="kicker brand-kicker"><img class="brand-mark" src="/assets/brand/finex-mark.png" alt="" />FINEX POS</div>
        <div class="links">
          <a href="#features">Imkoniyatlar</a>
          <a href="#pricing">Tariflar</a>
          <a href="#help">Yordam</a>
          <a href="#contact">Aloqa</a>
          <a href="#/platform">Platform</a>
          ${themeToggleHtml()}
          <a class="btn btn-ghost btn-sm" href="#/login">Kirish</a>
          <a class="btn btn-gold btn-sm" href="#/register">Bepul boshlash</a>
        </div>
      </div>
      <div class="hero">
        <div class="kicker">Do‘kon egasi uchun SaaS</div>
        <h1>Savdo, ombor va kassa — bitta kabinetda</h1>
        <p class="sub">Kichik va o‘rta do‘konlar, tarmoqlar uchun POS. Filial, tarif, qarz kitobi, smena, transfer, Click/Payme. 30 kun bepul sinov.</p>
        <div class="row">
          <a class="btn btn-gold" href="#/register">Do‘konni ochish</a>
          <a class="btn btn-ghost" href="#/login">Kabinetga kirish</a>
        </div>
      </div>
      <div class="grid3" id="features">
        <div class="card"><b>POS kassa</b><p class="muted">Barcode, miqdor, chegirma, naqd / karta / aralash, qarzga savdo, chek oynasi.</p></div>
        <div class="card"><b>Ombor</b><p class="muted">Ko‘p qatorli kirim, qoldiq, minimal zahira ogohlantirishi.</p></div>
        <div class="card"><b>Mijozlar</b><p class="muted">Doimiy mijoz, qarz kitobi, qarzni qaytarish.</p></div>
        <div class="card"><b>Kassa</b><p class="muted">Naqd kirim-chiqim, xarajatlar, qaytarishda kassa teskari yozuvi.</p></div>
        <div class="card"><b>Hisobot</b><p class="muted">Bugun / hafta / oy savdo, foyda, top tovarlar.</p></div>
        <div class="card"><b>Rollar</b><p class="muted">Egasi, admin, manager, kassir, omborchi — har biri o‘z ruxsati bilan.</p></div>
      </div>
      <div class="section" id="pricing">
        <div class="kicker">Tariflar</div>
        <h2>Oddiy narxlar</h2>
        <div class="plans">
          <article class="card plan">
            <div class="plan-name">FREE</div>
            <div class="price">0 so'm</div>
            <p class="muted">30 kun sinov. 1 do'kon, asosiy POS, tovarlar, cheklar.</p>
          </article>
          <article class="card plan plan-hit">
            <span class="plan-badge">Hit savdo</span>
            <div class="plan-name">PRO</div>
            <div class="price">80 000 / oy</div>
            <p class="muted">Hisobot, xodimlar, mijoz qarz, xarajatlar. Max 3 ta foydalanuvchigacha (kassir/admin).</p>
          </article>
          <article class="card plan plan-hit plan-enterprise">
            <span class="plan-badge">Filiallar</span>
            <div class="plan-name">ENTERPRISE</div>
            <ul class="plan-tiers">
              <li><b>3 ta do'kongacha — 160 000 so'm</b><span>80 000 so'm chegirma!</span></li>
              <li><b>5 ta do'kongacha — 300 000 so'm</b><span>100 000 so'm chegirma!</span></li>
            </ul>
            <p class="muted">Ko'p filial, xodim limiti, Click/Payme checkout, transfer.</p>
          </article>
          <article class="card plan">
            <div class="plan-name">VIP</div>
            <div class="price">500 000 / oy</div>
            <p class="muted">Do'konlar soni cheksiz, premium qo'llab-quvvatlash, barcha imkoniyatlar yoqilgan.</p>
          </article>
        </div>
      </div>
      <div class="section" id="help">
        <div class="kicker">Yordam</div>
        <h2>Qanday ishlatiladi</h2>
        <div class="grid3">
          <div class="card"><b>1. Ro‘yxat</b><p class="muted">Kompaniya va do‘kon ochiladi, demo tovarlar qo‘yiladi.</p></div>
          <div class="card"><b>2. Tovar va kirim</b><p class="muted">Narx, barcode, qoldiq. Yetkazib beruvchidan kirim.</p></div>
          <div class="card"><b>3. Savdo</b><p class="muted">Savatga qo‘shing, to‘lang. Chek chiqadi — chop etish ixtiyoriy.</p></div>
        </div>
      </div>
      <div class="section" id="contact">
        <div class="kicker">Aloqa</div>
        <div class="card">
          <b>FINEX</b>
          <p class="muted">Savol yoki demo uchun: pos@finex.uz · Telegram: @finex_pos</p>
          <p class="muted">Click/Payme checkout ulangan. Merchant kalit bo‘lmasa demo-to‘lov ishlaydi. Platform: #/platform</p>
        </div>
      </div>
    </div>`;
}

function authForm(kind) {
  const title = kind === "login" ? "Kirish" : "Do‘konni ochish";
  return `
    <div class="auth card">
      <div class="kicker brand-kicker" style="justify-content:space-between;width:100%"><span class="brand-kicker" style="margin:0"><img class="brand-mark" src="/assets/brand/finex-mark.png" alt="" />FINEX POS</span>${themeToggleHtml()}</div>
      <h2>${title}</h2>
      <form id="auth-form" class="grid3" style="grid-template-columns:1fr;margin-top:12px">
        ${
          kind === "register"
            ? `<input class="field" name="company_name" placeholder="Kompaniya nomi" required />
               <input class="field" name="store_name" placeholder="Do‘kon nomi" value="Asosiy do'kon" />
               <input class="field" name="full_name" placeholder="Ism familiya" required />`
            : ""
        }
        <input class="field" name="username" placeholder="Login" required />
        <input class="field" name="password" type="password" placeholder="Parol" required minlength="6" />
        <button class="btn btn-gold" type="submit">${kind === "login" ? "Kirish" : "Ro‘yxatdan o‘tish"}</button>
        <div class="err" id="auth-err"></div>
      </form>
      <p class="muted">${kind === "login" ? '<a href="#/register">Yangi do‘kon</a>' : '<a href="#/login">Akkountingiz bormi?</a>'} · <a href="#/">Bosh sahifa</a> · <a href="#/platform">Platform</a></p>
    </div>`;
}

function shell(inner) {
  const u = user();
  const page = (location.hash.split("/")[2] || "dashboard").split("?")[0];
  const items = [
    ["dashboard", t("dashboard"), "reports"],
    ["hisobotlar", t("reports"), "reports"],
    ["pos", t("pos"), "pos"],
    ["products", t("products"), "products"],
    ["stock", t("stock"), "stock"],
    ["opname", t("opname"), "stock"],
    ["transfers", t("transfers"), "stock"],
    ["sales", t("sales"), "pos"],
    ["customers", t("customers"), "customers"],
    ["cash", t("cash"), "cash"],
    ["expenses", t("expenses"), "cash"],
    ["suppliers", t("suppliers"), "suppliers"],
    ["stores", t("stores"), "stores"],
    ["staff", t("staff"), "staff"],
    ["settings", t("settings"), "settings"],
  ].filter((i) => !i[2] || can(i[2]))
    .filter((i) => isCompanyCabinet() || !["stores", "settings", "staff", "transfers"].includes(i[0]));
  const stores = (u.stores || []).filter((s) => s.is_active !== false);
  const storeSel =
    isCompanyCabinet() && stores.length > 1
      ? `<select class="field" id="store-switch" style="margin:8px 0">${stores
          .map((s) => `<option value="${s.id}" ${s.id === u.store_id ? "selected" : ""}>${esc(s.name)}</option>`)
          .join("")}</select>`
      : "";
  const warn = u.writable === false ? `<p class="err">Obuna tugagan — savdo yopiq. Billingni to‘lang.</p>` : "";
  return `
    ${localStorage.getItem("finup_impersonating") ? `<div class="impersonate-bar">Platform impersonate: ${esc(u.company_name)} · ${esc(u.username || u.full_name || "")} <button type="button" class="btn btn-sm" id="imp-exit">Platformga qaytish</button></div>` : ""}
    <div class="app">
      <aside class="side">
        <div class="kicker brand-kicker side-brand"><img class="brand-mark" src="/assets/brand/finex-mark.png" alt="FINEX" />FINEX POS</div>
        <p><b>${esc(u.company_name)}</b><br/><span class="muted">${esc(u.store_name || "")} · ${esc(u.role)} · ${esc(u.plan)}</span></p>
        ${storeSel}
        <div class="row" style="margin:8px 0;gap:4px">
          ${["uz", "ru", "en"].map((l) => `<button type="button" class="btn btn-ghost btn-sm ${lang() === l ? "active" : ""}" data-lang="${l}">${l.toUpperCase()}</button>`).join("")}
          ${themeToggleHtml()}
        </div>
        ${warn}
        ${items
          .map(
            ([id, label]) =>
              `<button class="link ${page === id ? "active" : ""}" data-go="#/app/${id}">${label}</button>`,
          )
          .join("")}
        <button class="link" id="logout">${t("logout")}</button>
      </aside>
      <section class="main">${inner}</section>
    </div>
    <div class="modal hidden" id="receipt-modal"></div>
    <div class="modal hidden" id="confirm-modal"></div>
    <div class="modal hidden" id="sale-modal"></div>
    <div class="modal hidden" id="cennik-modal"></div>
    <div class="modal hidden" id="stock-history-modal"></div>`;
}

function ico(path) {
  return `<svg class="kpi-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${path}</svg>`;
}

async function pageDashboard() {
  const d = await api("/api/reports/dashboard");
  const kpis = [
    ["Savdo", money(d.today.sales), ico('<path d="M3 3v18h18"/><path d="M7 14l4-4 4 3 6-7"/>')],
    ["Cheklar", d.today.checks, ico('<rect x="6" y="3" width="12" height="18" rx="2"/><path d="M9 8h6M9 12h6M9 16h4"/>')],
    ["Sotilgan", d.today.sold_qty, ico('<path d="M6 6h15l-1.5 9h-12z"/><path d="M6 6L5 3H2"/><circle cx="9" cy="20" r="1.5"/><circle cx="18" cy="20" r="1.5"/>')],
    ["Foyda", money(d.today.profit), ico('<path d="M12 3v18"/><path d="M8 8h5.5a3 3 0 010 6H8h6a3 3 0 010 6H8"/>')],
    ["Kassa", money(d.cash), ico('<rect x="3" y="7" width="18" height="12" rx="2"/><path d="M3 11h18"/><path d="M8 15h2"/>')],
  ];
  const top = (d.top_products || [])
    .map((p, i) => `<div class="rank-row"><span class="rank">${i + 1}</span><span>${esc(p.name)}</span><b>${p.qty}</b></div>`)
    .join("") || "<p class='muted'>Hali savdo yo‘q</p>";
  const low = (d.low_stock || []).length
    ? d.low_stock
        .map((p) => `<div class="rank-row warn"><span>${esc(p.name)}</span><b>${p.stock} / min ${p.min_stock}</b></div>`)
        .join("")
    : "<p class='ok'>Normada</p>";
  return `
    <div class="kicker">Bugungi natija</div>
    <h2>Boshqaruv paneli</h2>
    <div class="kpi">
      ${kpis
        .map(
          ([label, val, icon]) =>
            `<div class="card kpi-card"><div class="kpi-head">${icon}<span>${label}</span></div><b>${val}</b></div>`,
        )
        .join("")}
    </div>
    <div class="grid3" style="margin-top:16px">
      <div class="card">
        <b>Haftalik</b>
        <p>${money(d.week.sales)} · ${d.week.checks} chek</p>
        <p class="muted">Oylik: ${money(d.month.sales)}</p>
      </div>
      <div class="card">
        <b>Top tovarlar</b>
        <p class="muted" style="margin-top:4px">7 kun, miqdor bo‘yicha</p>
        ${top}
      </div>
      <div class="card">
        <b>Kam qoldiq</b>
        <p class="muted" style="margin-top:4px">min zahiradan past yoki teng</p>
        ${low}
      </div>
    </div>`;
}


function cennikShopName() {
  const u = user() || {};
  return (u.store_name || u.company_name || "FINEX POS").trim();
}

function cennikLabelHtml(p) {
  return `<article class="cennik-label">
    <div class="cennik-shop">${esc(cennikShopName())}</div>
    <div class="cennik-name">${esc(p.name || "")}</div>
    <svg class="cennik-barcode"></svg>
    <div class="cennik-price">Jami: ${money(p.sell_price)}</div>
  </article>`;
}

function drawCennikBarcodes(root, code) {
  const value = String(code || "").trim() || "000000";
  const nodes = root ? root.querySelectorAll("svg.cennik-barcode") : [];
  nodes.forEach((svg) => {
    if (typeof window.JsBarcode !== "function") {
      svg.outerHTML = '<div class="cennik-barcode-ph">' + esc(value) + "</div>";
      return;
    }
    try {
      window.JsBarcode(svg, value, {
        format: "CODE128",
        lineColor: "#111",
        background: "#fff",
        width: 1.2,
        height: 28,
        displayValue: true,
        fontSize: 9,
        margin: 0,
        textMargin: 1,
      });
    } catch (e) {
      try {
        window.JsBarcode(svg, value, {
          format: "CODE39",
          lineColor: "#111",
          background: "#fff",
          width: 1,
          height: 28,
          displayValue: true,
          fontSize: 9,
          margin: 0,
        });
      } catch (e2) {
        svg.insertAdjacentHTML("afterend", '<div class="cennik-barcode-ph">' + esc(value) + "</div>");
      }
    }
  });
}

function fillCennikSheet(p, qty) {
  const sheet = document.getElementById("cennik-sheet");
  const preview = document.getElementById("cennik-preview");
  const n = Math.max(1, Math.min(200, Number(qty) || 1));
  if (preview) preview.innerHTML = cennikLabelHtml(p);
  if (sheet) sheet.innerHTML = Array.from({ length: n }, () => cennikLabelHtml(p)).join("");
  drawCennikBarcodes(preview, p.barcode);
  drawCennikBarcodes(sheet, p.barcode);
}

function openCennikModal(p) {
  const modal = document.getElementById("cennik-modal");
  if (!modal || !p) return;
  modal.classList.remove("hidden");
  modal.innerHTML = `
    <div class="cennik-dialog">
      <div class="bill-head">
        <div>
          <div class="kicker">Chop etish</div>
          <h3>Cennik</h3>
        </div>
        <button type="button" class="btn btn-ghost btn-sm" id="cennik-close">Yopish</button>
      </div>
      <p class="muted">Termoetiketka 58×30 mm — ${esc(p.name || "")}</p>
      <div class="cennik-preview-wrap" id="cennik-preview"></div>
      <div class="cennik-controls">
        <label class="set-field">Soni
          <input class="field" id="cennik-qty" type="number" min="1" max="200" value="1" />
        </label>
        <button type="button" class="btn btn-excel" id="cennik-print">Chop etish</button>
      </div>
      <div id="cennik-sheet" class="cennik-sheet"></div>
    </div>`;
  fillCennikSheet(p, 1);
  const close = () => {
    document.body.classList.remove("printing-cennik");
    modal.classList.add("hidden");
    modal.innerHTML = "";
  };
  document.getElementById("cennik-close").onclick = close;
  document.getElementById("cennik-qty").addEventListener("input", (e) => fillCennikSheet(p, e.target.value));
  document.getElementById("cennik-print").onclick = () => {
    fillCennikSheet(p, document.getElementById("cennik-qty")?.value);
    document.body.classList.add("printing-cennik");
    window.print();
    document.body.classList.remove("printing-cennik");
  };
  modal.onclick = (e) => {
    if (e.target === modal) close();
  };
}



async function openStockAdjust(product) {
  const modal = document.getElementById("stock-history-modal") || document.getElementById("confirm-modal");
  if (!modal || !product) return;
  const current = Number(product.stock || 0);
  const unit = product.unit || "";
  const preview = () => {
    const qty = Number(document.getElementById("adj-qty")?.value);
    const out = document.getElementById("adj-preview");
    const err = document.getElementById("adj-err");
    const ok = document.getElementById("adj-ok");
    if (err) err.textContent = "";
    if (!(qty === qty) || qty === 0) {
      if (out) out.innerHTML = `<p class="muted">Farq 0 bo‘lmasin.</p>`;
      if (ok) ok.disabled = true;
      return;
    }
    const result = Math.round((current + qty) * 1000) / 1000;
    const neg = result < -0.0001;
    if (out) {
      out.innerHTML = `<p>Hozirgi: <b>${current}</b> ${esc(unit)}</p>
        <p>Farq: <b>${qty > 0 ? "+" : ""}${qty}</b></p>
        <p>Natija: <b class="${neg ? "stock-low" : ""}">${result}</b> ${esc(unit)}</p>`;
    }
    if (ok) ok.disabled = neg;
    if (neg && err) err.textContent = "Natija manfiy bo‘lmasin";
  };
  modal.classList.remove("hidden");
  modal.innerHTML = `
    <div class="card confirm-box">
      <h3>Qoldiqni tuzatish</h3>
      <p class="muted">${esc(product.name)} · hozirgi qoldiq <b>${current} ${esc(unit)}</b></p>
      <input class="field" id="adj-qty" type="number" step="0.001" placeholder="Farq (+5 yoki -3)" />
      <input class="field" id="adj-reason" placeholder="Sabab" style="margin-top:8px" />
      <div id="adj-preview" style="margin-top:8px"></div>
      <p class="err" id="adj-err"></p>
      <div class="modal-actions">
        <button type="button" class="btn btn-gold" id="adj-ok" disabled>Tasdiqlash</button>
        <button type="button" class="btn btn-ghost" id="adj-cancel">Bekor</button>
      </div>
    </div>`;
  const close = () => {
    modal.classList.add("hidden");
    modal.innerHTML = "";
  };
  document.getElementById("adj-cancel").onclick = close;
  modal.onclick = (e) => {
    if (e.target === modal) close();
  };
  document.getElementById("adj-qty").oninput = preview;
  document.getElementById("adj-ok").onclick = async () => {
    const err = document.getElementById("adj-err");
    const ok = document.getElementById("adj-ok");
    const qty = Number(document.getElementById("adj-qty")?.value);
    const reason = String(document.getElementById("adj-reason")?.value || "").trim();
    if (!(qty === qty) || qty === 0) {
      if (err) err.textContent = "Farq noldan farq qilsin";
      return;
    }
    if (reason.length < 3) {
      if (err) err.textContent = "Sabab kamida 3 belgi";
      return;
    }
    const result = Math.round((current + qty) * 1000) / 1000;
    if (result < -0.0001) {
      if (err) err.textContent = "Natija manfiy bo‘lmasin";
      return;
    }
    ok.disabled = true;
    try {
      await api("/api/stock-adjustments", {
        method: "POST",
        body: JSON.stringify({ product_id: product.id, qty, reason }),
      });
      close();
      render();
    } catch (ex) {
      if (err) err.textContent = ex.message;
      ok.disabled = false;
    }
  };
  preview();
}

async function openStockHistory(product) {
  const modal = document.getElementById("stock-history-modal");
  if (!modal || !product) return;
  const state = window.__stockHist || { page: 1, kind: "", product };
  state.product = product;
  window.__stockHist = state;
  const limit = 50;
  const params = new URLSearchParams({
    product_id: String(product.id),
    page: String(state.page || 1),
    limit: String(limit),
  });
  if (state.kind) params.set("kind", state.kind);
  let rows = [];
  let err = "";
  try {
    rows = await api("/api/stock-movements?" + params.toString());
  } catch (ex) {
    err = ex.message || "Xatolik";
  }
  const fmtQty = (n) => {
    const v = Number(n);
    if (!(v === v)) return "0";
    return (v > 0 ? "+" : "") + v;
  };
  const fmtDt = (s) => {
    const d = String(s || "").replace("T", " ");
    return d.slice(0, 16);
  };
  const kinds = ["", "OPENING", "IN", "SALE", "RETURN", "TRANSFER_OUT", "TRANSFER_IN", "ADJUST"];
  modal.classList.remove("hidden");
  modal.innerHTML = `
    <div class="card confirm-box" style="max-width:720px;width:94vw">
      <h3>Qoldiq tarixi</h3>
      <p class="muted">${esc(product.name)} · hozirgi qoldiq <b>${product.stock} ${esc(product.unit || "")}</b></p>
      <div class="grid3" style="margin:8px 0">
        <select class="field" id="hist-kind">${kinds.map((k) => `<option value="${k}" ${state.kind === k ? "selected" : ""}>${k || "Barcha turlar"}</option>`).join("")}</select>
      </div>
      ${err ? `<p class="err">${esc(err)}</p>` : ""}
      <table class="table">
        <thead><tr><th>Sana</th><th>Foydalanuvchi</th><th>Tur</th><th>Miqdor</th><th>Qoldiq</th><th>Havola</th></tr></thead>
        <tbody>
          ${
            rows.length
              ? rows.map((m) => `<tr>
                  <td>${esc(fmtDt(m.created_at))}</td>
                  <td>${esc(m.user_name || "—")}</td>
                  <td>${esc(m.kind)}</td>
                  <td>${fmtQty(m.qty)}</td>
                  <td>${m.balance_after}</td>
                  <td class="muted">${esc((m.ref_type || "") + (m.ref_id ? " #" + m.ref_id : ""))}${m.note ? " · " + esc(m.note) : ""}</td>
                </tr>`).join("")
              : `<tr><td colspan="6" class="muted">Harakat yo‘q</td></tr>`
          }
        </tbody>
      </table>
      <div style="display:flex;gap:8px;align-items:center;margin-top:8px">
        <button type="button" class="btn btn-ghost btn-sm" id="hist-prev" ${state.page <= 1 ? "disabled" : ""}>Oldingi</button>
        <span class="muted">Sahifa ${state.page}</span>
        <button type="button" class="btn btn-ghost btn-sm" id="hist-next" ${rows.length < limit ? "disabled" : ""}>Keyingi</button>
        <button type="button" class="btn btn-ghost" id="hist-close" style="margin-left:auto">Yopish</button>
      </div>
    </div>`;
  document.getElementById("hist-close").onclick = () => {
    modal.classList.add("hidden");
    modal.innerHTML = "";
  };
  modal.onclick = (e) => {
    if (e.target === modal) {
      modal.classList.add("hidden");
      modal.innerHTML = "";
    }
  };
  document.getElementById("hist-kind").onchange = (e) => {
    window.__stockHist.kind = e.target.value;
    window.__stockHist.page = 1;
    openStockHistory(product);
  };
  document.getElementById("hist-prev").onclick = () => {
    window.__stockHist.page = Math.max(1, Number(window.__stockHist.page || 1) - 1);
    openStockHistory(product);
  };
  document.getElementById("hist-next").onclick = () => {
    window.__stockHist.page = Number(window.__stockHist.page || 1) + 1;
    openStockHistory(product);
  };
}

async function pageProducts() {
  const page = Math.max(1, Number(window.__prodPage || 1));
  const limit = 200;
  const [rows, cats] = await Promise.all([
    api("/api/products?page=" + page + "&limit=" + limit),
    api("/api/categories").catch(() => []),
  ]);
  window.__products = rows;
  window.__prodCats = cats || [];
  window.__prodPage = page;
  const catOpts = (window.__prodCats || [])
    .map((c) => `<option value="${c.id}">${esc(c.name)}</option>`)
    .join("");
  const pager = `
    <div style="display:flex;gap:8px;align-items:center;margin:10px 0">
      <button type="button" class="btn btn-ghost btn-sm" id="p-prev" ${page <= 1 ? "disabled" : ""}>Oldingi</button>
      <span class="muted">Sahifa ${page}</span>
      <button type="button" class="btn btn-ghost btn-sm" id="p-next" ${(rows || []).length < limit ? "disabled" : ""}>Keyingi</button>
    </div>`;
  return `
    <h2>Tovarlar</h2>
    <form id="p-form" class="card" style="margin-bottom:12px">
      <input type="hidden" name="id" />
      <div class="grid3" style="margin-top:0">
        <input class="field" name="name" placeholder="Nomi" required />
        <div style="display:flex;gap:6px;align-items:center">
          <input class="field" name="barcode" placeholder="Barcode" style="flex:1" />
          <button type="button" class="btn btn-ghost" id="p-barcode-auto">Avto</button>
        </div>
        <input class="field" name="sku" placeholder="SKU" />
        <select class="field" name="category_id">
          <option value="">Kategoriya</option>
          ${catOpts}
        </select>
        <input class="field" name="manufacturer" placeholder="Ishlab chiqaruvchi" />
        <input class="field" name="sell_price" type="number" step="0.01" min="0" placeholder="Sotuv narxi" required />
        <input class="field" name="buy_price" type="number" step="0.01" min="0" placeholder="Xarid narxi" />
        <span id="p-stock-wrap"><input class="field" name="stock" type="number" step="0.001" placeholder="Ochilish qoldig‘i" /></span>
        <input class="field" name="min_stock" type="number" step="0.001" placeholder="Min qoldiq" />
        <input class="field" name="unit" placeholder="Birlik" value="dona" />
        <label class="check"><input type="checkbox" name="is_active" checked /> Faol</label>
        <button class="btn btn-gold" type="submit" id="p-save">Qo‘shish</button>
      </div>
      <div class="err" id="p-err" style="margin-top:10px"></div>
    </form>
    ${pager}
    <div class="card" style="margin-bottom:12px">
      <input class="field" id="p-filter" placeholder="Jadvaldan qidirish: nomi yoki barcode..." />
    </div>
    <table class="table" id="p-table">
      <thead><tr><th>Nomi</th><th>Barcode</th><th>Narx</th><th>Qoldiq</th><th>Amallar</th></tr></thead>
      <tbody>
      ${rows
        .map((p) => {
          const low = Number(p.stock) <= Number(p.min_stock);
          return `<tr class="${p.is_active ? "" : "badge-off"}" data-name="${esc(p.name).toLowerCase()}" data-barcode="${esc(p.barcode || "").toLowerCase()}">
            <td>${esc(p.name)}</td><td>${esc(p.barcode)}</td><td>${money(p.sell_price)}</td>
            <td class="${low ? "stock-low" : ""}">${p.stock} ${esc(p.unit)}${low ? ` <span class="muted">(min ${p.min_stock})</span>` : ""}</td>
            <td>
              <button class="btn btn-ghost btn-sm" data-edit='${esc(JSON.stringify(p))}'>Tahrir</button>
                <button type="button" class="btn btn-ghost btn-sm" data-cennik="${p.id}">Cennik</button>
              <button type="button" class="btn btn-ghost btn-sm" data-history="${p.id}">Tarix</button>
              <button type="button" class="btn btn-ghost btn-sm" data-adjust="${p.id}">Tuzatish</button>
              <button class="btn btn-ghost btn-sm" data-toggle="${p.id}" data-name="${esc(p.name)}" data-active="${p.is_active ? "1" : "0"}">${p.is_active ? "O'chirish" : "Yoqish"}</button>
            </td>
          </tr>`;
        })
        .join("")}
      </tbody>
    </table>`;
}

function askConfirm({ title, text, okLabel = "O'chirish", cancelLabel = "Bekor qilish" }) {
  return new Promise((resolve) => {
    const modal = document.getElementById("confirm-modal");
    if (!modal) return resolve(window.confirm(text));
    modal.classList.remove("hidden");
    modal.innerHTML = `
      <div class="card confirm-box">
        <h3>${esc(title)}</h3>
        <p class="muted">${esc(text)}</p>
        <div class="modal-actions">
          <button type="button" class="btn btn-danger" id="confirm-ok">${esc(okLabel)}</button>
          <button type="button" class="btn btn-ghost" id="confirm-cancel">${esc(cancelLabel)}</button>
        </div>
      </div>`;
    const done = (v) => {
      modal.classList.add("hidden");
      modal.innerHTML = "";
      resolve(v);
    };
    document.getElementById("confirm-ok").onclick = () => done(true);
    document.getElementById("confirm-cancel").onclick = () => done(false);
    modal.onclick = (e) => {
      if (e.target === modal) done(false);
    };
  });
}

function hashParams() {
  const h = location.hash || "";
  const i = h.indexOf("?");
  return new URLSearchParams(i >= 0 ? h.slice(i + 1) : "");
}

function opnameMapErr(ex, kind) {
  const m = String(ex?.message || "");
  if (kind === "open" || /ochiq inventarizatsiya/i.test(m)) return "Бу дўконда очиқ саноқ мавжуд.";
  if (kind === "dup" || /allaqachon qo['‘’]?shilgan/i.test(m)) return "Бу маҳсулот саноққа аллақачон қўшилган.";
  return m || "Xatolik";
}

function opnameBadge(st) {
  const s = String(st || "").toUpperCase();
  if (s === "OPEN") return `<span class="badge ok">OPEN</span>`;
  if (s === "POSTED") return `<span class="badge">POSTED</span>`;
  if (s === "CANCELLED") return `<span class="badge badge-back">CANCELLED</span>`;
  return `<span class="badge">${esc(s)}</span>`;
}

function opnameDiffPreview(countedRaw, systemQty) {
  if (countedRaw === "" || countedRaw === null || countedRaw === undefined) return null;
  const c = Number(countedRaw);
  if (!(c === c) || c < 0) return null;
  return c - Number(systemQty || 0);
}

function fmtOpDiff(d) {
  if (d === null || d === undefined) return "—";
  if (d > 0) return "+" + d;
  return String(d);
}

function opnameIsOpen(doc) {
  return String(doc?.status || "").toUpperCase() === "OPEN";
}

function opnameCanWrite(doc) {
  return opnameIsOpen(doc) && !isCompanyCabinet();
}

function opnameIsDirty() {
  return !!document.querySelector(".op-counted.dirty");
}

function paintOpDiff(input) {
  const tr = input.closest("tr");
  const cell = tr?.querySelector("[data-diff]");
  if (!cell) return;
  const sys = Number(input.dataset.system || 0);
  const raw = input.value.trim();
  if (raw === "") {
    cell.textContent = "—";
    cell.className = "num muted";
    return;
  }
  const n = Number(raw);
  if (!(n === n) || n < 0) {
    cell.textContent = "!";
    cell.className = "num stock-low";
    return;
  }
  const d = n - sys;
  cell.textContent = fmtOpDiff(d);
  cell.className = "num " + (d < 0 ? "stock-low" : d > 0 ? "ok" : "muted");
}

async function pageOpname() {
  if (!can("stock")) return `<p class="err">Ruxsat yo‘q</p>`;
  const id = Number(hashParams().get("id") || 0);
  if (id) return pageOpnameDetail(id);
  return pageOpnameList();
}

async function pageOpnameList() {
  const page = Math.max(1, Number(window.__opnameListPage || hashParams().get("page") || 1));
  const limit = 50;
  window.__opnameListPage = page;
  let rows = [];
  let total = 0;
  let err = "";
  try {
    const pack = await api("/api/stock-opnames?page=" + page + "&limit=" + limit, { withHeaders: true });
    rows = pack.data || [];
    total = Number(pack.headers?.total || rows.length);
  } catch (ex) {
    err = ex.message || "Xatolik";
  }
  const pages = Math.max(1, Math.ceil(total / limit) || 1);
  const createHtml = isCompanyCabinet()
    ? `<p class="muted">Kompaniya kabinetidan sanash ochilmaydi. Do‘kon loginidan kiring.</p>`
    : `<form id="op-create" class="card" style="margin-bottom:12px">
        <div class="grid3" style="margin-top:0">
          <input class="field" name="note" placeholder="Izoh (ixtiyoriy)" maxlength="300" />
          <button class="btn btn-gold" type="submit" id="op-create-btn">Yangi sanash</button>
        </div>
        <div class="err" id="op-create-err" style="margin-top:8px"></div>
      </form>`;
  return `
    <h2>${t("opname")}</h2>
    ${createHtml}
    ${err ? `<p class="err">${esc(err)}</p>` : ""}
    <div class="table-scroll">
    <table class="table">
      <thead><tr><th>№</th><th>Status</th><th>Do‘kon</th><th>Sana</th><th>Kim</th><th class="num">Qator</th><th>Izoh</th></tr></thead>
      <tbody>
        ${
          rows.length
            ? rows
                .map(
                  (d) => `<tr class="clickable" data-opid="${d.id}">
                    <td>${esc(d.number)}</td>
                    <td>${opnameBadge(d.status)}</td>
                    <td>${esc(d.store_name || "—")}</td>
                    <td>${fmtDate(d.created_at)}</td>
                    <td>${esc(d.created_by_name || "—")}</td>
                    <td class="num">${d.line_count ?? 0}</td>
                    <td class="muted">${esc(d.note || "—")}</td>
                  </tr>`,
                )
                .join("")
            : `<tr><td colspan="7" class="muted">Sanash hujjatlari yo‘q</td></tr>`
        }
      </tbody>
    </table>
    </div>
    <div style="display:flex;gap:8px;align-items:center;margin-top:10px">
      <button type="button" class="btn btn-ghost btn-sm" id="op-prev" ${page <= 1 ? "disabled" : ""}>Oldingi</button>
      <span class="muted">Sahifa ${page} / ${pages} · jami ${total}</span>
      <button type="button" class="btn btn-ghost btn-sm" id="op-next" ${page >= pages ? "disabled" : ""}>Keyingi</button>
    </div>`;
}

function opnameDetailHtml(doc) {
  const open = opnameIsOpen(doc);
  const writable = opnameCanWrite(doc);
  const lines = doc.lines || [];
  const statusNote = !open
    ? String(doc.status || "").toUpperCase() === "POSTED"
      ? `<p class="muted">Sanash yakunlangan — faqat o‘qish.</p>`
      : `<p class="muted">Sanash bekor qilingan — faqat o‘qish.</p>`
    : "";
  const warn = open
    ? `<p class="muted op-warn">Эслатма: саноқ бошланганидан кейин қолдиқ ўзгариши мумкин. Фарқ саноқ бошланган пайтдаги snapshot асосида ҳисобланади.</p>`
    : "";
  const addHtml = writable
    ? `<div class="card" style="margin-bottom:12px">
        <div class="grid3" style="margin-top:0">
          <div class="op-suggest">
            <input class="field" id="op-search" placeholder="Barcode / qidiruv..." autocomplete="off" />
            <div id="op-drop" class="op-drop hidden"></div>
          </div>
          <p id="op-add-hint" class="muted" style="margin:0;align-self:center"></p>
        </div>
        <div class="err" id="op-add-err" style="margin-top:8px"></div>
      </div>`
    : "";
  const finHtml = writable
    ? `<div class="row" style="margin:12px 0;gap:8px;align-items:center">
         <button type="button" class="btn btn-gold" id="op-finalize">Санашни якунлаш</button>
         <span class="err" id="op-finalize-err"></span>
       </div>`
    : "";
  return `
    <p><button type="button" class="btn btn-ghost btn-sm" id="op-back">← Ro‘yxat</button></p>
    <h2>${esc(doc.number || t("opname"))} ${opnameBadge(doc.status)}</h2>
    <p class="muted">${esc(doc.store_name || "")} · ${fmtDate(doc.created_at)} · ${esc(doc.created_by_name || "—")}${doc.note ? " · " + esc(doc.note) : ""}</p>
    ${statusNote}${warn}${addHtml}
    <div class="table-scroll">
    <table class="table" id="op-lines">
      <thead><tr><th>Mahsulot</th><th>SKU</th><th>Barcode</th><th class="num">System</th><th class="num">Counted</th><th class="num">Farq</th><th></th></tr></thead>
      <tbody>
        ${
          lines.length
            ? lines
                .map((ln) => {
                  const raw = ln.counted_qty === null || ln.counted_qty === undefined ? "" : String(ln.counted_qty);
                  const d = opnameDiffPreview(raw, ln.system_qty);
                  const countedCell = writable
                    ? `<input class="field op-counted" type="number" min="0" step="any" inputmode="decimal" data-line="${ln.line_id || ln.id}" data-system="${ln.system_qty}" data-saved="${esc(raw)}" value="${esc(raw)}" placeholder="—" />
                       <span class="muted op-save-st" data-st="${ln.line_id || ln.id}"></span>`
                    : raw === ""
                      ? `<span class="muted">—</span>`
                      : esc(raw);
                  const del = writable
                    ? `<button type="button" class="btn btn-ghost btn-sm" data-opdel="${ln.line_id || ln.id}" data-name="${esc(ln.product_name || "")}">O‘chirish</button>`
                    : "";
                  return `<tr data-line-row="${ln.line_id || ln.id}" data-pid="${ln.product_id}">
                    <td>${esc(ln.product_name || "")}${ln.is_active === false ? ' <span class="muted">(nofaol)</span>' : ""}</td>
                    <td class="muted">${esc(ln.sku || "—")}</td>
                    <td class="muted">${esc(ln.barcode || "—")}</td>
                    <td class="num">${ln.system_qty}</td>
                    <td>${countedCell}</td>
                    <td class="num ${d === null ? "muted" : d < 0 ? "stock-low" : d > 0 ? "ok" : "muted"}" data-diff>${fmtOpDiff(d)}</td>
                    <td>${del}</td>
                  </tr>`;
                })
                .join("")
            : `<tr><td colspan="7" class="muted">Qatorlar yo‘q${writable ? ". Barcode yoki qidiruv orqali mahsulot qo‘shing." : ""}</td></tr>`
        }
      </tbody>
    </table>
    </div>
    ${finHtml}`;
}

async function pageOpnameDetail(id) {
  try {
    const doc = await api("/api/stock-opnames/" + id);
    window.__opnameDoc = doc;
    return opnameDetailHtml(doc);
  } catch (ex) {
    return `<p><button type="button" class="btn btn-ghost btn-sm" id="op-back">← Ro‘yxat</button></p><p class="err">${esc(ex.message)}</p>`;
  }
}

async function reloadOpnameDetail() {
  const id = Number(hashParams().get("id") || window.__opnameDoc?.id || 0);
  if (!id) return render();
  const main = document.querySelector(".main");
  if (!main) return render();
  main.innerHTML = `<p class="muted">Yuklanmoqda...</p>`;
  try {
    const doc = await api("/api/stock-opnames/" + id);
    window.__opnameDoc = doc;
    main.innerHTML = opnameDetailHtml(doc);
    bindOpnameDetail();
  } catch (ex) {
    main.innerHTML = `<p class="err">${esc(ex.message)}</p>`;
  }
}

function bindOpnameList() {
  document.querySelectorAll("[data-opid]").forEach((row) => {
    row.onclick = () => {
      location.hash = "#/app/opname?id=" + row.dataset.opid;
    };
  });
  document.getElementById("op-prev")?.addEventListener("click", () => {
    window.__opnameListPage = Math.max(1, Number(window.__opnameListPage || 1) - 1);
    render();
  });
  document.getElementById("op-next")?.addEventListener("click", () => {
    window.__opnameListPage = Number(window.__opnameListPage || 1) + 1;
    render();
  });
  const form = document.getElementById("op-create");
  if (!form) return;
  form.onsubmit = async (e) => {
    e.preventDefault();
    const err = document.getElementById("op-create-err");
    const btn = document.getElementById("op-create-btn");
    if (err) err.textContent = "";
    if (btn?.disabled) return;
    if (btn) btn.disabled = true;
    window.__opnameBusy = true;
    try {
      const note = String(new FormData(form).get("note") || "");
      const doc = await api("/api/stock-opnames", { method: "POST", body: JSON.stringify({ note }) });
      location.hash = "#/app/opname?id=" + doc.id;
    } catch (ex) {
      if (err) err.textContent = opnameMapErr(ex, "open");
      if (btn) btn.disabled = false;
    } finally {
      window.__opnameBusy = false;
    }
  };
}

function bindOpnameDetail() {
  document.getElementById("op-back")?.addEventListener("click", () => {
    location.hash = "#/app/opname";
  });
  const search = document.getElementById("op-search");
  const drop = document.getElementById("op-drop");
  const addErr = document.getElementById("op-add-err");
  const hint = document.getElementById("op-add-hint");
  let tmr = 0;
  const hideDrop = () => drop && drop.classList.add("hidden");
  const showResults = (rows) => {
    if (!drop) return;
    if (!rows.length) {
      drop.innerHTML = `<div class="muted" style="padding:8px">Topilmadi</div>`;
      drop.classList.remove("hidden");
      return;
    }
    drop.innerHTML = rows
      .map(
        (p) => `<button type="button" class="link op-drop-item" data-addpid="${p.id}">
          <b>${esc(p.name)}</b>
          <span class="muted">${esc(p.barcode || "")} ${esc(p.sku || "")} · snapshot ${p.stock}</span>
        </button>`,
      )
      .join("");
    drop.classList.remove("hidden");
  };
  const addProduct = async (product) => {
    if (!product || window.__opnameBusy) return;
    if (addErr) addErr.textContent = "";
    const doc = window.__opnameDoc;
    if ((doc?.lines || []).some((l) => Number(l.product_id) === Number(product.id))) {
      if (addErr) addErr.textContent = "Бу маҳсулот саноққа аллақачон қўшилган.";
      return;
    }
    window.__opnameBusy = true;
    try {
      await api("/api/stock-opnames/" + doc.id + "/lines", {
        method: "POST",
        body: JSON.stringify({ product_id: product.id }),
      });
      if (search) search.value = "";
      hideDrop();
      if (hint) hint.textContent = "";
      await reloadOpnameDetail();
    } catch (ex) {
      if (addErr) addErr.textContent = opnameMapErr(ex, "dup");
    } finally {
      window.__opnameBusy = false;
    }
  };
  const runSearch = async (q, autoAdd) => {
    const s = String(q || "").trim();
    if (!s) {
      hideDrop();
      return;
    }
    try {
      const rows = ((await api("/api/products?q=" + encodeURIComponent(s) + "&limit=20")) || []).filter((p) => p.is_active !== false);
      const exact = rows.find((p) => String(p.barcode || "") === s);
      if (autoAdd && exact) {
        hideDrop();
        await addProduct(exact);
        return;
      }
      showResults(rows);
      if (hint) hint.textContent = exact ? exact.name : rows.length ? rows.length + " ta" : "";
    } catch (ex) {
      if (addErr) addErr.textContent = ex.message;
    }
  };
  search?.addEventListener("input", () => {
    clearTimeout(tmr);
    tmr = setTimeout(() => runSearch(search.value, false), 250);
  });
  search?.addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    clearTimeout(tmr);
    runSearch(search.value, true);
  });
  drop?.addEventListener("mousedown", (e) => {
    const b = e.target.closest("[data-addpid]");
    if (!b) return;
    e.preventDefault();
    addProduct({ id: Number(b.dataset.addpid) });
  });
  search?.addEventListener("blur", () => setTimeout(hideDrop, 180));

  document.querySelectorAll(".op-counted").forEach((inp) => {
    inp.addEventListener("input", () => {
      const saved = inp.dataset.saved ?? "";
      inp.classList.toggle("dirty", inp.value !== saved);
      paintOpDiff(inp);
    });
    const save = async () => {
      const raw = inp.value.trim();
      const saved = inp.dataset.saved ?? "";
      const st = document.querySelector(`[data-st="${inp.dataset.line}"]`);
      if (raw === saved) return;
      if (raw === "") {
        inp.value = saved;
        inp.classList.remove("dirty");
        paintOpDiff(inp);
        return;
      }
      const n = Number(raw);
      if (!(n === n) || n < 0) {
        if (st) st.textContent = "xato";
        return;
      }
      if (window.__opnameBusy) return;
      window.__opnameBusy = true;
      inp.disabled = true;
      if (st) st.textContent = "saqlanmoqda…";
      try {
        const out = await api(
          "/api/stock-opnames/" + window.__opnameDoc.id + "/lines/" + inp.dataset.line,
          { method: "PATCH", body: JSON.stringify({ counted_qty: n }) },
        );
        const v = out.counted_qty === null || out.counted_qty === undefined ? "" : String(out.counted_qty);
        inp.value = v;
        inp.dataset.saved = v;
        inp.classList.remove("dirty");
        paintOpDiff(inp);
        if (st) st.textContent = "saqlandi";
        setTimeout(() => {
          if (st && st.textContent === "saqlandi") st.textContent = "";
        }, 1200);
      } catch (ex) {
        if (st) st.textContent = opnameMapErr(ex);
      } finally {
        inp.disabled = false;
        window.__opnameBusy = false;
      }
    };
    inp.addEventListener("blur", save);
    inp.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        inp.blur();
      }
    });
  });

  document.querySelectorAll("[data-opdel]").forEach((btn) => {
    btn.onclick = async () => {
      if (window.__opnameBusy || btn.disabled) return;
      const ok = await askConfirm({
        title: "Qatorni o‘chirish",
        text: (btn.dataset.name || "Mahsulot") + " qatorini o‘chirasizmi?",
        okLabel: "O‘chirish",
        cancelLabel: "Bekor qilish",
      });
      if (!ok) return;
      btn.disabled = true;
      window.__opnameBusy = true;
      try {
        await api("/api/stock-opnames/" + window.__opnameDoc.id + "/lines/" + btn.dataset.opdel, { method: "DELETE" });
        await reloadOpnameDetail();
      } catch (ex) {
        const box = document.getElementById("op-add-err");
        if (box) box.textContent = ex.message;
        btn.disabled = false;
      } finally {
        window.__opnameBusy = false;
      }
    };
  });

  document.getElementById("op-finalize")?.addEventListener("click", async () => {
    const btn = document.getElementById("op-finalize");
    const err = document.getElementById("op-finalize-err");
    if (window.__opnameBusy || btn?.disabled) return;
    const ok = await askConfirm({
      title: "Санашни якунлаш",
      text: "Санашни якунласангиз, фарқлар омбор қолдиғига қўлланади. Давом этасизми?",
      okLabel: "Yakunlash",
      cancelLabel: "Bekor qilish",
    });
    if (!ok) return;
    if (err) err.textContent = "";
    if (btn) btn.disabled = true;
    window.__opnameBusy = true;
    try {
      await api("/api/stock-opnames/" + window.__opnameDoc.id + "/finalize", { method: "POST" });
      await reloadOpnameDetail();
    } catch (ex) {
      if (err) err.textContent = ex.message;
      if (btn) btn.disabled = false;
    } finally {
      window.__opnameBusy = false;
    }
  });

}

function bindOpname(page) {
  if (page !== "opname") return;
  if (hashParams().get("id")) bindOpnameDetail();
  else bindOpnameList();
}

async function pageStock() {
  const products = await api("/api/products?limit=500");
  const docs = await api("/api/stock-ins");
  window.__stock = { products, lines: [] };
  const opts = (products || [])
    .filter((p) => p.is_active !== false)
    .map(
      (p) =>
        `<option value="${p.id}">${esc(p.name)}${p.barcode ? " · " + esc(p.barcode) : ""}</option>`,
    )
    .join("");
  return `
    <h2>Kirim</h2>
${isCompanyCabinet() ? "" : `    <form id="in-form" class="card">
      <div class="grid3" style="margin-top:0">
        <input class="field" name="supplier" placeholder="Yetkazib beruvchi" />
        <input class="field" name="note" placeholder="Izoh" />
      </div>
      <div class="grid3">
        <input class="field" id="in-barcode" placeholder="Barcode (skaner yoki qo‘lda)" autocomplete="off" />
        <select class="field" id="in-product">
          <option value="">Mahsulot tanlang</option>
          ${opts}
        </select>
        <p id="in-barcode-hint" class="muted" style="margin:0;align-self:center"></p>
      </div>
      <div class="grid3">
        <input class="field" id="in-qty" type="number" step="0.001" min="0.001" placeholder="Miqdor" />
        <input class="field" id="in-buy" type="number" step="0.01" min="0" placeholder="Xarid narxi" />
        <button class="btn btn-ghost" type="button" id="in-add">Qator qo‘shish</button>
      </div>
      <p id="in-form-err" class="err" hidden></p>
      <button class="btn btn-gold" style="margin-top:10px" type="submit">Kirim qilish</button>
    </form>`}
    <div id="in-lines" class="stock-draft"></div>
    <h3>Tarix</h3>
    <table class="table">
      <thead>
        <tr><th>№</th><th>Sana</th><th>Yetkazuvchi</th><th class="num">Summa</th></tr>
      </thead>
      <tbody>
        ${
          docs.length
            ? docs
                .map(
                  (d) =>
                    `<tr class="clickable" data-doc="${d.id}"><td>${esc(d.number)}</td><td>${fmtDate(d.created_at)}</td><td>${esc(d.supplier || "—")}</td><td class="num">${money(d.total)}</td></tr>`,
                )
                .join("")
            : `<tr><td colspan="4" class="muted">Kirim tarixi bo‘sh</td></tr>`
        }
      </tbody>
    </table>
    <div id="in-detail"></div>`;
}

function stockFormError(msg) {
  const el = document.getElementById("in-form-err");
  if (!el) return;
  el.hidden = !msg;
  el.textContent = msg || "";
}

function findStockProduct(q) {
  const products = window.__stock?.products || [];
  const s = String(q || "").trim();
  if (!s) return null;
  const exact = products.find((x) => (x.barcode || "") === s);
  if (exact) return exact;
  const lower = s.toLowerCase();
  const matches = products.filter(
    (x) =>
      (x.barcode || "").toLowerCase().includes(lower) || String(x.name || "").toLowerCase().includes(lower),
  );
  return matches.length === 1 ? matches[0] : null;
}

function addStockLine(product, qty, buy) {
  const q = Number(qty);
  if (!product || !(q > 0)) return false;
  const price = Number(buy) > 0 ? Number(buy) : Number(product.buy_price || 0);
  const lines = window.__stock.lines;
  const existing = lines.find((l) => l.product_id === product.id && Number(l.buy_price) === price);
  if (existing) existing.qty = Math.round((Number(existing.qty) + q) * 1000) / 1000;
  else {
    lines.push({
      product_id: product.id,
      name: product.name,
      barcode: product.barcode || "",
      qty: Math.round(q * 1000) / 1000,
      buy_price: price,
    });
  }
  return true;
}

function fillStockBuy(product) {
  const buy = document.getElementById("in-buy");
  const sel = document.getElementById("in-product");
  if (product && sel) sel.value = String(product.id);
  if (product && buy && !buy.value) buy.value = product.buy_price || "";
}

function drawStockLines() {
  const box = document.getElementById("in-lines");
  if (!box || !window.__stock) return;
  const lines = window.__stock.lines;
  if (!lines.length) {
    box.innerHTML = `
      <div class="empty-warn" role="status">
        <span class="empty-warn-ico" aria-hidden="true">!</span>
        <div>
          <b>${EMPTY_STOCK_MSG}</b>
          <p class="muted" style="margin:4px 0 0">Qator qo‘shish yoki barcode orqali mahsulot kiriting.</p>
        </div>
      </div>`;
    return;
  }
  const total = lines.reduce((s, l) => s + Number(l.qty) * Number(l.buy_price), 0);
  box.innerHTML = `
    <h3>Qo‘shilgan mahsulotlar</h3>
    <table class="table">
      <thead>
        <tr>
          <th>Mahsulot</th>
          <th>Barcode</th>
          <th class="num">Miqdor</th>
          <th class="num">Narx</th>
          <th class="num">Summa</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        ${lines
          .map(
            (l, i) => `<tr>
              <td>${esc(l.name)}</td>
              <td class="muted">${esc(l.barcode || "—")}</td>
              <td class="num">${l.qty}</td>
              <td class="num">${money(l.buy_price)}</td>
              <td class="num">${money(l.qty * l.buy_price)}</td>
              <td><button type="button" class="btn-x" data-rm="${i}" title="O‘chirish" aria-label="O‘chirish">×</button></td>
            </tr>`,
          )
          .join("")}
      </tbody>
      <tfoot>
        <tr>
          <td colspan="4"><b>Jami</b></td>
          <td class="num"><b>${money(total)}</b></td>
          <td></td>
        </tr>
      </tfoot>
    </table>`;
}

async function pagePos() {
  const [products, customers, shift] = await Promise.all([
    api("/api/pos/products"),
    can("customers") ? api("/api/customers") : Promise.resolve([]),
    can("cash") ? api("/api/shifts/current").catch(() => ({ open: false })) : Promise.resolve({ open: false }),
  ]);
  window.__pos = { products, customers, cart: [] };
  const shiftBar = can("cash")
    ? `<div class="card" style="margin-bottom:12px">
        ${shift.open ? `<span class="ok">Smena ochiq</span> <button class="btn btn-ghost btn-sm" id="shift-close">${t("shiftClose")}</button>` : `<span class="err">Smena yopiq</span> <input class="field" id="shift-open-cash" type="number" placeholder="Naqd ochilish" style="max-width:160px;display:inline-block" /> <button class="btn btn-gold btn-sm" id="shift-open">${t("shiftOpen")}</button>`}
      </div>`
    : "";
  return `
    <h2>POS — savdo oynasi</h2>
    ${shiftBar}
    <div class="pos">
      <div class="card pos-search">
        <input class="field" id="scan" placeholder="Qidirish / barcode..." autofocus autocomplete="off" />
        <div id="plist" class="pos-drop" role="listbox"></div>
      </div>
      <div class="card">
        <b>Savat</b>
        <div id="cart"></div>
        <div class="grid3" style="margin-top:10px">
          <input class="field" id="discount" type="number" step="0.01" placeholder="Chegirma" />
          <select class="field" id="customer">
            <option value="">Mijoz yo‘q</option>
            ${customers.map((c) => `<option value="${c.id}">${esc(c.name)}${c.debt ? " · qarz " + money(c.debt) : ""}</option>`).join("")}
          </select>
          <label class="check"><input type="checkbox" id="credit" /> Qarzga</label>
        </div>
        <p>Jami: <b id="total">0 so'm</b></p>
        <p class="muted" id="pos-tax" hidden></p>
        <p class="muted" style="font-size:12px">F2 to‘lov · Esc qidiruv · F4 naqd</p>
        <div class="grid3">
          <input class="field" id="cash" type="number" placeholder="Naqd" />
          <input class="field" id="card" type="number" placeholder="Karta" />
          <input class="field" id="online" type="number" placeholder="Click/Payme" />
        </div>
        <p class="ok qaytim" id="qaytim" hidden></p>
        <button class="btn btn-gold" id="pay" style="margin-top:10px;width:100%">To‘lov</button>
        <div id="pos-msg"></div>
      </div>
    </div>`;
}

function vatIncluded(total, vat) {
  const v = Number(vat || 0);
  const t = Number(total || 0);
  if (!(v > 0) || !(t > 0)) return 0;
  return Math.round((t * v) / (100 + v) * 100) / 100;
}
function posTotals() {
  const state = window.__pos;
  const subtotal = (state?.cart || []).reduce((s, i) => s + i.qty * i.price, 0);
  const discount = Math.max(0, Number(document.getElementById("discount")?.value || 0));
  const total = Math.max(0, subtotal - discount);
  const tax = vatIncluded(total, user()?.vat_percent);
  return { subtotal, discount, total, tax };
}

function drawPos() {
  const state = window.__pos;
  if (!state) return;
  const q = (document.getElementById("scan")?.value || "").toLowerCase();
  const list = state.products.filter(
    (p) => !q || p.name.toLowerCase().includes(q) || (p.barcode || "").includes(q),
  );
  const plist = document.getElementById("plist");
  if (plist) {
    plist.innerHTML = list
      .slice(0, 24)
      .map(
        (p) =>
          `<button type="button" class="pos-drop-item" data-add="${p.id}">
              <span>${esc(p.name)}</span>
              <span class="muted">${esc(p.barcode || "")}</span>
              <b>${money(p.sell_price)}</b>
              <span class="muted">qoldiq ${p.stock}</span>
            </button>`,
      )
      .join("");
    plist.hidden = !list.length;
  }
  const cart = document.getElementById("cart");
  if (cart) {
    cart.innerHTML =
      state.cart
        .map(
          (i, idx) =>
            `<div class="cart-item">
              <span>${esc(i.name)}</span>
              <span class="qty">
                <button data-minus="${idx}">−</button>${i.qty}<button data-plus="${idx}">+</button>
                <b>${money(i.qty * i.price)}</b>
                <button data-del="${idx}">×</button>
              </span>
            </div>`,
        )
        .join("") || "<p class='muted'>Savat bo‘sh</p>";
  }
  const tot = posTotals();
  const t = document.getElementById("total");
  if (t) t.textContent = money(tot.total);
  const taxEl = document.getElementById("pos-tax");
  if (taxEl) {
    if (tot.tax > 0) {
      taxEl.hidden = false;
      taxEl.textContent = "QQS (narxga kiritilgan): " + money(tot.tax);
    } else {
      taxEl.hidden = true;
      taxEl.textContent = "";
    }
  }
  updatePayHints();
}

function findScanProduct(q) {
  const products = window.__pos?.products || [];
  const s = (q || "").trim();
  if (!s) return null;
  const exact = products.find((x) => (x.barcode || "") === s);
  if (exact) return exact;
  const matches = products.filter(
    (x) => x.name.toLowerCase().includes(s.toLowerCase()) || (x.barcode || "").includes(s),
  );
  return matches.length === 1 ? matches[0] : null;
}

function updatePayHints() {
  const qaytim = document.getElementById("qaytim");
  const customer = document.getElementById("customer");
  const credit = document.getElementById("credit");
  if (!qaytim) return;
  const { total } = posTotals();
  const cash = Number(document.getElementById("cash")?.value || 0);
  const card = Number(document.getElementById("card")?.value || 0);
  const online = Number(document.getElementById("online")?.value || 0);
  const extra = cash + card + online - total;
  if (total > 0 && extra > 0) {
    qaytim.hidden = false;
    qaytim.textContent = "Qaytim: " + money(extra);
  } else {
    qaytim.hidden = true;
    qaytim.textContent = "";
  }
  if (credit?.checked) customer?.classList.add("need-customer");
  else customer?.classList.remove("need-customer");
}

function showReceipt(sale) {
  const modal = document.getElementById("receipt-modal");
  if (!modal) return;
  const u = user();
  modal.classList.remove("hidden");
  modal.innerHTML = `
    <div>
      <div class="receipt" id="receipt">
        <h3>${esc(u.company_name)}</h3>
        <div class="muted" style="text-align:center;color:#444">${esc(u.store_name || "")}</div>
        <hr />
        <div class="line"><span>${esc(sale.number)}</span><span>${esc((sale.created_at || "").slice(0, 19).replace("T", " "))}</span></div>
        <div class="line"><span>Kassir</span><span>${esc(sale.cashier || u.full_name)}</span></div>
        ${sale.customer_name ? `<div class="line"><span>Mijoz</span><span>${esc(sale.customer_name)}</span></div>` : ""}
        <hr />
        ${(sale.items || []).map((i) => `<div class="line"><span>${esc(i.name)} × ${i.qty}</span><span>${money(i.line_total)}</span></div>`).join("")}
        <hr />
        <div class="line"><span>Oraliq</span><span>${money(sale.subtotal)}</span></div>
        ${sale.discount ? `<div class="line"><span>Chegirma</span><span>-${money(sale.discount)}</span></div>` : ""}
        <div class="line"><b>Jami</b><b>${money(sale.total)}</b></div>
        ${Number(sale.tax_total) > 0 ? `<div class="line"><span>QQS (kiritilgan)</span><span>${money(sale.tax_total)}</span></div>` : ""}
        <div class="line"><span>To‘lov</span><span>${esc(sale.payment_type || "")}</span></div>
        <div class="line"><span>Naqd</span><span>${money(sale.paid_cash)}</span></div>
        ${sale.paid_card ? `<div class="line"><span>Karta</span><span>${money(sale.paid_card)}</span></div>` : ""}
        ${sale.paid_online ? `<div class="line"><span>Online</span><span>${money(sale.paid_online)}</span></div>` : ""}
        ${sale.on_credit ? `<div class="line"><span>Qarz</span><span>${money(sale.on_credit)}</span></div>` : ""}
        <div class="line"><span>Qaytim</span><span>${money(sale.change_amount)}</span></div>
        <p style="text-align:center;font-size:12px;margin:12px 0 0">Rahmat!</p>
        <p style="text-align:center;font-size:11px;color:#666;margin:6px 0 0">FINEX POS</p>
      </div>
      <div class="modal-actions">
        <button class="btn btn-gold" id="print-receipt">Chop etish</button>
        <button class="btn btn-ghost" id="close-receipt">Yopish</button>
      </div>
    </div>`;
  document.getElementById("print-receipt").onclick = () => window.print();
  document.getElementById("close-receipt").onclick = () => modal.classList.add("hidden");
  modal.onclick = (e) => {
    if (e.target === modal) modal.classList.add("hidden");
  };
}

function saleStatusLabel(status) {
  if (status === "RETURNED") return "Qaytarilgan";
  if (status === "PARTIAL") return "Qisman qaytarilgan";
  if (status === "PAID") return "To‘langan";
  return status || "";
}

function ymd(d) {
  const z = (n) => String(n).padStart(2, "0");
  return d.getFullYear() + "-" + z(d.getMonth() + 1) + "-" + z(d.getDate());
}

function salesDates(state) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  if (state.preset === "today") return { date_from: ymd(today), date_to: ymd(today) };
  if (state.preset === "yesterday") {
    const y = new Date(today);
    y.setDate(y.getDate() - 1);
    return { date_from: ymd(y), date_to: ymd(y) };
  }
  return { date_from: state.date_from || "", date_to: state.date_to || "" };
}

function eyeIco() {
  return '<svg class="ico-eye" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>';
}

async function pageSales() {
  window.__sales = window.__sales || { page: 1, page_size: 20, preset: "today", date_from: "", date_to: "", cashier: "" };
  return `
    <h2>Cheklar</h2>
    <div class="card sales-filters">
      <div class="chip-row">
        <button type="button" class="chip" data-preset="today">Bugun</button>
        <button type="button" class="chip" data-preset="yesterday">Kecha</button>
        <button type="button" class="chip" data-preset="range">Tanlangan kunlar</button>
        <button type="button" class="chip" data-preset="all">Barchasi</button>
      </div>
      <div class="grid3" style="margin-top:12px">
        <input class="field" type="date" id="sale-from" />
        <input class="field" type="date" id="sale-to" />
        <select class="field" id="sale-cashier">
          <option value="">Barcha kassirlar</option>
        </select>
      </div>
    </div>
    <table class="table" id="sales-table">
      <thead>
        <tr><th>№</th><th>Sana</th><th>Summa</th><th>To‘lov</th><th>Holat</th><th>Kassir</th><th></th></tr>
      </thead>
      <tbody id="sales-body"></tbody>
    </table>
    <div class="pager" id="sales-pager"></div>`;
}

function saleWhen(iso) {
  if (!iso) return "";
  return esc(iso.slice(0, 16).replace("T", " "));
}

async function loadSales() {
  const state = window.__sales;
  if (!state || !document.getElementById("sales-body")) return;
  const range = salesDates(state);
  const params = new URLSearchParams({ page: String(state.page), page_size: String(state.page_size) });
  if (range.date_from) params.set("date_from", range.date_from);
  if (range.date_to) params.set("date_to", range.date_to);
  if (state.cashier) params.set("cashier", state.cashier);
  const data = await api("/api/sales?" + params.toString());
  const rows = data.items || [];
  const body = document.getElementById("sales-body");
  const canRefundRole = user().role !== "CASHIER";
  body.innerHTML = rows.length
    ? rows
        .map((s) => {
          const returned = s.status === "RETURNED";
          return `<tr class="${returned ? "badge-off" : ""}">
            <td>${esc(s.number)}</td>
            <td>${saleWhen(s.created_at)}</td>
            <td>${money(s.total)}</td>
            <td>${esc(s.payment_type)}</td>
            <td><span class="badge ${returned ? "badge-back" : ""}">${esc(saleStatusLabel(s.status))}</span></td>
            <td>${esc(s.cashier)}</td>
            <td class="row-actions">
              <button type="button" class="btn btn-ghost btn-sm" data-view="${s.id}">${eyeIco()} Ko‘rish</button>
              ${canRefundRole && !returned ? `<button type="button" class="btn btn-danger btn-sm" data-refund="${s.id}" data-number="${esc(s.number)}">Qaytarish</button>` : ""}
            </td>
          </tr>`;
        })
        .join("")
    : `<tr><td colspan="7" class="muted">Chek topilmadi</td></tr>`;
  const sel = document.getElementById("sale-cashier");
  if (sel) {
    const cur = state.cashier;
    sel.innerHTML = '<option value="">Barcha kassirlar</option>' + (data.cashiers || []).map((n) => `<option value="${esc(n)}" ${n === cur ? "selected" : ""}>${esc(n)}</option>`).join("");
  }
  document.querySelectorAll("[data-preset]").forEach((b) => b.classList.toggle("active", b.dataset.preset === state.preset));
  const fromEl = document.getElementById("sale-from");
  const toEl = document.getElementById("sale-to");
  if (fromEl) fromEl.value = range.date_from;
  if (toEl) toEl.value = range.date_to;
  const pages = Math.max(1, Math.ceil((data.total || 0) / state.page_size));
  const pager = document.getElementById("sales-pager");
  if (pager) {
    pager.innerHTML = `
      <button type="button" class="btn btn-ghost btn-sm" data-spage="prev" ${state.page <= 1 ? "disabled" : ""}>Oldingi</button>
      <span class="muted">${state.page} / ${pages} · ${data.total || 0} chek</span>
      <button type="button" class="btn btn-ghost btn-sm" data-spage="next" ${state.page >= pages ? "disabled" : ""}>Keyingi</button>`;
  }
}

async function openSaleModal(id) {
  const sale = await api("/api/sales/" + id);
  const modal = document.getElementById("sale-modal");
  if (!modal) return;
  const canReturn = user().role !== "CASHIER" && sale.status !== "RETURNED";
  modal.classList.remove("hidden");
  modal.innerHTML = `
    <div class="card confirm-box sale-box">
      <h3>${esc(sale.number)}</h3>
      <p class="muted">${saleWhen(sale.created_at)} · ${esc(sale.cashier)} · ${esc(saleStatusLabel(sale.status))}</p>
      <table class="table">
        <tr><th>Tovar</th><th>Soni</th><th>Qaytarilgan</th><th>Narx</th><th>Jami</th><th></th></tr>
        ${(sale.items || []).map((i) => {
          const remain = Number(i.qty || 0) - Number(i.returned_qty || 0);
          return `<tr>
            <td>${esc(i.name)}</td><td>${i.qty}</td><td>${i.returned_qty || 0}</td>
            <td>${money(i.price)}</td><td>${money(i.line_total)}</td>
            <td>${canReturn && remain > 0 ? `<input class="field" data-rq="${i.id}" type="number" min="0" max="${remain}" step="0.001" placeholder="0" style="width:80px" />` : ""}</td>
          </tr>`;
        }).join("")}
      </table>
      ${sale.discount ? `<p class="muted">Chegirma: -${money(sale.discount)}</p>` : ""}
      ${sale.tax_total ? `<p class="muted">QQS: ${money(sale.tax_total)}</p>` : ""}
      <p><b>Jami: ${money(sale.total)}</b></p>
      <div class="modal-actions">
        ${canReturn ? `<button type="button" class="btn btn-danger" id="sale-refund">Qaytarish</button>` : ""}
        <button type="button" class="btn btn-ghost" id="sale-close">Yopish</button>
      </div>
    </div>`;
  const close = () => {
    modal.classList.add("hidden");
    modal.innerHTML = "";
  };
  document.getElementById("sale-close").onclick = close;
  modal.onclick = (e) => {
    if (e.target === modal) close();
  };
  document.getElementById("sale-refund")?.addEventListener("click", async () => {
    const items = [...document.querySelectorAll("[data-rq]")].map((el) => ({ id: Number(el.dataset.rq), qty: Number(el.value || 0) })).filter((x) => x.qty > 0);
    await refundSale(sale.id, sale.number, items);
  });
}

async function refundSale(id, number, items = []) {
  const ok = await askConfirm({
    title: "Qaytarishni tasdiqlang",
    text: items.length ? "Tanlangan qatorlar qaytariladi." : (number || "Chek") + " to‘liq qaytariladi.",
    okLabel: "Qaytarish",
    cancelLabel: "Bekor qilish",
  });
  if (!ok) return;
  await api("/api/sales/" + id + "/return", { method: "POST", body: JSON.stringify({ items }) });
  document.getElementById("sale-modal")?.classList.add("hidden");
  await loadSales();
}

function bindSales() {
  if (!document.getElementById("sales-body")) return;
  const state = window.__sales;
  document.querySelectorAll("[data-preset]").forEach((btn) => {
    btn.onclick = () => {
      state.preset = btn.dataset.preset;
      state.page = 1;
      if (state.preset !== "range") {
        state.date_from = "";
        state.date_to = "";
      }
      loadSales();
    };
  });
  document.getElementById("sale-from")?.addEventListener("change", (e) => {
    state.preset = "range";
    state.date_from = e.target.value;
    state.page = 1;
    loadSales();
  });
  document.getElementById("sale-to")?.addEventListener("change", (e) => {
    state.preset = "range";
    state.date_to = e.target.value;
    state.page = 1;
    loadSales();
  });
  document.getElementById("sale-cashier")?.addEventListener("change", (e) => {
    state.cashier = e.target.value;
    state.page = 1;
    loadSales();
  });
  document.getElementById("sales-pager")?.addEventListener("click", (e) => {
    const b = e.target.closest("[data-spage]");
    if (!b || b.disabled) return;
    if (b.dataset.spage === "prev") state.page = Math.max(1, state.page - 1);
    if (b.dataset.spage === "next") state.page += 1;
    loadSales();
  });
  document.getElementById("sales-body")?.addEventListener("click", (e) => {
    const view = e.target.closest("[data-view]");
    const refund = e.target.closest("[data-refund]");
    if (view) openSaleModal(Number(view.dataset.view));
    if (refund) refundSale(Number(refund.dataset.refund), refund.dataset.number);
  });
  loadSales();
}

function digitsOnly(s) {
  return String(s || "").replace(/\s+/g, "");
}

function validPhone(s) {
  return /^\d+$/.test(digitsOnly(s));
}

async function pageCustomers() {
  const rows = await api("/api/customers");
  window.__customers = rows;
  return `
    <h2>Mijozlar</h2>
    <form id="c-form" class="card" style="margin-bottom:12px">
      <div class="grid3" style="margin-top:0">
        <input class="field" name="name" placeholder="Ism" required />
        <input class="field" name="phone" placeholder="Telefon" required inputmode="numeric" />
        <input class="field" name="note" placeholder="Izoh" />
        <button class="btn btn-gold" type="submit">Qo‘shish</button>
      </div>
      <div class="err" id="c-err" style="margin-top:10px"></div>
    </form>
    <div class="card" style="margin-bottom:12px">
      <input class="field" id="c-filter" placeholder="Mijozlarni qidirish: ism yoki telefon..." />
    </div>
    <table class="table" id="c-table">
      <thead><tr><th>Ism</th><th>Telefon</th><th>Qarz</th><th></th></tr></thead>
      <tbody>
      ${rows
        .map((c) => {
          const debt = Number(c.debt || 0);
          return `<tr data-name="${esc(c.name).toLowerCase()}" data-phone="${esc(c.phone || "")}">
            <td>${esc(c.name)}</td>
            <td>${esc(c.phone)}</td>
            <td class="${debt > 0 ? "stock-low" : ""}">${money(c.debt)}</td>
            <td>
              <button type="button" class="btn btn-ghost btn-sm" data-chistory="${c.id}">Tarix</button>
              <button type="button" class="btn btn-ghost btn-sm" data-cedit='${esc(JSON.stringify(c))}'>Tahrir</button>
              <button type="button" class="btn btn-ghost btn-sm" data-pay="${c.id}" data-name="${esc(c.name)}" data-max="${debt}" ${debt > 0 ? "" : "disabled"}>Qarz uzish</button>
            </td>
          </tr>`;
        })
        .join("")}
      </tbody>
    </table>`;
}

async function openDebtPayModal(id, name, max) {
  const modal = document.getElementById("confirm-modal");
  if (!modal) return;
  modal.classList.remove("hidden");
  modal.innerHTML = `
    <div class="card confirm-box">
      <h3>Qarz uzish</h3>
      <p class="muted">${esc(name)} · joriy qarz <b class="stock-low">${money(max)}</b></p>
      <input class="field" id="debt-amount" type="number" step="0.01" min="0.01" placeholder="Olib kelingan summa" value="${max}" />
      <div class="err" id="debt-err" style="margin-top:8px"></div>
      <div class="modal-actions">
        <button type="button" class="btn btn-gold" id="debt-ok">To‘lash</button>
        <button type="button" class="btn btn-ghost" id="debt-cancel">Bekor</button>
      </div>
    </div>`;
  const close = () => {
    modal.classList.add("hidden");
    modal.innerHTML = "";
  };
  document.getElementById("debt-cancel").onclick = close;
  modal.onclick = (e) => {
    if (e.target === modal) close();
  };
  document.getElementById("debt-ok").onclick = async () => {
    const err = document.getElementById("debt-err");
    const amount = Number(document.getElementById("debt-amount").value || 0);
    if (!(amount > 0)) {
      err.textContent = "Summani kiriting";
      return;
    }
    if (amount > max + 0.01) {
      err.textContent = "Summa qarzdan oshmasin";
      return;
    }
    try {
      await api("/api/customers/" + id + "/pay-debt", {
        method: "POST",
        body: JSON.stringify({ amount, method: "CASH" }),
      });
      close();
      render();
    } catch (ex) {
      err.textContent = ex.message;
    }
  };
  document.getElementById("debt-amount").focus();
}

function cashKindLabel(kind) {
  if (kind === "OUT") return "CHIQIM";
  if (kind === "IN") return "KIRIM";
  if (kind === "SALE") return "SAVDO";
  return kind || "";
}

async function pageCash() {
  const d = await api("/api/cash");
  window.__cash = d;
  return `
    <h2>Kassa</h2>
    <div class="kpi" style="margin-bottom:16px">
      <div class="card kpi-card"><div class="kpi-head"><span>Naqd pul</span></div><b>${money(d.cash ?? d.balance)}</b></div>
      <div class="card kpi-card"><div class="kpi-head"><span>Karta (Terminal)</span></div><b>${money(d.card || 0)}</b></div>
      <div class="card kpi-card"><div class="kpi-head"><span>Jami</span></div><b>${money(((d.cash ?? d.balance) || 0) + (d.card || 0))}</b></div>
    </div>
${isCompanyCabinet() ? "" : `    <form id="cash-form" class="card" style="margin-bottom:12px">
      <div class="grid3" style="margin-top:0">
        <select class="field" name="kind" required>
          <option value="IN">Kirim</option>
          <option value="OUT">Chiqim</option>
        </select>
        <input class="field" name="amount" type="number" step="0.01" min="0.01" placeholder="Summa" required />
        <input class="field" name="note" placeholder="Izoh" required />
      </div>
      <button class="btn btn-gold" style="margin-top:10px" type="submit">Saqlash</button>
      <div class="err" id="cash-err" style="margin-top:10px"></div>
    </form>`}
    <table class="table" id="cash-table">
      <thead>
        <tr><th>Sana / vaqt</th><th>Holat</th><th>Summa</th><th>Izoh / chek</th></tr>
      </thead>
      <tbody>
        ${(d.txns || []).map((t) => {
          const out = t.kind === "OUT";
          const saleNo = t.sale_number || "";
          const note = t.note || "";
          const chek = saleNo
            ? `<button type="button" class="link-chek" data-sale-id="${t.sale_id}">${esc(saleNo)}</button>`
            : "";
          return `<tr>
            <td>${saleWhen(t.created_at)}</td>
            <td class="${out ? "stock-low" : "ok"}">${esc(cashKindLabel(t.kind))}</td>
            <td class="${out ? "stock-low" : ""}">${out ? "−" : "+"}${money(t.amount)}</td>
            <td>${chek}${chek && note && note !== saleNo ? " · " : ""}${esc(note && note !== saleNo ? note : chek ? "" : note)}</td>
          </tr>`;
        }).join("")}
      </tbody>
    </table>`;
}

const EXPENSE_CATS = ["Ijara", "Kommunal", "Oylik", "Transport", "Boshqa"];

async function pageExpenses() {
  const rows = await api("/api/expenses");
  return `
    <h2>Xarajatlar</h2>
${isCompanyCabinet() ? "" : `    <form id="ex-form" class="card" style="margin-bottom:12px">
      <div class="grid3" style="margin-top:0">
        <select class="field" name="category" required>
          ${EXPENSE_CATS.map((c) => `<option value="${c}">${c}</option>`).join("")}
        </select>
        <input class="field" name="amount" type="number" step="0.01" min="0.01" placeholder="Summa" required />
        <input class="field" name="note" placeholder="Izoh" />
        <button class="btn btn-gold" type="submit">Yozish</button>
      </div>
      <div class="err" id="ex-err" style="margin-top:10px"></div>
    </form>`}
    <table class="table">
      <thead><tr><th>Sana</th><th>Kategoriya</th><th>Summa</th><th>Izoh</th></tr></thead>
      <tbody>
        ${rows
          .map(
            (e) =>
              `<tr>
                <td>${saleWhen(e.created_at)}</td>
                <td>${esc(e.category)}</td>
                <td class="stock-low">−${money(e.amount)}</td>
                <td>${esc(e.note)}</td>
              </tr>`,
          )
          .join("")}
      </tbody>
    </table>`;
}

const STAFF_ROLES = [
  ["CASHIER", "Kassir"],
  ["WAREHOUSE", "Omborchi"],
  ["MANAGER", "Menejer"],
  ["ADMIN", "Administrator"],
];

function bindPwToggle(inputId, btnId) {
  const input = document.getElementById(inputId);
  const btn = document.getElementById(btnId);
  btn?.addEventListener("click", () => {
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    btn.setAttribute("aria-label", show ? "Yashirish" : "Ko‘rsatish");
    btn.classList.toggle("on", show);
  });
}

async function pageStaff() {
  const rows = await api("/api/staff");
  const me = user();
  return `
    <h2>Xodimlar</h2>
    <form id="st-form" class="card" style="margin-bottom:12px">
      <input type="hidden" name="id" />
      <div class="grid3" style="margin-top:0">
        <input class="field" name="full_name" placeholder="Ism" required />
        <input class="field" name="username" placeholder="Login" required />
        <div class="pw-wrap">
          <input class="field" name="password" id="st-password" type="password" placeholder="Parol" autocomplete="new-password" />
          <button type="button" class="pw-toggle" id="st-pw-toggle" aria-label="Ko‘rsatish">${eyeIco()}</button>
        </div>
        <select class="field" name="role">
          ${STAFF_ROLES.map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}
        </select>
        <button class="btn btn-gold" type="submit" id="st-save">Qo‘shish</button>
      </div>
      <div class="err" id="st-err" style="margin-top:10px"></div>
    </form>
    <table class="table" id="st-table">
      <thead><tr><th>Ism</th><th>Login</th><th>Rol</th><th>Holat</th><th></th></tr></thead>
      <tbody>
        ${rows
          .map((u) => {
            const self = me && me.id === u.id;
            const owner = u.role === "OWNER";
            const roleLabel = (STAFF_ROLES.find((r) => r[0] === u.role) || [u.role, u.role])[1];
            return `<tr class="${u.is_active ? "" : "badge-off"}">
              <td>${esc(u.full_name)}</td>
              <td>${esc(u.username)}</td>
              <td>${esc(roleLabel)}</td>
              <td>${u.is_active ? "Faol" : "O‘chirilgan"}</td>
              <td class="row-actions">
                ${!owner ? `<button type="button" class="btn btn-ghost btn-sm" data-st-edit='${esc(JSON.stringify(u))}'>Tahrirlash</button>` : ""}
                ${!owner && !self ? `<button type="button" class="btn btn-danger btn-sm" data-st-toggle="${u.id}" data-name="${esc(u.full_name)}" data-active="${u.is_active ? "1" : "0"}">${u.is_active ? "O'chirish" : "Yoqish"}</button>` : ""}
              </td>
            </tr>`;
          })
          .join("")}
      </tbody>
    </table>`;
}

function settingsKey() {
  return "finex_pos_settings_" + (user()?.company_id || "0");
}

function loadLocalSettings() {
  try {
    return JSON.parse(localStorage.getItem(settingsKey()) || "null");
  } catch {
    return null;
  }
}

function saveLocalSettings(data) {
  const payload = {
    company_name: data.company_name || "",
    phone: data.phone || "",
    inn: data.inn || "",
    address: data.address || "",
    store_name: data.store_name || "",
    store_phone: data.store_phone || "",
    store_address: data.store_address || "",
  };
  localStorage.setItem(settingsKey(), JSON.stringify(payload));
}


function fmtDay(iso) {
  if (!iso) return "—";
  const raw = String(iso).slice(0, 10);
  const p = raw.split("-");
  if (p.length === 3 && p[0].length === 4) return p[2] + "." + p[1] + "." + p[0];
  return raw;
}

function uzMonthPeriod(d) {
  const months = ["Yanvar","Fevral","Mart","Aprel","May","Iyun","Iyul","Avgust","Sentabr","Oktabr","Noyabr","Dekabr"];
  return months[d.getMonth()] + " " + d.getFullYear();
}

function planPrice(plan) {
  const map = { FREE: 0, PRO: 80000, ENTERPRISE: 160000, VIP: 500000 };
  return map[String(plan || "FREE").toUpperCase()] || 0;
}

function billingFallback(plan) {
  const u = user() || {};
  const id = Number(u.account_no || 0) || 100000 + Number(u.id || u.company_id || 0);
  const until = new Date();
  until.setDate(until.getDate() + 30);
  const p = String(plan || "FREE").toUpperCase();
  const price = planPrice(p);
  const now = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  const payments = price
    ? [{
        n: 1,
        at: "",
        period: uzMonthPeriod(now),
        amount: price,
        method: "",
        status: "unpaid",
      }]
    : [];
  return {
    account_id: id,
    balance: 0,
    plan: p,
    status: "ACTIVE",
    expires_at: until.getFullYear() + "-" + pad(until.getMonth() + 1) + "-" + pad(until.getDate()),
    payments,
  };
}

async function fetchBilling(plan) {
  try {
    const data = await api("/api/billing");
    if (data && data.account_id) return data;
  } catch (e) {}
  return billingFallback(plan);
}

function payStatusLabel(st) {
  return st === "paid" ? "To‘langan" : "To‘lanmagan";
}

function payMethodLabel(m) {
  if (!m) return "—";
  const v = String(m).toLowerCase();
  if (v === "click") return "Click";
  if (v === "payme") return "Payme";
  if (v === "cash" || v === "naqd") return "Naqd";
  return m;
}

function billingRequisites(accountId, plan) {
  const id = accountId ?? "";
  const p = plan || "PRO";
  return `ТЎЛОВ РЕКВИЗИТЛАРИ: "URGUT-INOVATSION" MCHJ, СИТР: 309706996, ҳисоб рақам: 20208000905546514002, МФО: 01183, "ANOR BANK" АКЦИЯДОРЛИК ЖАМИЯТИ, (тўлов мақсади: Оммавий оферта шартномасига асосан ID: ${id} учун ${p} тариф бўйича абонент тўлови кўчирилди)`;
}

function renderBilling(b) {
  const rows = b.payments || [];
  const body = rows.length
    ? rows
        .map(
          (r, i) => `<tr>
            <td>${esc(r.n || i + 1)}</td>
            <td>${esc(fmtDay(r.at))}</td>
            <td>${esc(r.period || "—")}</td>
            <td>${money(r.amount)}</td>
            <td>${esc(payMethodLabel(r.method))}</td>
            <td><span class="pay-st ${r.status === "paid" ? "pay-paid" : "pay-due"}">${payStatusLabel(r.status)}</span></td>
          </tr>`
        )
        .join("")
    : '<tr><td colspan="6" class="muted">Hali to‘lovlar yo‘q</td></tr>';
  const active = String(b.status || "ACTIVE").toUpperCase() === "ACTIVE";
  return `
    <section class="bill-wrap" id="billing">
      <div class="card bill-card">
        <div class="bill-head">
          <div>
            <div class="kicker">Billing</div>
            <h3>Shaxsiy hisob va Tariflar</h3>
          </div>
          <span class="bill-status ${active ? "on" : "off"}">${esc(b.status || (active ? "AKTIV" : "NOFAOL"))}</span>
        </div>
        <div class="bill-kpis">
          <div class="bill-kpi">
            <span>Foydalanuvchi ID</span>
            <b class="bill-id">ID: ${esc(b.account_id)}</b>
          </div>
          <div class="bill-kpi">
            <span>Balans</span>
            <b>${money(b.balance)}</b>
          </div>
          <div class="bill-kpi">
            <span>Joriy tarif</span>
            <b>${esc(b.plan || "FREE")} tarif</b>
          </div>
          <div class="bill-kpi">
            <span>Amal qilish</span>
            <b>${active ? "AKTIV" : "NOFAOL"} — ${esc(fmtDay(b.expires_at))} gacha</b>
          </div>
        </div>
        <p class="bill-hint">
          Holat: <b>${esc(b.status || "")}</b>
          ${b.usage ? ` · Do‘kon ${b.usage.stores}/${b.limits?.stores} · User ${b.usage.users}/${b.limits?.users}` : ""}
        </p>
        <div class="row" id="bill-checkout">
          <select class="field" id="bill-plan" style="max-width:160px">
            <option value="PRO">PRO</option>
            <option value="ENTERPRISE">ENTERPRISE</option>
            <option value="VIP">VIP</option>
          </select>
        </div>
        <div class="card" id="bill-requisites" data-account-id="${esc(b.account_id)}" style="margin-top:12px">
          <pre class="muted" style="white-space:pre-wrap;margin:0">${esc(billingRequisites(b.account_id, b.plan))}</pre>
        </div>
      </div>
      <div class="card bill-table-card">
        <div class="bill-table-head"><b>To‘lovlar tarixi</b></div>
        <div class="table-scroll">
          <table class="table">
            <thead>
              <tr>
                <th>№</th>
                <th>Sana</th>
                <th>Oy</th>
                <th>Summa</th>
                <th>To‘lov turi</th>
                <th>Holati</th>
              </tr>
            </thead>
            <tbody>${body}</tbody>
          </table>
        </div>
        <a class="offer-link" href="/assets/docs/oferta.html" target="_blank" rel="noopener">Ommaviy oferta shartnomasini ko‘rish</a>
      </div>
    </section>`;
}

async function pageSettings() {
  const s = await api("/api/settings");
  const local = loadLocalSettings();
  const init = { ...s, ...(local || {}) };
  init.plan = s.plan;
  let billing = billingFallback(init.plan);
  try {
    const remote = await fetchBilling(init.plan);
    if (remote && remote.account_id) billing = remote;
  } catch (e) {}
  const v = (k) => esc(init[k] || "");
  return `
    <h2>Sozlamalar</h2>
    <div class="card">
      <h3>Kassir kompyuteri</h3>
      <p class="muted">Brauzer .exe/.zip ni bloklaydi. Yorliqni shu yerda yaratamiz.</p>
      <p><button type="button" id="kiosk-copy" class="btn btn-gold">Yorliq skriptini nusxalash</button></p>
      <ol class="muted">
        <li>Win+R → powershell → Enter</li>
        <li>O'ng tugma bilan joylashtiring (Ctrl+V) → Enter</li>
        <li>Ish stolida FIXEN POS chiqadi</li>
      </ol>
      <p class="muted">Edge/Chrome da: ⋮ → Ilovani o'rnatish / Install this site as an app</p>
      <p class="muted" style="font-size:smaller">Agar oldingi yuklama bloklansa, yuklamalar belgisida strelka → Keep anyway.</p>
    </div>
    ${renderBilling(billing)}
    <h3 class="set-sub">Do‘kon ma’lumotlari</h3>
    <form id="set-form" class="card">
      <div class="set-grid">
        <label class="set-field">Kompaniya
          <input class="field" name="company_name" placeholder="Kompaniya nomi" value="${v("company_name")}" />
        </label>
        <label class="set-field">INN
          <input class="field" name="inn" id="set-inn" placeholder="9 raqam" inputmode="numeric" maxlength="9" value="${v("inn")}" />
        </label>
        <label class="set-field">Telefon
          <input class="field" name="phone" placeholder="Telefon" value="${v("phone")}" />
        </label>
        <label class="set-field">Do‘kon telefon
          <input class="field" name="store_phone" placeholder="Do‘kon telefon" value="${v("store_phone")}" />
        </label>
        <label class="set-field">Manzil
          <input class="field" name="address" placeholder="Manzil" value="${v("address")}" />
        </label>
        <label class="set-field">Do‘kon manzili
          <input class="field" name="store_address" placeholder="Do‘kon manzili" value="${v("store_address")}" />
        </label>
        <label class="set-field set-span-2">Do‘kon nomi
          <input class="field" name="store_name" placeholder="Do‘kon nomi" value="${v("store_name")}" />
        </label>
        <label class="set-field">Valyuta
          <select class="field" name="currency">
            ${["UZS", "USD", "EUR", "RUB", "KZT"].map((c) => `<option ${init.currency === c ? "selected" : ""}>${c}</option>`).join("")}
          </select>
        </label>
        <label class="set-field">QQS %
          <input class="field" name="vat_percent" type="number" step="0.01" value="${esc(init.vat_percent || 0)}" />
        </label>
        <label class="set-field">Til
          <select class="field" name="locale">
            ${["uz", "ru", "en"].map((c) => `<option ${init.locale === c ? "selected" : ""}>${c}</option>`).join("")}
          </select>
        </label>
        <div class="set-span-2">
          <button class="btn btn-gold" type="submit">Saqlash</button>
        </div>
      </div>
      <div id="set-msg"></div>
    </form>
    <h3 class="set-sub">Parol</h3>
    <form id="pw-form" class="card">
      <div class="set-grid">
        <label class="set-field">Joriy parol
          <input class="field" type="password" name="current_password" required autocomplete="current-password" />
        </label>
        <label class="set-field">Yangi parol
          <input class="field" type="password" name="new_password" required minlength="6" autocomplete="new-password" />
        </label>
        <label class="set-field">Yangi parol (takror)
          <input class="field" type="password" name="new_password2" required minlength="6" autocomplete="new-password" />
        </label>
        <div class="set-span-2">
          <button class="btn btn-gold" type="submit">Parolni saqlash</button>
        </div>
      </div>
      <div id="pw-msg"></div>
    </form>`;
}


async function fetchReports(params) {
  const q = new URLSearchParams(params);
  return api("/api/reports/analytics?" + q.toString());
}

function hisRange(state) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  if (state.preset === "today") return { date_from: ymd(today), date_to: ymd(today) };
  if (state.preset === "yesterday") {
    const y = new Date(today);
    y.setDate(y.getDate() - 1);
    return { date_from: ymd(y), date_to: ymd(y) };
  }
  if (state.preset === "month") {
    const from = new Date(today.getFullYear(), today.getMonth(), 1);
    return { date_from: ymd(from), date_to: ymd(today) };
  }
  return { date_from: state.date_from || "", date_to: state.date_to || "" };
}

function drawHisChart(chart) {
  const canvas = document.getElementById("his-chart");
  if (!canvas || typeof window.Chart === "undefined") return;
  if (window.__hisChart) {
    window.__hisChart.destroy();
    window.__hisChart = null;
  }
  window.__hisChart = new window.Chart(canvas, {
    type: "bar",
    data: {
      labels: chart.labels || [],
      datasets: [
        { label: "Kirim", data: chart.kirim || [], backgroundColor: "rgba(57,255,136,.75)", borderRadius: 6 },
        { label: "Chiqim", data: chart.chiqim || [], backgroundColor: "rgba(212,175,55,.8)", borderRadius: 6 },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { labels: { color: "#e8eefc" } } },
      scales: {
        x: { ticks: { color: "#8b97b3" }, grid: { color: "rgba(255,255,255,.06)" } },
        y: { ticks: { color: "#8b97b3" }, grid: { color: "rgba(255,255,255,.06)" } },
      },
    },
  });
}

function nextHisobotNo() {
  const key = "finex_hisobot_no_" + (user()?.company_id || "0");
  const n = Number(localStorage.getItem(key) || 0) + 1;
  localStorage.setItem(key, String(n));
  return String(n).padStart(5, "0");
}

function excelSerial(iso) {
  const raw = String(iso || "").slice(0, 10);
  const p = raw.split("-");
  if (p.length !== 3) return null;
  const y = Number(p[0]);
  const m = Number(p[1]);
  const d = Number(p[2]);
  if (!y || !m || !d) return null;
  return Math.round((Date.UTC(y, m - 1, d) - Date.UTC(1899, 11, 30)) / 86400000);
}

function dmy(iso) {
  const raw = String(iso || "").slice(0, 10);
  const p = raw.split("-");
  if (p.length !== 3) return raw;
  return p[2] + "." + p[1] + "." + p[0];
}

function hisobotFileName(dateFrom, dateTo) {
  const a = dmy(dateFrom) || "";
  const b = dmy(dateTo) || "";
  if (a && b) return "Finex_Hisobot (" + a + "-" + b + ").xlsx";
  return "Finex_Hisobot.xlsx";
}

function moneyFmt() {
  return '_-* #,##0.00_-;\-* #,##0.00_-;_-* "-"??_-;_-@_-';
}

function setDateCell(ws, addr, iso) {
  const serial = excelSerial(iso);
  if (serial == null) {
    ws[addr] = { t: "s", v: iso || "" };
    return;
  }
  ws[addr] = { t: "n", v: serial, z: "dd.mm.yyyy" };
}

function buildFinexHisobotWb(payload, reportNo) {
  const XLSX = window.XLSX;
  const range = hisRange(window.__his || {});
  const dateFrom = payload.date_from || range.date_from || "";
  const dateTo = payload.date_to || range.date_to || "";
  const shop = payload.store_name || (user() && user().store_name) || (user() && user().company_name) || "";
  const no = reportNo || nextHisobotNo();
  const rows = payload.rows || window.__hisRows || [];
  const kirim = rows.filter((r) => r.type === "kirim").reduce((s, r) => s + Number(r.amount || 0), 0);
  const chiqim = rows.filter((r) => r.type === "chiqim").reduce((s, r) => s + Number(r.amount || 0), 0);
  const opening = Number(payload.opening_stock || 0);
  const closing = opening + kirim - chiqim;
  const fmt = moneyFmt();

  const logAoA = [
    ["Finex-hisobot №", no, "", "", "hisobot davri boshlanishi", ""],
    ["Do'kon nomi", shop, "", "", "hisobot davri tugashi", ""],
    [],
    ["Sana", "Tur", "Mahsulot/Kategoriya", "Miqdor", "Summa", "Hujjat"],
  ];
  rows.forEach((r) => {
    logAoA.push([
      (r.at || "").slice(0, 19).replace("T", " "),
      r.type === "kirim" ? "Kirim" : "Chiqim",
      r.title || "",
      Number(r.qty || 0),
      Number(r.amount || 0),
      r.ref || "",
    ]);
  });
  logAoA.push([]);
  logAoA.push(["Davr boshidagi qoldiq:", "", opening]);
  logAoA.push(["Hisobot davrida kirim:", "", Math.round(kirim * 100) / 100]);
  logAoA.push(["Hisobot davrida chiqim:", "", Math.round(chiqim * 100) / 100]);
  logAoA.push(["Davr oxiridagi qoldiq:", "", Math.round(closing * 100) / 100]);

  const ws1 = XLSX.utils.aoa_to_sheet(logAoA);
  setDateCell(ws1, "F1", dateFrom);
  setDateCell(ws1, "F2", dateTo);
  const firstData = 5;
  const lastData = 4 + rows.length;
  for (let r = firstData; r <= lastData; r++) {
    const cell = ws1[XLSX.utils.encode_cell({ r: r - 1, c: 4 })];
    if (cell && cell.t === "n") cell.z = fmt;
  }
  ["C20", "C21", "C22", "C23"].forEach((addr) => {
    const real = XLSX.utils.encode_cell({ r: logAoA.length - 4 + ["C20", "C21", "C22", "C23"].indexOf(addr), c: 2 });
    const cell = ws1[real];
    if (cell && cell.t === "n") cell.z = fmt;
  });
  const totStart = logAoA.length - 4;
  for (let i = 0; i < 4; i++) {
    const cell = ws1[XLSX.utils.encode_cell({ r: totStart + i, c: 2 })];
    if (cell && typeof cell.v === "number") cell.z = fmt;
  }
  ws1["!cols"] = [
    { wch: 20.4 },
    { wch: 10.4 },
    { wch: 19.8 },
    { wch: 12.1 },
    { wch: 12.8 },
    { wch: 19 },
  ];
  if (ws1["!rows"]) ws1["!rows"][3] = { hpt: 27.75 };
  else ws1["!rows"] = [null, null, null, { hpt: 27.75 }];

  const turn = payload.turnover || [];
  const qayAoA = [
    ["", "Finex-hisobot №", no, "", "", "", "hisobot davri boshlanishi", ""],
    ["", "Do'kon nomi", shop, "", "", "", "hisobot davri tugashi", ""],
    ["№", "Tovarlar nomi", "O'lchov birligi", "Narxi", "Davr boshiga qoldiq", "", "Kirim", "", "Chiqim", "", "Davr oxiriga qoldiq", ""],
    ["", "", "", "", "Miqdor", "Summa", "Miqdor", "Summa", "Miqdor", "Summa", "Miqdor", "Summa"],
    ["", "", "", "", "", "", "", "", "", "", "", ""],
    ["Jami", "", "", "", 0, 0, 0, 0, 0, 0, 0, 0],
  ];
  turn.forEach((t) => {
    qayAoA.push([
      t.n,
      t.name || "",
      t.unit || "",
      Number(t.price || 0),
      Number(t.open_qty || 0),
      Number(t.open_sum || 0),
      Number(t.in_qty || 0),
      Number(t.in_sum || 0),
      Number(t.out_qty || 0),
      Number(t.out_sum || 0),
      Number(t.close_qty || 0),
      Number(t.close_sum || 0),
    ]);
  });
  const firstProd = 7;
  const lastProd = turn.length ? 6 + turn.length : 6;
  qayAoA.push([]);
  qayAoA.push([]);
  qayAoA.push(["", "Do'kon mudiri _________________________________"]);

  const ws2 = XLSX.utils.aoa_to_sheet(qayAoA);
  setDateCell(ws2, "H1", dateFrom);
  setDateCell(ws2, "H2", dateTo);
  const sumRow = 6;
  const sumCols = [4, 5, 6, 7, 8, 9, 10, 11];
  sumCols.forEach((c) => {
    const addr = XLSX.utils.encode_cell({ r: sumRow - 1, c: c });
    const col = XLSX.utils.encode_col(c);
    if (turn.length) {
      ws2[addr] = { t: "n", f: "SUM(" + col + firstProd + ":" + col + lastProd + ")", z: c % 2 === 1 ? fmt : "0.000" };
    } else {
      ws2[addr] = { t: "n", v: 0, z: c % 2 === 1 ? fmt : "0.000" };
    }
  });
  for (let r = firstProd; r <= lastProd; r++) {
    [3, 5, 7, 9, 11].forEach((c) => {
      const cell = ws2[XLSX.utils.encode_cell({ r: r - 1, c: c })];
      if (cell && cell.t === "n") cell.z = fmt;
    });
  }
  ws2["!merges"] = [
    { s: { r: 2, c: 0 }, e: { r: 4, c: 0 } },
    { s: { r: 2, c: 1 }, e: { r: 4, c: 1 } },
    { s: { r: 2, c: 2 }, e: { r: 4, c: 2 } },
    { s: { r: 2, c: 3 }, e: { r: 4, c: 3 } },
    { s: { r: 2, c: 4 }, e: { r: 2, c: 5 } },
    { s: { r: 2, c: 6 }, e: { r: 2, c: 7 } },
    { s: { r: 2, c: 8 }, e: { r: 2, c: 9 } },
    { s: { r: 2, c: 10 }, e: { r: 2, c: 11 } },
    { s: { r: 3, c: 4 }, e: { r: 4, c: 4 } },
    { s: { r: 3, c: 5 }, e: { r: 4, c: 5 } },
    { s: { r: 3, c: 6 }, e: { r: 4, c: 6 } },
    { s: { r: 3, c: 7 }, e: { r: 4, c: 7 } },
    { s: { r: 3, c: 8 }, e: { r: 4, c: 8 } },
    { s: { r: 3, c: 9 }, e: { r: 4, c: 9 } },
    { s: { r: 3, c: 10 }, e: { r: 4, c: 10 } },
    { s: { r: 3, c: 11 }, e: { r: 4, c: 11 } },
    { s: { r: 5, c: 0 }, e: { r: 5, c: 3 } },
  ];
  ws2["!cols"] = [
    { wch: 6.8 },
    { wch: 31.1 },
    { wch: 11 },
    { wch: 9.6 },
    { wch: 12.1 },
    { wch: 16.6 },
    { wch: 12 },
    { wch: 16.6 },
    { wch: 12.7 },
    { wch: 16.6 },
    { wch: 12.3 },
    { wch: 16.6 },
  ];

  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws1, "Сум");
  XLSX.utils.book_append_sheet(wb, ws2, "Микдор");
  wb.__fileName = hisobotFileName(dateFrom, dateTo);
  return wb;
}

async function exportHisExcel() {
  const downloadBlob = (blob, name) => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1500);
  };
  const state = window.__his || {};
  const range = hisRange(state);
  const no = nextHisobotNo();
  try {
    const q = new URLSearchParams({
      date_from: range.date_from || "",
      date_to: range.date_to || "",
      op_type: state.op_type || "all",
      report_no: no,
    });
    const res = await fetch("/api/reports/export?" + q.toString(), {
      headers: token() ? { Authorization: "Bearer " + token() } : {},
    });
    if (res.ok) {
      downloadBlob(await res.blob(), hisobotFileName(range.date_from, range.date_to));
      return;
    }
  } catch (e) {}
  let payload = window.__hisData;
  if (!payload) {
    const state = window.__his || {};
    const range = hisRange(state);
    try {
      payload = await fetchReports({
        date_from: range.date_from || "",
        date_to: range.date_to || "",
        op_type: state.op_type || "all",
      });
    } catch (e) {
      payload = { rows: window.__hisRows || [], turnover: [] };
    }
  }
  if (window.XLSX && window.XLSX.utils) {
    const wb = buildFinexHisobotWb(payload, no);
    window.XLSX.writeFile(wb, wb.__fileName || "Finex_Hisobot.xlsx");
    return;
  }
  const q = new URLSearchParams({
    date_from: (payload && payload.date_from) || "",
    date_to: (payload && payload.date_to) || "",
    op_type: (window.__his && window.__his.op_type) || "all",
  });
  const res = await fetch("/api/reports/export?" + q.toString(), {
    headers: token() ? { Authorization: "Bearer " + token() } : {},
  });
  if (res.ok) downloadBlob(await res.blob(), "Finex_Hisobot.xlsx");
}

async function pageHisobotlar() {
  window.__his = window.__his || { preset: "month", date_from: "", date_to: "", op_type: "all" };
  return `
    <h2>Hisobotlar</h2>
    <p class="muted">Kirim, chiqim va ombor qiymati — tanlangan davr bo‘yicha.</p>
    <div class="card sales-filters">
      <div class="chip-row">
        <button type="button" class="chip" data-hpreset="today">Bugun</button>
        <button type="button" class="chip" data-hpreset="yesterday">Kecha</button>
        <button type="button" class="chip" data-hpreset="month">Oy</button>
      </div>
      <div class="grid3" style="margin-top:12px">
        <input class="field" type="date" id="his-from" />
        <input class="field" type="date" id="his-to" />
        <select class="field" id="his-type">
          <option value="all">Barcha operatsiyalar</option>
          <option value="kirim">Faqat Kirim</option>
          <option value="chiqim">Faqat Chiqim</option>
        </select>
      </div>
    </div>
    <div class="kpi his-kpi" id="his-kpis"></div>
    <div class="card his-chart-card"><canvas id="his-chart"></canvas></div>
    <div class="his-table-head">
      <b>Operatsiyalar</b>
      <button type="button" class="btn btn-excel" id="his-excel">Excel-ga yuklash</button>
    </div>
    <table class="table" id="his-table">
      <thead><tr><th>Sana</th><th>Tur</th><th>Mahsulot / kategoriya</th><th>Miqdor</th><th>Summa</th></tr></thead>
      <tbody id="his-body"></tbody>
    </table>`;
}

async function loadHisobotlar() {
  const state = window.__his;
  const bodyEl = document.getElementById("his-body");
  if (!state || !bodyEl) return;
  const range = hisRange(state);
  let data;
  try {
    data = await fetchReports({
      date_from: range.date_from || "",
      date_to: range.date_to || "",
      op_type: state.op_type || "all",
    });
  } catch (ex) {
    bodyEl.innerHTML = '<tr><td colspan="5" class="err">' + esc(ex.message || "Hisobot yuklanmadi") + "</td></tr>";
    return;
  }
  window.__hisRows = data.rows || [];
  window.__hisData = data;
  document.getElementById("his-kpis").innerHTML = `
    <div class="card kpi-card his-in"><div class="kpi-head"><span>Aqlli Kirim</span></div><b>${money(data.kirim)}</b><p class="muted">Tovar xarid / inflou</p></div>
    <div class="card kpi-card his-out"><div class="kpi-head"><span>Aqlli Chiqim</span></div><b>${money(data.chiqim)}</b><p class="muted">Savdo + xarajat</p></div>
    <div class="card kpi-card his-stock"><div class="kpi-head"><span>Ombor qoldig‘i</span></div><b>${money(data.stock_value)}</b><p class="muted">qoldiq × xarid narxi</p></div>`;
  drawHisChart(data.chart || { labels: [], kirim: [], chiqim: [] });
  bodyEl.innerHTML = (data.rows || []).length
    ? data.rows
        .map(
          (r) => `<tr>
            <td>${saleWhen(r.at)}</td>
            <td class="${r.type === "chiqim" ? "stock-low" : "ok"}">${r.type === "kirim" ? "KIRIM" : "CHIQIM"}</td>
            <td>${esc(r.title)}${r.ref ? ` <span class="muted">${esc(r.ref)}</span>` : ""}</td>
            <td>${r.qty}</td>
            <td>${money(r.amount)}</td>
          </tr>`
        )
        .join("")
    : '<tr><td colspan="5" class="muted">Ma’lumot yo‘q</td></tr>';
  document.querySelectorAll("[data-hpreset]").forEach((b) => b.classList.toggle("active", b.dataset.hpreset === state.preset));
  const fromEl = document.getElementById("his-from");
  const toEl = document.getElementById("his-to");
  if (fromEl) fromEl.value = range.date_from || "";
  if (toEl) toEl.value = range.date_to || "";
  const typeEl = document.getElementById("his-type");
  if (typeEl) typeEl.value = state.op_type || "all";
}

function bindHisobotlar() {
  if (!document.getElementById("his-body")) return;
  window.__his = window.__his || { preset: "month", date_from: "", date_to: "", op_type: "all" };
  const state = window.__his;
  document.querySelectorAll("[data-hpreset]").forEach((btn) => {
    btn.onclick = () => {
      state.preset = btn.dataset.hpreset;
      if (state.preset !== "range") {
        state.date_from = "";
        state.date_to = "";
      }
      loadHisobotlar();
    };
  });
  document.getElementById("his-from")?.addEventListener("change", (e) => {
    state.preset = "range";
    state.date_from = e.target.value;
    state.date_to = document.getElementById("his-to")?.value || state.date_to || e.target.value;
    loadHisobotlar();
  });
  document.getElementById("his-to")?.addEventListener("change", (e) => {
    state.preset = "range";
    state.date_to = e.target.value;
    state.date_from = document.getElementById("his-from")?.value || state.date_from || e.target.value;
    loadHisobotlar();
  });
  document.getElementById("his-type")?.addEventListener("change", (e) => {
    state.op_type = e.target.value;
    loadHisobotlar();
  });
  document.getElementById("his-excel")?.addEventListener("click", () => exportHisExcel(window.__hisRows || []));
  loadHisobotlar();
}

async function renderApp() {
  if (!user()) {
    location.hash = "#/login";
    return render();
  }
  const page = (location.hash.split("/")[2] || "dashboard").split("?")[0];
  if (page === "dashboard" && !can("reports")) {
    location.hash = "#/app/pos";
    return;
  }
  const loaders = {
    dashboard: pageDashboard,
    products: pageProducts,
    stock: pageStock,
    opname: pageOpname,
    pos: pagePos,
    sales: pageSales,
    hisobotlar: pageHisobotlar,
    customers: pageCustomers,
    cash: pageCash,
    expenses: pageExpenses,
    staff: pageStaff,
    settings: pageSettings,
    stores: () => pageStores(api, money),
    suppliers: () => pageSuppliers(api),
    transfers: () => pageTransfers(api),
  };
  const fn = loaders[page] || (can("reports") ? pageDashboard : pagePos);
  try {
    root.innerHTML = shell("Yuklanmoqda...");
    const html = await fn();
    root.innerHTML = shell(html);
    bindApp(page);
    bindSaas(page, api, setAuth, render);
  } catch (e) {
    root.innerHTML = shell(`<p class="err">${esc(e.message)}</p>`);
    bindApp(page);
    bindSaas(page, api, setAuth, render);
  }
}

function bindApp(page) {
  document.getElementById("imp-exit")?.addEventListener("click", logout);
  document.getElementById("logout")?.addEventListener("click", logout);
  document.querySelectorAll("[data-go]").forEach((el) => {
    el.onclick = () => {
      location.hash = el.dataset.go;
    };
  });
  document.querySelectorAll("[data-lang]").forEach((b) => {
    b.onclick = () => {
      setLang(b.dataset.lang);
      render();
    };
  });
  document.getElementById("store-switch")?.addEventListener("change", async (e) => {
    const data = await api("/api/auth/switch-store", { method: "POST", body: JSON.stringify({ store_id: Number(e.target.value) }) });
    setAuth(data);
    render();
  });

  const pForm = document.getElementById("p-form");
  if (pForm) {
    document.getElementById("p-barcode-auto")?.addEventListener("click", () => {
      if (pForm.barcode) pForm.barcode.value = makeBarcode();
    });
    document.getElementById("p-prev")?.addEventListener("click", () => {
      window.__prodPage = Math.max(1, Number(window.__prodPage || 1) - 1);
      render();
    });
    document.getElementById("p-next")?.addEventListener("click", () => {
      window.__prodPage = Math.max(1, Number(window.__prodPage || 1) + 1);
      render();
    });
    pForm.onsubmit = async (e) => {
      e.preventDefault();
      const err = document.getElementById("p-err");
      if (err) err.textContent = "";
      const f = Object.fromEntries(new FormData(pForm).entries());
      const name = (f.name || "").trim();
      let barcode = (f.barcode || "").trim();
      if (!barcode) {
        barcode = makeBarcode();
        if (pForm.barcode) pForm.barcode.value = barcode;
      }
      const sell = Number(f.sell_price);
      const buy = Number(f.buy_price || 0);
      const missing = [];
      if (!name) missing.push("Nomi");
      if (f.sell_price === undefined || f.sell_price === "") missing.push("Sotuv narxi");
      if (missing.length) {
        if (err) err.textContent = "Majburiy: " + missing.join(", ");
        return;
      }
      if (Number.isNaN(sell) || sell < 0) {
        if (err) err.textContent = "Sotuv narxi noto‘g‘ri";
        return;
      }
      if (sell < buy) {
        if (err) err.textContent = "Sotuv narxi xarid narxidan kam bo‘lmasin";
        return;
      }
      const payload = {
        name,
        barcode,
        sku: f.sku || "",
        category_id: f.category_id ? Number(f.category_id) : null,
        manufacturer: (f.manufacturer || "").trim(),
        sell_price: sell,
        buy_price: buy,
        min_stock: Number(f.min_stock || 0),
        unit: f.unit || "dona",
        is_active: Boolean(pForm.elements.is_active?.checked),
      };
      if (!f.id) payload.stock = Number(f.stock || 0);
      try {
        if (f.id) await api(`/api/products/${f.id}`, { method: "PATCH", body: JSON.stringify(payload) });
        else await api("/api/products", { method: "POST", body: JSON.stringify(payload) });
        render();
      } catch (ex) {
        if (err) err.textContent = ex.message;
      }
    };
    document.querySelectorAll("[data-cennik]").forEach((btn) => {
      btn.onclick = () => {
        const p = (window.__products || []).find((x) => x.id === Number(btn.dataset.cennik));
        if (p) openCennikModal(p);
      };
    });
    document.querySelectorAll("[data-edit]").forEach((btn) => {
      btn.onclick = () => {
        const p = JSON.parse(btn.dataset.edit);
        pForm.id.value = p.id;
        pForm.name.value = p.name;
        pForm.barcode.value = p.barcode || "";
        pForm.sku.value = p.sku || "";
        if (pForm.category_id) pForm.category_id.value = p.category_id || "";
        if (pForm.manufacturer) pForm.manufacturer.value = p.manufacturer || "";
        pForm.sell_price.value = p.sell_price;
        pForm.buy_price.value = p.buy_price;
        if (pForm.stock) pForm.stock.value = "";
        const stockWrap = document.getElementById("p-stock-wrap");
        if (stockWrap) stockWrap.hidden = true;
        if (pForm.elements.is_active) pForm.elements.is_active.checked = p.is_active !== false;
        pForm.min_stock.value = p.min_stock;
        pForm.unit.value = p.unit;
        document.getElementById("p-save").textContent = "Yangilash";
        window.scrollTo({ top: 0, behavior: "smooth" });
      };
    });
    document.getElementById("p-filter")?.addEventListener("input", (e) => {
      const q = e.target.value.trim().toLowerCase();
      document.querySelectorAll("#p-table tbody tr").forEach((tr) => {
        const name = tr.dataset.name || "";
        const barcode = tr.dataset.barcode || "";
        tr.hidden = Boolean(q) && !name.includes(q) && !barcode.includes(q);
      });
    });
    document.querySelectorAll("[data-history]").forEach((btn) => {
      btn.onclick = () => {
        const p = (window.__products || []).find((x) => x.id === Number(btn.dataset.history));
        if (p) {
          window.__stockHist = { page: 1, kind: "", product: p };
          openStockHistory(p);
        }
      };
    });
    document.querySelectorAll("[data-adjust]").forEach((btn) => {
      btn.onclick = () => {
        const p = (window.__products || []).find((x) => x.id === Number(btn.dataset.adjust));
        if (p) openStockAdjust(p);
      };
    });
    document.querySelectorAll("[data-toggle]").forEach((btn) => {
      btn.onclick = async () => {
        if (btn.dataset.active === "1") {
          const ok = await askConfirm({
            title: "O'chirishni tasdiqlang",
            text: `"${btn.dataset.name}" tovarini o‘chirasizmi? U POS ro‘yxatidan yashiriladi.`,
            okLabel: "O'chirish",
          });
          if (!ok) return;
        }
        await api(`/api/products/${btn.dataset.toggle}/toggle`, { method: "POST" });
        render();
      };
    });
  }

  const inForm = document.getElementById("in-form");
  if (inForm) {
    const barcodeEl = document.getElementById("in-barcode");
    const productEl = document.getElementById("in-product");
    const qtyEl = document.getElementById("in-qty");
    const buyEl = document.getElementById("in-buy");
    const hintEl = document.getElementById("in-barcode-hint");

    const tryAddLine = (fromBarcode) => {
      stockFormError("");
      let product = null;
      if (fromBarcode) product = findStockProduct(barcodeEl?.value);
      else {
        const id = Number(productEl?.value);
        product = window.__stock.products.find((x) => x.id === id) || findStockProduct(barcodeEl?.value);
      }
      if (!product) {
        stockFormError(fromBarcode ? "Barcode bo‘yicha mahsulot topilmadi" : "Mahsulot tanlang");
        return false;
      }
      const qty = Number(qtyEl?.value || (fromBarcode ? 1 : 0));
      if (!(qty > 0)) {
        stockFormError("Miqdorni kiriting");
        qtyEl?.focus();
        return false;
      }
      addStockLine(product, qty, buyEl?.value);
      if (productEl) productEl.value = String(product.id);
      if (qtyEl) qtyEl.value = "";
      if (barcodeEl) barcodeEl.value = "";
      if (buyEl) buyEl.value = "";
      if (hintEl) hintEl.textContent = "";
      drawStockLines();
      barcodeEl?.focus();
      return true;
    };

    drawStockLines();
    productEl?.addEventListener("change", () => {
      const p = window.__stock.products.find((x) => x.id === Number(productEl.value));
      fillStockBuy(p);
      if (p && hintEl) hintEl.textContent = p.barcode ? "Barcode: " + p.barcode : "";
    });
    barcodeEl?.addEventListener("input", () => {
      const p = findStockProduct(barcodeEl.value);
      if (p) {
        fillStockBuy(p);
        if (hintEl) hintEl.textContent = p.name;
      } else if (hintEl) hintEl.textContent = barcodeEl.value.trim() ? "Qidirilmoqda…" : "";
    });
    barcodeEl?.addEventListener("keydown", (e) => {
      if (e.key !== "Enter") return;
      e.preventDefault();
      tryAddLine(true);
    });
    document.getElementById("in-add")?.addEventListener("click", () => tryAddLine(false));
    document.getElementById("in-lines")?.addEventListener("click", (e) => {
      const rm = e.target.closest("[data-rm]");
      if (!rm) return;
      window.__stock.lines.splice(Number(rm.dataset.rm), 1);
      drawStockLines();
    });
    inForm.onsubmit = async (e) => {
      e.preventDefault();
      stockFormError("");
      const f = Object.fromEntries(new FormData(inForm).entries());
      if (!window.__stock.lines.length) {
        stockFormError(EMPTY_STOCK_MSG);
        document.querySelector(".empty-warn")?.scrollIntoView({ behavior: "smooth", block: "center" });
        return;
      }
      const inBtn = inForm.querySelector("button[type=submit]");
      if (inBtn) inBtn.disabled = true;
      try {
        await api("/api/stock-ins", {
          method: "POST",
          body: JSON.stringify({
            supplier: f.supplier,
            note: f.note,
            items: window.__stock.lines.map((l) => ({
              product_id: l.product_id,
              qty: l.qty,
              buy_price: l.buy_price,
            })),
          }),
        });
        render();
      } catch (ex) {
        stockFormError(ex.message);
        if (inBtn) inBtn.disabled = false;
      }
    };
    document.querySelectorAll("[data-doc]").forEach((row) => {
      row.onclick = async () => {
        const d = await api(`/api/stock-ins/${row.dataset.doc}`);
        const sum = (d.items || []).reduce((s, i) => s + Number(i.qty) * Number(i.buy_price || 0), 0);
        document.getElementById("in-detail").innerHTML = `<div class="card"><b>${esc(d.number)}</b>
          <div class="muted">${fmtDate(d.created_at)} · ${esc(d.supplier || "—")}</div>
          ${(d.items || [])
            .map((i) => `<div class="muted">${esc(i.name)} × ${i.qty} · ${money(i.buy_price)} = ${money(Number(i.qty) * Number(i.buy_price || 0))}</div>`)
            .join("")}
          <div style="margin-top:8px"><b>Jami: ${money(d.total || sum)}</b></div>
        </div>`;
      };
    });
  }

  const cashForm = document.getElementById("cash-form");
  if (cashForm) {
    cashForm.onsubmit = async (e) => {
      e.preventDefault();
      const err = document.getElementById("cash-err");
      if (err) err.textContent = "";
      const f = Object.fromEntries(new FormData(cashForm).entries());
      const kind = f.kind;
      const amount = Number(f.amount);
      const note = (f.note || "").trim();
      if (!kind) {
        if (err) err.textContent = "Kirim yoki Chiqim tanlang";
        return;
      }
      if (!(amount > 0)) {
        if (err) err.textContent = "Summa majburiy";
        return;
      }
      if (!note) {
        if (err) err.textContent = "Izoh majburiy";
        return;
      }
      try {
        await api("/api/cash", { method: "POST", body: JSON.stringify({ kind, amount, note }) });
        cashForm.reset();
        cashForm.kind.value = "IN";
        render();
      } catch (ex) {
        if (err) err.textContent = ex.message;
      }
    };
    document.getElementById("cash-table")?.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-sale-id]");
      if (btn && typeof openSaleModal === "function") openSaleModal(Number(btn.dataset.saleId));
    });
  }

  const exForm = document.getElementById("ex-form");
  if (exForm) {
    exForm.onsubmit = async (e) => {
      e.preventDefault();
      const err = document.getElementById("ex-err");
      if (err) err.textContent = "";
      const f = Object.fromEntries(new FormData(exForm).entries());
      const category = (f.category || "").trim();
      const amountRaw = String(f.amount || "").trim();
      const amount = Number(amountRaw);
      if (!category) {
        if (err) err.textContent = "Kategoriya tanlang";
        return;
      }
      if (!amountRaw || Number.isNaN(amount) || amount <= 0) {
        if (err) err.textContent = "Summa faqat musbat raqam bo‘lsin";
        return;
      }
      try {
        await api("/api/expenses", {
          method: "POST",
          body: JSON.stringify({ category, amount, note: (f.note || "").trim() }),
        });
        exForm.reset();
        exForm.category.value = "Ijara";
        render();
      } catch (ex) {
        if (err) err.textContent = ex.message;
      }
    };
  }

  const cForm = document.getElementById("c-form");
  if (cForm) {
    cForm.onsubmit = async (e) => {
      e.preventDefault();
      const err = document.getElementById("c-err");
      if (err) err.textContent = "";
      const f = Object.fromEntries(new FormData(cForm).entries());
      const name = (f.name || "").trim();
      const phone = digitsOnly(f.phone);
      if (!name) {
        if (err) err.textContent = "Ism majburiy";
        return;
      }
      if (!phone) {
        if (err) err.textContent = "Telefon majburiy";
        return;
      }
      if (!validPhone(phone)) {
        if (err) err.textContent = "Telefon faqat raqamlardan iborat bo‘lsin";
        return;
      }
      try {
        await api("/api/customers", { method: "POST", body: JSON.stringify({ ...f, name, phone }) });
        render();
      } catch (ex) {
        if (err) err.textContent = ex.message;
      }
    };
    document.getElementById("c-filter")?.addEventListener("input", (e) => {
      const q = e.target.value.trim().toLowerCase();
      document.querySelectorAll("#c-table tbody tr").forEach((tr) => {
        const name = tr.dataset.name || "";
        const phone = tr.dataset.phone || "";
        tr.hidden = Boolean(q) && !name.includes(q) && !phone.includes(q);
      });
    });
    document.querySelectorAll("[data-pay]").forEach((btn) => {
      btn.onclick = () => {
        if (btn.disabled) return;
        openDebtPayModal(Number(btn.dataset.pay), btn.dataset.name, Number(btn.dataset.max || 0));
      };
    });
    document.querySelectorAll("[data-chistory]").forEach((btn) => {
      btn.onclick = async () => {
        const d = await api("/api/customers/" + btn.dataset.chistory);
        const modal = document.getElementById("confirm-modal");
        modal.classList.remove("hidden");
        modal.innerHTML = `<div class="card confirm-box sale-box">
          <h3>${esc(d.name)}</h3>
          <p>Qarz: <b>${money(d.debt)}</b> · Limit: ${money(d.credit_limit)}</p>
          <table class="table">${(d.ledger || []).map((x) => `<tr><td>${esc(x.kind)}</td><td>${money(x.amount)}</td><td>${esc(x.note)}</td></tr>`).join("")}</table>
          <button class="btn btn-ghost" id="sale-close">Yopish</button>
        </div>`;
        document.getElementById("sale-close").onclick = () => modal.classList.add("hidden");
      };
    });
    document.querySelectorAll("[data-cedit]").forEach((btn) => {
      btn.onclick = async () => {
        const c = JSON.parse(btn.dataset.cedit);
        const name = prompt("Ism", c.name);
        if (!name) return;
        await api("/api/customers/" + c.id, { method: "PATCH", body: JSON.stringify({ name, phone: c.phone, credit_limit: c.credit_limit }) });
        render();
      };
    });
  }

  const stForm = document.getElementById("st-form");
  if (stForm) {
    bindPwToggle("st-password", "st-pw-toggle");
    stForm.onsubmit = async (e) => {
      e.preventDefault();
      const err = document.getElementById("st-err");
      if (err) err.textContent = "";
      const f = Object.fromEntries(new FormData(stForm).entries());
      const full_name = (f.full_name || "").trim();
      const username = (f.username || "").trim();
      const password = f.password || "";
      const role = f.role || "CASHIER";
      if (!full_name || !username || !role) {
        if (err) err.textContent = "Ism, login va rol majburiy";
        return;
      }
      if (!f.id && password.length < 4) {
        if (err) err.textContent = "Parol kamida 4 belgi bo‘lsin";
        return;
      }
      if (f.id && password && password.length < 4) {
        if (err) err.textContent = "Yangi parol kamida 4 belgi bo‘lsin";
        return;
      }
      try {
        if (f.id) {
          const payload = { full_name, username, role };
          if (password) payload.password = password;
          await api("/api/staff/" + f.id, { method: "PATCH", body: JSON.stringify(payload) });
        } else {
          await api("/api/staff", { method: "POST", body: JSON.stringify({ full_name, username, password, role }) });
        }
        stForm.reset();
        stForm.id.value = "";
        document.getElementById("st-save").textContent = "Qo‘shish";
        document.getElementById("st-password").placeholder = "Parol";
        render();
      } catch (ex) {
        if (err) err.textContent = ex.message;
      }
    };
    document.querySelectorAll("[data-st-edit]").forEach((btn) => {
      btn.onclick = () => {
        const u = JSON.parse(btn.dataset.stEdit);
        stForm.id.value = u.id;
        stForm.full_name.value = u.full_name;
        stForm.username.value = u.username;
        stForm.role.value = u.role === "OWNER" ? "ADMIN" : u.role;
        stForm.password.value = "";
        document.getElementById("st-password").placeholder = "Yangi parol (ixtiyoriy)";
        document.getElementById("st-save").textContent = "Saqlash";
        window.scrollTo({ top: 0, behavior: "smooth" });
      };
    });
    document.querySelectorAll("[data-st-toggle]").forEach((btn) => {
      btn.onclick = async () => {
        if (btn.dataset.active === "1") {
          const ok = await askConfirm({
            title: "O'chirishni tasdiqlang",
            text: `"${btn.dataset.name}" xodimini o‘chirasizmi? U tizimga kira olmaydi.`,
            okLabel: "O'chirish",
          });
          if (!ok) return;
        }
        await api("/api/staff/" + btn.dataset.stToggle + "/toggle", { method: "POST" });
        render();
      };
    });
  }

  document.getElementById("kiosk-copy")?.addEventListener("click", async () => {
    const r = await fetch("/assets/kiosk/create-shortcut.txt");
    const t = await r.text();
    await navigator.clipboard.writeText(t);
    const b = document.getElementById("kiosk-copy");
    if (b) { const old = b.textContent; b.textContent = "Nusxa olindi"; setTimeout(() => { b.textContent = old; }, 2000); }
  });

  const setForm = document.getElementById("set-form");
  if (setForm) {
    const inn = document.getElementById("set-inn");
    inn?.addEventListener("input", () => {
      inn.value = String(inn.value || "").replace(/\D/g, "").slice(0, 9);
    });
    setForm.onsubmit = async (e) => {
      e.preventDefault();
      const msg = document.getElementById("set-msg");
      if (msg) msg.innerHTML = "";
      const f = Object.fromEntries(new FormData(setForm).entries());
      f.inn = String(f.inn || "").replace(/\D/g, "").slice(0, 9);
      if (f.inn && !/^\d{1,9}$/.test(f.inn)) {
        if (msg) msg.innerHTML = '<p class="err">INN faqat raqam, ko‘pi bilan 9 belgi</p>';
        return;
      }
      try {
        const saved = await api("/api/settings", { method: "PATCH", body: JSON.stringify(f) });
        saveLocalSettings(saved);
        const me = await api("/api/auth/me");
        const cur = user();
        setAuth({ access: token(), user: { ...cur, company_name: me.company_name, store_name: me.store_name, currency: me.currency, locale: me.locale, vat_percent: me.vat_percent } });
        if (msg) msg.innerHTML = '<p class="ok">Saqlandi (server va localStorage)</p>';
      } catch (ex) {
        if (msg) msg.innerHTML = `<p class="err">${esc(ex.message)}</p>`;
      }
    };
    const billPlan = document.getElementById("bill-plan");
    if (billPlan) {
      billPlan.onchange = () => {
        const box = document.querySelector("#bill-requisites pre");
        const acc = document.getElementById("bill-requisites")?.dataset.accountId;
        if (box) box.textContent = billingRequisites(acc, billPlan.value);
      };
    }
  }

  const pwForm = document.getElementById("pw-form");
  if (pwForm) {
    pwForm.onsubmit = async (e) => {
      e.preventDefault();
      const msg = document.getElementById("pw-msg");
      if (msg) msg.innerHTML = "";
      const f = Object.fromEntries(new FormData(pwForm).entries());
      if (f.new_password !== f.new_password2) {
        if (msg) msg.innerHTML = '<p class="err">Parollar mos emas</p>';
        return;
      }
      try {
        await api("/api/auth/change-password", { method: "POST", body: JSON.stringify({ current_password: f.current_password, new_password: f.new_password }) });
        if (msg) msg.innerHTML = '<p class="ok">Saqlandi</p>';
        pwForm.reset();
      } catch (ex) {
        if (msg) msg.innerHTML = `<p class="err">${esc(ex.message)}</p>`;
      }
    };
  }

  bindSales();
  bindHisobotlar();

  if (page === "pos") {
    drawPos();
    const scan = document.getElementById("scan");
    scan?.focus();
    scan?.addEventListener("input", drawPos);
    document.getElementById("discount")?.addEventListener("input", () => {
      drawPos();
      updatePayHints();
    });
    ["cash", "card", "online", "credit", "customer"].forEach((id) => {
      document.getElementById(id)?.addEventListener("input", updatePayHints);
      document.getElementById(id)?.addEventListener("change", updatePayHints);
    });
    scan?.addEventListener("keydown", (e) => {
      if (e.key !== "Enter") return;
      e.preventDefault();
      const q = e.target.value.trim();
      const p = findScanProduct(q);
      if (p) {
        addCart(p.id);
        e.target.value = "";
        drawPos();
        e.target.focus();
      }
    });
    document.getElementById("plist")?.addEventListener("click", (e) => {
      const add = e.target.closest("[data-add]");
      if (add) {
        addCart(Number(add.dataset.add));
        if (scan) {
          scan.value = "";
          scan.focus();
        }
        drawPos();
      }
    });
    document.getElementById("cart")?.addEventListener("click", (e) => {
      const plus = e.target.closest("[data-plus]");
      const minus = e.target.closest("[data-minus]");
      const del = e.target.closest("[data-del]");
      if (plus) {
        const i = Number(plus.dataset.plus);
        const line = window.__pos.cart[i];
        const p = window.__pos.products.find((x) => x.id === line.product_id);
        if (p && line.qty + 1 > Number(p.stock || 0) + 1e-9) {
          const msg = document.getElementById("pos-msg");
          if (msg) msg.innerHTML = `<p class="err">Qoldiq yetarli emas (${p.stock})</p>`;
        } else {
          line.qty += 1;
          window.__pos.idem = null;
        }
      }
      if (minus) {
        const i = Number(minus.dataset.minus);
        window.__pos.cart[i].qty -= 1;
        if (window.__pos.cart[i].qty <= 0) window.__pos.cart.splice(i, 1);
        window.__pos.idem = null;
      }
      if (del) {
        window.__pos.cart.splice(Number(del.dataset.del), 1);
        window.__pos.idem = null;
      }
      drawPos();
    });
    document.getElementById("pay")?.addEventListener("click", payNow);
    if (window.__posKeys) window.removeEventListener("keydown", window.__posKeys);
    window.__posKeys = (e) => {
      if (!document.getElementById("pay")) return;
      if (e.key === "F2") {
        e.preventDefault();
        payNow();
      } else if (e.key === "F4") {
        e.preventDefault();
        document.getElementById("cash")?.focus();
      } else if (e.key === "Escape") {
        const s = document.getElementById("scan");
        if (s) {
          s.value = "";
          drawPos();
          s.focus();
        }
      }
    };
    window.addEventListener("keydown", window.__posKeys);
    document.getElementById("shift-open")?.addEventListener("click", async () => {
      await api("/api/shifts/open", { method: "POST", body: JSON.stringify({ opening_cash: Number(document.getElementById("shift-open-cash")?.value || 0) }) });
      render();
    });
    document.getElementById("shift-close")?.addEventListener("click", async () => {
      await api("/api/shifts/close", { method: "POST", body: JSON.stringify({ closing_cash: 0 }) });
      render();
    });
  }
}

function addCart(id) {
  const p = window.__pos.products.find((x) => x.id === id);
  if (!p) return;
  const line = window.__pos.cart.find((x) => x.product_id === id);
  const next = (line ? line.qty : 0) + 1;
  if (next > Number(p.stock || 0) + 1e-9) {
    const msg = document.getElementById("pos-msg");
    if (msg) msg.innerHTML = `<p class="err">Qoldiq yetarli emas (${p.stock})</p>`;
    return;
  }
  if (line) line.qty += 1;
  else window.__pos.cart.push({ product_id: id, name: p.name, qty: 1, price: p.sell_price });
  if (window.__pos) window.__pos.idem = null;
  drawPos();
}

async function payNow() {
  const msg = document.getElementById("pos-msg");
  const payBtn = document.getElementById("pay");
  if (window.__pos?.paying) return;
  if (window.__pos) window.__pos.paying = true;
  if (payBtn) payBtn.disabled = true;
  try {
    if (!window.__pos.cart.length) throw new Error("Savat bo‘sh");
    const { total } = posTotals();
    const discount = Math.max(0, Number(document.getElementById("discount").value || 0));
    let cash = Number(document.getElementById("cash").value || 0);
    const card = Number(document.getElementById("card").value || 0);
    const online = Number(document.getElementById("online").value || 0);
    if (cash < 0 || card < 0 || online < 0) throw new Error("To‘lov manfiy bo‘lmasin");
    const customerId = Number(document.getElementById("customer").value || 0) || null;
    const allowCredit = document.getElementById("credit").checked;
    if (allowCredit && !customerId) throw new Error("Qarzga savdo uchun mijoz tanlang");
    if (!cash && !card && !online && !allowCredit) cash = total;
    const type = online && (cash || card) ? "MIXED" : online ? "ONLINE" : card && cash ? "MIXED" : card ? "CARD" : allowCredit && cash + card + online < total ? "CREDIT" : "CASH";
    if (!window.__pos.idem) window.__pos.idem = "pos-" + Date.now() + "-" + Math.random().toString(16).slice(2);
    const sale = await api("/api/pos/sale", {
      method: "POST",
      body: JSON.stringify({
        items: window.__pos.cart.map((i) => ({ product_id: i.product_id, qty: i.qty, price: i.price })),
        discount,
        paid_cash: cash,
        paid_card: card,
        paid_online: online,
        payment_type: type,
        customer_id: customerId,
        allow_credit: allowCredit,
        idempotency_key: window.__pos.idem,
      }),
    });
    msg.innerHTML = `<p class="ok">${esc(sale.number)} · ${money(sale.total)}</p>`;
    showReceipt(sale);
    window.__pos.cart = [];
    window.__pos.idem = null;
    document.getElementById("cash").value = "";
    document.getElementById("card").value = "";
    document.getElementById("online").value = "";
    document.getElementById("discount").value = "";
    document.getElementById("credit").checked = false;
    window.__pos.products = await api("/api/pos/products");
    if (can("customers")) window.__pos.customers = await api("/api/customers");
    drawPos();
  } catch (e) {
    msg.innerHTML = `<p class="err">${esc(e.message)}</p>`;
  } finally {
    if (window.__pos) window.__pos.paying = false;
    if (payBtn) payBtn.disabled = false;
  }
}

async function render() {
  const view = nav();
  if (view === "home") {
    root.innerHTML = landing();
    return;
  }
  if (view === "login" || view === "register") {
    root.innerHTML = authForm(view);
    document.getElementById("auth-form").onsubmit = async (e) => {
      e.preventDefault();
      const f = Object.fromEntries(new FormData(e.target).entries());
      const err = document.getElementById("auth-err");
      try {
        const data = await api(view === "login" ? "/api/auth/login" : "/api/auth/register", {
          method: "POST",
          body: JSON.stringify(f),
        });
        setAuth(data);
        location.hash = (data.user.permissions || []).includes("reports") ? "#/app/dashboard" : "#/app/pos";
      } catch (ex) {
        err.textContent = ex.message;
      }
    };
    return;
  }
  if (view === "platform") {
    root.innerHTML = await pagePlatform(api);
    bindSaas("platform", api, setAuth, render);
    return;
  }
  await renderApp();
}

const _render = render;
async function renderAndAi() {
  await _render();
  try { applyTheme(); bindThemeToggle(); } catch (e) { /* theme must not break POS */ }
  try { syncFinexAi(); } catch (e) { /* AI widget must not break POS */ }
}
window.addEventListener("hashchange", renderAndAi);
renderAndAi();

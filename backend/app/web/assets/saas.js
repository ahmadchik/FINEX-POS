import { bindPlatform } from "./platform.js?v=theme2";
export { pagePlatform, applyPlatformTheme } from "./platform.js?v=theme2";
export { applyTheme, bindThemeToggle, themeToggleHtml } from "./theme.js?v=theme2";
export function lang() {
  return localStorage.getItem("finup_lang") || (JSON.parse(localStorage.getItem("finup_pos_user") || "null") || {}).locale || "uz";
}

export function setLang(v) {
  localStorage.setItem("finup_lang", v);
}

const I18N = {
  uz: {
    dashboard: "Dashboard",
    reports: "Hisobotlar",
    pos: "POS savdo",
    products: "Tovarlar",
    stock: "Kirim",
    sales: "Cheklar",
    customers: "Mijozlar",
    cash: "Kassa",
    expenses: "Xarajatlar",
    staff: "Xodimlar",
    settings: "Sozlamalar",
    stores: "Do‘konlar",
    suppliers: "Yetkazuvchilar",
    transfers: "Transfer",
    logout: "Chiqish",
    shiftOpen: "Smena ochish",
    shiftClose: "Smena yopish",
  },
  ru: {
    dashboard: "Дашборд",
    reports: "Отчёты",
    pos: "POS продажа",
    products: "Товары",
    stock: "Приход",
    sales: "Чеки",
    customers: "Клиенты",
    cash: "Касса",
    expenses: "Расходы",
    staff: "Сотрудники",
    settings: "Настройки",
    stores: "Магазины",
    suppliers: "Поставщики",
    transfers: "Трансфер",
    logout: "Выход",
    shiftOpen: "Открыть смену",
    shiftClose: "Закрыть смену",
  },
  en: {
    dashboard: "Dashboard",
    reports: "Reports",
    pos: "POS",
    products: "Products",
    stock: "Stock in",
    sales: "Receipts",
    customers: "Customers",
    cash: "Cash",
    expenses: "Expenses",
    staff: "Staff",
    settings: "Settings",
    stores: "Stores",
    suppliers: "Suppliers",
    transfers: "Transfers",
    logout: "Log out",
    shiftOpen: "Open shift",
    shiftClose: "Close shift",
  },
};

export function t(key) {
  const pack = I18N[lang()] || I18N.uz;
  return pack[key] || I18N.uz[key] || key;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

export async function pageStores(api, money) {
  const rows = await api("/api/stores");
  return `
    <h2>${t("stores")}</h2>
    <form id="store-form" class="card" style="margin-bottom:12px">
      <input type="hidden" name="id" value="" />
      <div class="grid3" style="margin-top:0">
        <input class="field" name="name" placeholder="Do‘kon nomi" required />
        <input class="field" name="phone" placeholder="Telefon" />
        <input class="field" name="address" placeholder="Manzil" />
        <input class="field" name="username" placeholder="Do'kon login" />
        <input class="field" name="password" type="password" placeholder="Parol (yangi yoki o'zgartirish)" />
        <button class="btn btn-gold" type="submit" id="store-submit">Qo‘shish</button>
        <button class="btn btn-ghost" type="button" id="store-cancel" hidden>Bekor</button>
      </div>
      <div class="err" id="store-err" style="margin-top:8px"></div>
    </form>
    <table class="table">
      <thead><tr><th>Nomi</th><th>Login</th><th>Telefon</th><th>Manzil</th><th></th></tr></thead>
      <tbody>
        ${rows.map((s) => `<tr class="${s.is_active ? "" : "badge-off"}">
          <td>${esc(s.name)}${s.current ? " · <b>joriy</b>" : ""}</td>
          <td>${esc(s.username || "")}</td>
          <td>${esc(s.phone)}</td>
          <td>${esc(s.address)}</td>
          <td>
            <button class="btn btn-ghost btn-sm" data-edit="${s.id}" data-name="${esc(s.name)}" data-username="${esc(s.username || "")}" data-phone="${esc(s.phone)}" data-address="${esc(s.address)}">Tahrirlash</button>
            ${s.current ? "" : `<button class="btn btn-ghost btn-sm" data-switch="${s.id}">Kirish</button>`}
            <button class="btn btn-ghost btn-sm" data-stoggle="${s.id}">${s.is_active ? "O‘chirish" : "Yoqish"}</button>
          </td>
        </tr>`).join("")}
      </tbody>
    </table>`;
}

export async function pageSuppliers(api) {
  const rows = await api("/api/suppliers");
  return `
    <h2>${t("suppliers")}</h2>
    <form id="sup-form" class="card" style="margin-bottom:12px">
      <div class="grid3" style="margin-top:0">
        <input class="field" name="name" placeholder="Nomi" required />
        <input class="field" name="phone" placeholder="Telefon" />
        <input class="field" name="note" placeholder="Izoh" />
        <button class="btn btn-gold" type="submit">Qo‘shish</button>
      </div>
    </form>
    <table class="table">
      <thead><tr><th>Nomi</th><th>Telefon</th><th>Izoh</th></tr></thead>
      <tbody>${rows.map((s) => `<tr><td>${esc(s.name)}</td><td>${esc(s.phone)}</td><td>${esc(s.note)}</td></tr>`).join("")}</tbody>
    </table>`;
}

export async function pageTransfers(api) {
  let u = null;
  try { u = JSON.parse(localStorage.getItem("finup_pos_user") || "null"); } catch (e) { u = null; }
  const isCompany = !!(u && (u.cabinet === "company" || u.role === "OWNER" || u.role === "ADMIN"));
  const fetches = isCompany
    ? [api("/api/transfers")]
    : [api("/api/stores"), api("/api/products"), api("/api/transfers")];
  const results = await Promise.all(fetches);
  const stores = isCompany ? [] : results[0];
  const products = isCompany ? [] : results[1];
  const rows = isCompany ? results[0] : results[2];
  window.__tr = { stores, products };
  const formHtml = isCompany ? "" : `
    <form id="tr-form" class="card" style="margin-bottom:12px">
      <div class="grid3" style="margin-top:0">
        <select class="field" name="from_store_id">${stores.map((s) => `<option value="${s.id}">Dan: ${esc(s.name)}</option>`).join("")}</select>
        <select class="field" name="to_store_id">${stores.map((s) => `<option value="${s.id}">Ga: ${esc(s.name)}</option>`).join("")}</select>
        <select class="field" name="product_id">${products.map((p) => `<option value="${p.id}">${esc(p.name)} (${p.stock})</option>`).join("")}</select>
        <input class="field" name="qty" type="number" step="0.001" placeholder="Miqdor" required />
        <button class="btn btn-gold" type="submit">O‘tkazish</button>
      </div>
      <div class="err" id="tr-err" style="margin-top:8px"></div>
    </form>`;
  return `
    <h2>${t("transfers")}</h2>
    ${formHtml}
    <table class="table">
      <thead><tr><th>Raqam</th><th>Dan</th><th>Ga</th><th>Sana</th></tr></thead>
      <tbody>${rows.map((r) => `<tr><td>${esc(r.number)}</td><td>${esc(r.from_store)}</td><td>${esc(r.to_store)}</td><td>${esc((r.created_at || "").slice(0, 16))}</td></tr>`).join("")}</tbody>
    </table>`;
}

export function bindSaas(page, api, setAuth, render) {
  const storeForm = document.getElementById("store-form");
  if (storeForm) {
    const submitBtn = document.getElementById("store-submit");
    const cancelBtn = document.getElementById("store-cancel");
    const resetStoreForm = () => {
      storeForm.reset();
      storeForm.elements.id.value = "";
      if (submitBtn) submitBtn.textContent = "Qo‘shish";
      if (cancelBtn) cancelBtn.hidden = true;
    };
    cancelBtn?.addEventListener("click", resetStoreForm);
    storeForm.onsubmit = async (e) => {
      e.preventDefault();
      const f = Object.fromEntries(new FormData(storeForm).entries());
      const payload = { name: f.name, phone: f.phone || "", address: f.address || "", username: (f.username || "").trim(), password: f.password || "" };
      const id = Number(f.id || 0);
      try {
        if (id) {
          await api("/api/stores/" + id, { method: "PATCH", body: JSON.stringify(payload) });
        } else {
          await api("/api/stores", { method: "POST", body: JSON.stringify(payload) });
        }
        render();
      } catch (ex) {
        document.getElementById("store-err").textContent = ex.message;
      }
    };
    document.querySelectorAll("[data-edit]").forEach((b) => {
      b.onclick = () => {
        storeForm.elements.id.value = b.dataset.edit || "";
        storeForm.elements.name.value = b.dataset.name || "";
        storeForm.elements.username.value = b.dataset.username || "";
        storeForm.elements.password.value = "";
        storeForm.elements.phone.value = b.dataset.phone || "";
        storeForm.elements.address.value = b.dataset.address || "";
        if (submitBtn) submitBtn.textContent = "Saqlash";
        if (cancelBtn) cancelBtn.hidden = false;
        storeForm.elements.name.focus();
      };
    });
    document.querySelectorAll("[data-switch]").forEach((b) => {
      b.onclick = async () => {
        const data = await api("/api/auth/switch-store", { method: "POST", body: JSON.stringify({ store_id: Number(b.dataset.switch) }) });
        setAuth(data);
        render();
      };
    });
    document.querySelectorAll("[data-stoggle]").forEach((b) => {
      b.onclick = async () => {
        await api("/api/stores/" + b.dataset.stoggle + "/toggle", { method: "POST" });
        render();
      };
    });
  }

  const sup = document.getElementById("sup-form");
  if (sup) {
    sup.onsubmit = async (e) => {
      e.preventDefault();
      const f = Object.fromEntries(new FormData(sup).entries());
      await api("/api/suppliers", { method: "POST", body: JSON.stringify(f) });
      render();
    };
  }

  const tr = document.getElementById("tr-form");
  if (tr) {
    tr.onsubmit = async (e) => {
      e.preventDefault();
      const f = Object.fromEntries(new FormData(tr).entries());
      try {
        await api("/api/transfers", {
          method: "POST",
          body: JSON.stringify({
            from_store_id: Number(f.from_store_id),
            to_store_id: Number(f.to_store_id),
            items: [{ product_id: Number(f.product_id), qty: Number(f.qty) }],
          }),
        });
        render();
      } catch (ex) {
        document.getElementById("tr-err").textContent = ex.message;
      }
    };
  }

  bindPlatform(page, api, setAuth, render);
}

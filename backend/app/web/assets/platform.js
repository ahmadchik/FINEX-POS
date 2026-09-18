import { applyTheme, bindThemeToggle, themeToggleHtml } from "./theme.js?v=theme2";
export { applyTheme as applyPlatformTheme };

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function platToken() {
  return localStorage.getItem("finup_platform_token") || "";
}

function companyIdFromHash() {
  const m = (location.hash || "").match(/^#\/platform\/(\d+)/);
  return m ? Number(m[1]) : 0;
}

function platQuery() {
  const q = (location.hash.split("?")[1] || "").replace(/^#/, "");
  return Object.fromEntries(new URLSearchParams(q));
}

function moneyUzs(n) {
  return Number(n || 0).toLocaleString("uz-UZ") + " so'm";
}

function when(iso) {
  return iso ? String(iso).replace("T", " ").slice(0, 16) : "—";
}

async function platFetch(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      Authorization: "Bearer " + platToken(),
      ...(opts.headers || {}),
    },
  });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401) {
    localStorage.removeItem("finup_platform_token");
    throw new Error("Sessiya tugadi");
  }
  if (!res.ok) {
    const d = data.detail;
    throw new Error(typeof d === "string" ? d : data.message || "Xatolik");
  }
  return data;
}

function stPill(status) {
  const s = status || "";
  return `<span class="plat-st plat-st-${esc(s)}">${esc(s)}</span>`;
}

function loginHtml() {
  return `
    <div class="auth card plat-login">
      <div class="kicker brand-kicker"><img class="brand-mark" src="/assets/brand/finex-mark.png" alt="" />FINEX POS</div>
      <h2>Platform egasi</h2>
      <p class="muted">Bu do'kon kasir/owner logini emas. Loyiha egasi kabineti.</p>
      <form id="plat-login">
        <input class="field" name="username" value="platform" autocomplete="username" style="margin-bottom:8px" />
        <input class="field" name="password" type="password" placeholder="Parol: platform123" autocomplete="current-password" style="margin-bottom:8px" />
        <div class="row" style="margin:0 0 10px;gap:8px">${themeToggleHtml()}</div>
        <button class="btn btn-gold" type="submit">Kirish</button>
        <p class="muted" style="margin-top:10px">Standart: <b>platform</b> / <b>platform123</b></p>
        <p class="err" id="plat-err"></p>
      </form>
      <p class="muted">Do'kon kabineti: <a href="#/login">#/login</a></p>
    </div>`;
}

function platShell(inner) {
  return `
    <div class="plat">
      <div class="plat-top">
        <div class="kicker brand-kicker"><img class="brand-mark" src="/assets/brand/finex-mark.png" alt="" />Platform</div>
        <div class="row" style="margin:0;gap:8px;align-items:center">
          ${themeToggleHtml()}
          <a class="muted" href="#/">Sayt</a>
          <button type="button" class="btn btn-ghost btn-sm" id="plat-out">Chiqish</button>
        </div>
      </div>
      ${inner}
    </div>`;
}

async function listHtml() {
  const q = platQuery();
  const params = new URLSearchParams();
  if (q.q) params.set("q", q.q);
  if (q.status) params.set("status", q.status);
  if (q.plan) params.set("plan", q.plan);
  params.set("limit", "80");
  const [ov, list] = await Promise.all([
    platFetch("/api/platform/overview"),
    platFetch("/api/platform/companies?" + params.toString()),
  ]);
  const items = list.items || [];
  const kpis = [
    ["Kompaniya", ov.companies],
    ["Trial", ov.trial],
    ["Active", ov.active],
    ["Past due", ov.past_due],
    ["Stop", ov.suspended],
    ["7 kunda trial", ov.trial_ending_7d],
    ["MRR", moneyUzs(ov.mrr)],
    ["User / do'kon", (ov.users || 0) + " / " + (ov.stores || 0)],
  ];
  return platShell(`
    <div class="plat-kpis">
      ${kpis
        .map(
          ([l, v]) => `<div class="plat-kpi"><span class="muted">${esc(l)}</span><b>${esc(v)}</b></div>`,
        )
        .join("")}
    </div>
    <form id="plat-filter" class="plat-toolbar">
      <input class="field" name="q" placeholder="Qidiruv: nom, ID, hisob, telefon" value="${esc(q.q || "")}" style="flex:1;min-width:180px" />
      <select class="field" name="status" style="width:150px">
        ${["", "TRIAL", "ACTIVE", "PAST_DUE", "SUSPENDED"]
          .map((s) => `<option value="${s}" ${q.status === s ? "selected" : ""}>${s || "Holat"}</option>`)
          .join("")}
      </select>
      <select class="field" name="plan" style="width:150px">
        ${["", "FREE", "PRO", "ENTERPRISE", "VIP"]
          .map((s) => `<option value="${s}" ${q.plan === s ? "selected" : ""}>${s || "Tarif"}</option>`)
          .join("")}
      </select>
      <button class="btn btn-gold" type="submit">Filter</button>
      <button class="btn btn-ghost" type="button" id="plat-new-toggle">+ Tenant</button>
    </form>
    <form id="plat-new" class="card" style="display:none;margin-bottom:14px">
      <h3 style="margin-top:0">Yangi tenant</h3>
      <div class="grid3" style="margin-top:0">
        <input class="field" name="name" placeholder="Kompaniya nomi" required />
        <input class="field" name="full_name" placeholder="Owner ismi" required />
        <input class="field" name="username" placeholder="Login" required />
        <input class="field" name="password" placeholder="Parol (bo'sh = avto)" />
        <select class="field" name="plan">
          <option>FREE</option><option>PRO</option><option>ENTERPRISE</option><option>VIP</option>
        </select>
        <button class="btn btn-gold" type="submit">Yaratish</button>
      </div>
      <p class="err" id="plat-new-err"></p>
    </form>
    <p class="muted">${list.total || 0} ta kompaniya</p>
    <table class="table">
      <thead><tr><th>ID</th><th>Kompaniya</th><th>Owner</th><th>Tarif</th><th>Holat</th><th>Hisob</th><th>Do'kon</th><th>User</th><th>Muddati</th></tr></thead>
      <tbody>
        ${
          items.length
            ? items
                .map(
                  (c) => `<tr class="clickable" data-open="${c.id}">
          <td>${c.id}</td>
          <td><b>${esc(c.name)}</b></td>
          <td>${esc(c.owner_username || "—")}</td>
          <td>${esc(c.plan)}</td>
          <td>${stPill(c.status)}</td>
          <td>${esc(c.account_no || "")}</td>
          <td>${c.stores}</td>
          <td>${c.users}</td>
          <td>${esc(when(c.paid_until || c.trial_ends_at))}</td>
        </tr>`,
                )
                .join("")
            : `<tr><td colspan="9" class="muted">Hech narsa topilmadi</td></tr>`
        }
      </tbody>
    </table>
    <h3>So'nggi audit</h3>
    <table class="table">
      <thead><tr><th>Vaqt</th><th>Amal</th><th>Company</th><th>Entity</th></tr></thead>
      <tbody>
        ${(ov.audit || [])
          .map(
            (a) => `<tr>
          <td>${esc(when(a.created_at))}</td>
          <td>${esc(a.action)}</td>
          <td>${a.company_id ? `<a href="#/platform/${a.company_id}">#${a.company_id}</a>` : "—"}</td>
          <td>${esc(a.entity)} ${a.entity_id || ""}</td>
        </tr>`,
          )
          .join("")}
      </tbody>
    </table>
  `);
}

async function detailHtml(id) {
  const c = await platFetch("/api/platform/companies/" + id);
  const owner = c.owner || {};
  return platShell(`
    <p class="muted"><a href="#/platform">← Tenantlar</a></p>
    <div class="plat-detail-head">
      <div>
        <h2 style="margin:0">${esc(c.name)} ${stPill(c.status)}</h2>
        <p class="muted">Hisob ${esc(c.account_no || "—")} · ${esc(c.plan)} · yaratilgan ${esc(when(c.created_at))}</p>
      </div>
      <div class="row" style="margin:0;gap:8px">
        <button class="btn btn-gold btn-sm" data-imp="${c.id}">Impersonate</button>
        <button class="btn btn-ghost btn-sm" data-pext="${c.id}">+30 kun</button>
        ${
          c.status === "SUSPENDED"
            ? `<button class="btn btn-ghost btn-sm" data-punsusp="${c.id}">Unsuspend</button>`
            : `<button class="btn btn-danger btn-sm" data-psusp="${c.id}">Stop</button>`
        }
      </div>
    </div>
    <div class="plat-kpis">
      <div class="plat-kpi"><span class="muted">Owner</span><b>${esc(owner.full_name || "—")}</b><span class="muted">${esc(owner.username || "")}</span></div>
      <div class="plat-kpi"><span class="muted">Trial</span><b>${esc(when(c.trial_ends_at))}</b></div>
      <div class="plat-kpi"><span class="muted">Paid until</span><b>${esc(when(c.paid_until))}</b></div>
      <div class="plat-kpi"><span class="muted">Limit</span><b>${c.stores}/${c.limits?.stores} do'kon · ${c.users}/${c.limits?.users} user</b></div>
    </div>
    <div class="grid3" style="margin-top:8px">
      <form id="plat-plan" class="card">
        <h3 style="margin-top:0">Tarif</h3>
        <select class="field" name="plan">
          ${["FREE", "PRO", "ENTERPRISE", "VIP"]
            .map((p) => `<option ${c.plan === p ? "selected" : ""}>${p}</option>`)
            .join("")}
        </select>
        <button class="btn btn-gold" type="submit" style="margin-top:10px">Saqlash</button>
      </form>
      <form id="plat-notes" class="card">
        <h3 style="margin-top:0">Ichki izoh</h3>
        <textarea class="field" name="notes" rows="4" placeholder="Support / risk / partner">${esc(c.notes || "")}</textarea>
        <button class="btn btn-ghost" type="submit" style="margin-top:10px">Izohni saqlash</button>
      </form>
      <form id="plat-reset" class="card">
        <h3 style="margin-top:0">Owner parol</h3>
        <p class="muted">Yangi parol avtomatik yaratiladi va bir marta ko'rinadi.</p>
        <button class="btn btn-ghost" type="submit">Reset parol</button>
        <p class="ok" id="plat-reset-out" style="margin-top:8px"></p>
        <p class="err" id="plat-reset-err"></p>
      </form>
    </div>
    <p class="err" id="plat-err"></p>
    <h3>Xodimlar</h3>
    <table class="table">
      <thead><tr><th>Ism</th><th>Login</th><th>Rol</th><th>Holat</th></tr></thead>
      <tbody>${(c.staff || [])
        .map(
          (u) => `<tr class="${u.is_active ? "" : "badge-off"}"><td>${esc(u.full_name)}</td><td>${esc(u.username)}</td><td>${esc(u.role)}</td><td>${u.is_active ? "Faol" : "O'chiq"}</td></tr>`,
        )
        .join("")}</tbody>
    </table>
    <h3>Do'konlar</h3>
    <table class="table">
      <thead><tr><th>Nomi</th><th>Telefon</th><th>Manzil</th></tr></thead>
      <tbody>${(c.store_rows || [])
        .map((s) => `<tr class="${s.is_active ? "" : "badge-off"}"><td>${esc(s.name)}</td><td>${esc(s.phone)}</td><td>${esc(s.address)}</td></tr>`)
        .join("")}</tbody>
    </table>
    <h3>To'lovlar</h3>
    <table class="table">
      <thead><tr><th>#</th><th>Sana</th><th>Tarif</th><th>Summa</th><th>Usul</th><th>Holat</th></tr></thead>
      <tbody>${
        (c.payments || []).length
          ? (c.payments || [])
              .map(
                (p) => `<tr><td>${p.id}</td><td>${esc(when(p.paid_at || p.created_at))}</td><td>${esc(p.plan)}</td><td>${moneyUzs(p.amount)}</td><td>${esc(p.method)}</td><td>${esc(p.status)}</td></tr>`,
              )
              .join("")
          : `<tr><td colspan="6" class="muted">To'lov yo'q</td></tr>`
      }</tbody>
    </table>
    <h3>Audit</h3>
    <table class="table">
      <thead><tr><th>Vaqt</th><th>Amal</th><th>Entity</th></tr></thead>
      <tbody>${(c.audit || [])
        .map((a) => `<tr><td>${esc(when(a.created_at))}</td><td>${esc(a.action)}</td><td>${esc(a.entity)} ${a.entity_id || ""}</td></tr>`)
        .join("")}</tbody>
    </table>
  `);
}

export async function pagePlatform() {
  if (!platToken()) return loginHtml();
  try {
    const cid = companyIdFromHash();
    if (cid) return await detailHtml(cid);
    return await listHtml();
  } catch (e) {
    if (String(e.message).includes("Sessiya")) {
      localStorage.removeItem("finup_platform_token");
      return loginHtml();
    }
    return platShell(`<p class="err">${esc(e.message)}</p><p><a href="#/platform">Ro'yxat</a></p>`);
  }
}

function flashErr(msg) {
  const el = document.getElementById("plat-err");
  if (el) el.textContent = msg || "";
}

export function bindPlatform(_page, api, setAuth, render) {
  bindThemeToggle();
  const plat = document.getElementById("plat-login");
  if (plat) {
    plat.onsubmit = async (e) => {
      e.preventDefault();
      const f = Object.fromEntries(new FormData(plat).entries());
      try {
        const res = await fetch("/api/platform/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(f),
        });
        const data = await res.json().catch(() => ({}));
        const detail = typeof data.detail === "string" ? data.detail : Array.isArray(data.detail) ? (data.detail[0]?.msg || "Xato") : "";
        if (!res.ok || !data.access) throw new Error(detail || "Login yoki parol noto'g'ri");
        localStorage.setItem("finup_platform_token", data.access);
        location.hash = "#/platform";
        render();
      } catch (ex) {
        document.getElementById("plat-err").textContent = ex.message;
      }
    };
    return;
  }

  document.getElementById("plat-out")?.addEventListener("click", () => {
    localStorage.removeItem("finup_platform_token");
    location.hash = "#/platform";
    render();
  });

  document.getElementById("plat-filter")?.addEventListener("submit", (e) => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.target).entries());
    const p = new URLSearchParams();
    if (f.q) p.set("q", f.q);
    if (f.status) p.set("status", f.status);
    if (f.plan) p.set("plan", f.plan);
    const qs = p.toString();
    location.hash = "#/platform" + (qs ? "?" + qs : "");
    render();
  });

  document.getElementById("plat-new-toggle")?.addEventListener("click", () => {
    const box = document.getElementById("plat-new");
    if (box) box.style.display = box.style.display === "none" ? "block" : "none";
  });

  document.getElementById("plat-new")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const err = document.getElementById("plat-new-err");
    const f = Object.fromEntries(new FormData(e.target).entries());
    try {
      const created = await platFetch("/api/platform/companies", { method: "POST", body: JSON.stringify(f) });
      if (created.password) alert("Login: " + created.username + "\nParol: " + created.password);
      location.hash = "#/platform/" + created.id;
      render();
    } catch (ex) {
      if (err) err.textContent = ex.message;
    }
  });

  document.querySelectorAll("[data-open]").forEach((tr) => {
    tr.onclick = () => {
      location.hash = "#/platform/" + tr.dataset.open;
    };
  });

  const patch = async (id, body, confirmMsg) => {
    if (confirmMsg && !confirm(confirmMsg)) return;
    try {
      await platFetch("/api/platform/companies/" + id, { method: "PATCH", body: JSON.stringify(body) });
      render();
    } catch (ex) {
      flashErr(ex.message);
    }
  };

  document.querySelectorAll("[data-pext]").forEach((b) => {
    b.onclick = (e) => {
      e.stopPropagation();
      patch(b.dataset.pext, { extend_days: 30 }, "30 kun qo'shilsinmi?");
    };
  });
  document.querySelectorAll("[data-psusp]").forEach((b) => {
    b.onclick = (e) => {
      e.stopPropagation();
      patch(b.dataset.psusp, { status: "SUSPENDED" }, "Kompaniya to'xtatilsinmi? Savdo yopiladi.");
    };
  });
  document.querySelectorAll("[data-punsusp]").forEach((b) => {
    b.onclick = (e) => {
      e.stopPropagation();
      patch(b.dataset.punsusp, { status: "UNSUSPEND" }, "Qayta yoqilsinmi?");
    };
  });

  document.querySelectorAll("[data-imp]").forEach((b) => {
    b.onclick = async (e) => {
      e.stopPropagation();
      if (!confirm("Owner kabinetiga kirilsinmi? (impersonate)")) return;
      try {
        const data = await platFetch("/api/platform/companies/" + b.dataset.imp + "/impersonate", { method: "POST" });
        localStorage.setItem("finup_impersonating", "1");
        setAuth(data);
        location.hash = "#/app/dashboard";
        render();
      } catch (ex) {
        flashErr(ex.message);
      }
    };
  });

  document.getElementById("plat-plan")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const id = companyIdFromHash();
    const f = Object.fromEntries(new FormData(e.target).entries());
    await patch(id, { plan: f.plan }, f.plan + " tarifiga o'tilsinmi?");
  });

  document.getElementById("plat-notes")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const id = companyIdFromHash();
    const f = Object.fromEntries(new FormData(e.target).entries());
    await patch(id, { notes: f.notes });
  });

  document.getElementById("plat-reset")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const id = companyIdFromHash();
    if (!confirm("Owner paroli yangilansinmi?")) return;
    const out = document.getElementById("plat-reset-out");
    const err = document.getElementById("plat-reset-err");
    try {
      const fd = new FormData(e.target);
      const password = String(fd.get("password") || "");
      const data = await platFetch("/api/platform/companies/" + id + "/reset-password", {
        method: "POST",
        body: JSON.stringify({ password }),
      });
      if (out) out.textContent = "Login: " + data.username + " — parol yangilandi";
      if (err) err.textContent = "";
    } catch (ex) {
      if (err) err.textContent = ex.message;
    }
  });
}

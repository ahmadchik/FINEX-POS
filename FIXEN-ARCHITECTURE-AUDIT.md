# FIXEN POS Architecture Audit

## Phase 2 Step 6D follow-up (2026-09-19)

Stock opname **finalize**: `POST /api/stock-opnames/{id}/finalize`. Atomic OPEN→POSTED via existing `move_stock(kind=ADJUST, ref_type=opname)`. Live stock + snapshot difference. Full rollback on any line failure. UI «Санашни якунлаш». Tests: `backend/tests/test_phase2_opname_finalize.py`. Do not start cancel.

## Phase 2 Step 6C follow-up (2026-09-19)

Stock opname **UI**: `#/app/opname` Sanash list/create/detail. Reuses 6B API. Snapshot displayed, difference preview only. No finalize/cancel, no `move_stock`. Do not start Step 6D.

## Phase 2 Step 6B follow-up (2026-09-19)

Stock opname **OPEN API**: create/list/detail + line add/patch/delete. HQ write forbidden (`forbid_company_kirim_write`). Snapshot `system_qty` at line-add. No finalize, no cancel, no UI, no `move_stock`. Tests: `backend/tests/test_phase2_opname_api.py`. 141 passed / 0 failed. Do not start Step 6C.

## Phase 2 Step 6A follow-up (2026-09-19)

Stock opname **database foundation only**: `stock_opnames` + `stock_opname_lines`. Partial unique one OPEN per store; unique product per opname. `ensure_schema` additive. No API, no UI, no finalize, no `move_stock` change. Tests: `backend/tests/test_phase2_opname_schema.py`. 133 passed / 0 failed. Do not start Step 6B.

## Phase 2 Step 5 follow-up (2026-09-18)

Transfer harden: `qty > 0`, atomic TRANSFER_OUT+IN via `move_stock`, source stock check, dest match by non-empty barcode/SKU, `GET /api/transfers/{id}`, `GET /api/transfer-stores`, audit payload. Kirim qty > 0. STORE `GET /api/stores` still 403. Status stays `DONE`. Tests: `backend/tests/test_phase2_transfers.py`.

## Phase 2 Step 4 follow-up (2026-09-18)

Dedicated stock adjustment: `POST /api/stock-adjustments` (difference-based `qty`) through existing `move_stock(kind=ADJUST)`. Product PATCH ignores `stock`. Audit `stock.adjust`. No second ledger. Idempotency not added (sale keys only). Tests: `backend/tests/test_phase2_stock_adjust.py`.

## Phase 2 Step 3 follow-up (2026-09-18)

Read-only stock ledger API `GET /api/stock-movements` + Products «Tarix» UI. Uses existing `stock_movements` / `move_stock`. Tests: `backend/tests/test_phase2_stock_history.py`.

## Phase 2 Step 2 follow-up (2026-09-18)

Product master + SKU/barcode foundation. Unique partial indexes on barcode/SKU per store; product list pagination (max 500); exact barcode search first; category on form + company check; `joinedload` category. `move_stock` unchanged. Variants/warehouse not started. Tests: `backend/tests/test_phase2_products.py`.

## Phase 1 follow-up (2026-09-18)

Core POS stabilization (no loyalty/omnichannel/exchange module):

- QQS is **tax-inclusive**: `tax = total * vat / (100 + vat)` via `app/money.py` (`ROUND_HALF_UP`). Same value on sale payload, receipt, dashboard `today.tax`.
- Receipt shows QQS and payment type. POS shows QQS hint.
- CASHIER discount cap: 10% of subtotal (`CASHIER_MAX_DISCOUNT_PCT`); audited.
- Mixed: cash+card/online; card/online cannot exceed total; cash may overpay (change). Underpay requires credit+customer.
- Duplicate checkout: same `idempotency_key` returns existing sale; unique index; UI reuses key until cart changes.
- Inactive product cannot be sold. Qty <= 0 rejected. Stock checked on aggregated product qty.
- Return cannot exceed remaining qty; CASHIER still 403; `sale.return` audit.
- Exchange: **not built** — use return then new sale (existing return architecture).
- Void/cancel: cart line remove is not a sale. Completed sale is not DELETE — only return. No void endpoint.
- Cashier shortcuts: F2 pay, Esc clear scan, F4 cash. Enter still adds barcode.

Tests: `backend/tests/test_phase1_pos.py`.

## HIGH hardening follow-up (2026-09-18)

CORS, rate-limit hardening, platform reset-password (no password in responses), and JWT `cid` vs database membership. Tests: `backend/tests/test_high_security.py`.

## Phase 0 follow-up (2026-09-18)

Security foundation applied for demo-pay authorization, webhook fail-closed behavior, product stock ledger, and production secret validation. Tests in `backend/tests/test_phase0_security.py`. UI/mobile/new features were not started.

**Audit date:** 2026-09-18  
**Auditor role:** Senior Software Architect / Product Architect / Security Engineer / Lead Developer  
**Code changed in this audit:** none  
**Branch:** `main`  
**HEAD:** `78e336c` — Prepare FIXEN POS Web for deployment (Ahmad, 2026-09-12)  
**Working tree:** dirty (user changes present — not discarded). Uncommitted backend/web files, untracked `docs/`, `.cursor/`, `mobile/`.

Git safety: no reset, checkout, clean, or hard reset was performed.

Secret values are **not** included in this report. Only presence of configuration keys is noted.

---

## 1. Executive Summary

FIXEN POS is a **FastAPI monolith** that serves a **vanilla JS SPA** from `backend/app/web/` plus REST under `/api/*`. A **Flutter** companion app exists under `mobile/` (login + dashboard real; AI/reports/alerts placeholder). Data is **SQLAlchemy + SQLite** (PostgreSQL URL theoretically supported; no Alembic). Multi-company SaaS with **multi-store**, JWT RBAC, stock ledger, CRM debt, expenses, shifts, transfers, platform admin, and an AI chat layer with read-only tools.

The product vision is an AI-powered retail operating system. The **live system is a working Core POS + partial Business + early Intelligence**. It is not yet omnichannel, not variant-aware, not PostgreSQL-migrated, and not a full AI business assistant.

**Architecture compliance score: 84 / 100**. Phase 0 + HIGH + Phase 1. Phase 2 Steps 1–6D: product master, ledger, ADJUST, transfer, opname OPEN+UI+finalize. Remaining: opname cancel, write-off, warehouse, variants.

Phase 0 + HIGH closed previous CRITICAL/HIGH security items. Remaining: incomplete audit coverage, SQLite, GET demo-pay read (no activate).

1. Demo-pay confirm unauthenticated — **FIXED** (JWT + billing + company_id).
2. Click/Payme empty-secret skip — **FIXED** (fail-closed reject).
3. Product PATCH stock without ledger — **FIXED** (move_stock ADJUST + audit).
4. Production default JWT/platform secrets — **FIXED** (fail-fast). Dev placeholders remain for local workflow.

---

## 2. Current Architecture

```
Browser SPA (index.html + app.js/saas.js/platform.js/ai.js)
        │  Bearer JWT (localStorage)
        ▼
FastAPI  app.main:app
  routers: auth, catalog, pos, ops, more, saas, platform, ai
        │
SQLAlchemy models  →  SQLite file (DATABASE_URL)
        │
AI layer (OpenAI-compatible HTTP + in-code knowledge.py + read-only tools)
```

| Layer | Implementation |
|-------|----------------|
| Entry | `backend/app/main.py` — `ensure_schema()` at import; CORS; static `/` and `/assets` |
| Config | `backend/app/config.py` + `.env` (pydantic-settings) |
| DB | `backend/app/db.py` — `create_all` + SQLite ALTER extras. **No Alembic** |
| AuthZ | `security.py` ROLE_PERMS + `deps.require_perm` + HQ write guard |
| Ledger | `ledger.move_stock`, `customer_ledger` |
| Frontend | Hash router `#/app/{page}` |
| Mobile | Flutter + Riverpod; default API `http://127.0.0.1:8001` |
| Deploy (known ops) | Hetzner `/opt/fixen-pos`, https://fixen.uz — **this audit did not re-read production files** |

**Not a separate frontend repo.** Web lives inside the backend package.

---

## 3. Existing Modules

Legend: **EXISTS** | **PARTIAL** | **MISSING** | **PLANNED** (vision only) | **UNKNOWN**

### CORE

| # | Module | Status | Evidence |
|---|--------|--------|----------|
| 1 | POS / Sales | EXISTS | `routers_pos.py`, `#/app/pos` |
| 2 | Products | PARTIAL | CRUD + barcode; no variants/brand/image/wholesale as first-class |
| 3 | Barcode | EXISTS | scan UI, autogen EAN-13, JsBarcode cennik |
| 4 | Inventory | PARTIAL | IN/SALE/RETURN/TRANSFER/ADJUST + opname finalize (6D); no cancel/write-off/warehouse |
| 5 | Payments | PARTIAL | cash/card/online/credit fields; no retail PSP |
| 6 | Returns | PARTIAL | full/partial return; no exchange |
| 7 | CRM | PARTIAL | profile, debt, ledger, sales; no loyalty/360 extras |
| 8 | Users / Roles | EXISTS | staff CRUD + RBAC; extra `STORE` role |
| 9 | Reports | PARTIAL | dashboard, analytics JSON, XLSX |

### BUSINESS

| # | Module | Status |
|---|--------|--------|
| 10 | Purchase | PARTIAL — `stock-ins` immediate receive; **no Purchase Order** |
| 11 | Supplier | EXISTS (CRUD); stock-in still uses string `supplier` more than FK |
| 12 | Expenses | EXISTS |
| 13 | Profit | PARTIAL — dashboard/analytics include cost/profit style KPIs |
| 14 | Loyalty | MISSING / PLANNED |
| 15 | Marketing | MISSING / PLANNED |
| 16 | Multi-store | EXISTS |
| 17 | Online Orders | MISSING / PLANNED |

### INTELLIGENCE

| # | Module | Status |
|---|--------|--------|
| 18 | AI Assistant | PARTIAL — chat + KB + read tools |
| 19–24 | Forecast / prediction / reorder / customer intel / anomaly | MISSING / PLANNED |
| 25 | AI Business Reports | PARTIAL — tools can summarize; no scheduled executive report |

### OMNICHANNEL

| # | Channel | Status |
|---|---------|--------|
| 26 | Store | EXISTS |
| 27 | Web | EXISTS (SPA) |
| 28 | Telegram | MISSING (landing contact only) |
| 29 | Mobile | PARTIAL |
| 30 | Delivery | MISSING / PLANNED |
| 31 | Online Orders | MISSING / PLANNED |

---

## 4. Core POS Audit

Intended checkout chain:

Barcode → Product → Cart → Customer → Discount → Tax → Payment → Sale → Inventory → Receipt → Analytics

| Step | Backend | Frontend | Verdict |
|------|---------|----------|---------|
| Barcode | `GET /api/pos/products` | `#scan` Enter exact/unique match | EXISTS |
| Product | store-scoped active products | cart lines | EXISTS |
| Cart | client-side until POST | `window.__pos.cart` | EXISTS (state in JS — acceptable if server re-validates; server **does** re-validate products/stock/prices from DB) |
| Customer | optional `customer_id` | select if `can("customers")` | EXISTS |
| Discount | sale-level discount | `#discount` | EXISTS |
| Tax | company `vat_percent`, inclusive split to `tax_total` | Settings VAT; **receipt UI does not show QQS** | PARTIAL / inconsistency |
| Payment | `paid_cash` + `paid_card` + `paid_online` + credit | four inputs | EXISTS (mixed de-facto) |
| Sale | `Sale` + `SaleItem`; idempotency_key | `POST /api/pos/sale` | EXISTS |
| Inventory | `move_stock(..., SALE)` | — | EXISTS |
| Receipt | JSON `sale_payload`; `GET /api/sales/{id}` | modal + `window.print` | PARTIAL (no hardware printer API; tax omitted on print) |
| Analytics | dashboard aggregates sales | dashboard/hisobotlar | EXISTS |

Other POS notes:

- CASHIER needs open `CashShift`.
- Company not writable → HTTP 402.
- CASHIER cannot return (`role == "CASHIER"` → 403).
- Cancel-sale as dedicated void: **MISSING** (return used instead).
- Exchange: **MISSING**.
- Keyboard shortcuts beyond Enter-to-add: **MISSING**.
- Negative stock on sale: blocked in `move_stock` and pre-check.

---

## 5. Inventory Audit

| Operation | Linked to inventory | Linked to sale/purchase | Audit (`stock_movements` / `audit_logs`) |
|-----------|---------------------|-------------------------|------------------------------------------|
| STOCK IN | EXISTS `POST /api/stock-ins` | purchase doc `stock_ins` (not PO) | movement kind `IN`; `audit_logs` **not** used here |
| STOCK OUT dedicated | MISSING | — | — |
| SALE | EXISTS | `sales` | kind `SALE` |
| RETURN | EXISTS | `sales.returned_qty` | kind `RETURN` |
| TRANSFER | EXISTS | `stock_transfers` | `TRANSFER_OUT` / `TRANSFER_IN` + `audit_logs` `transfer.create` |
| ADJUSTMENT | MISSING as API (kind exists in comment) | — | Product PATCH can set `stock` **without** movement — **integrity gap** |
| WRITE-OFF | MISSING | — | — |
| STOCK OPNAME | MISSING | — | — |
| OPENING | EXISTS on product create | — | kind `OPENING` |

**Negative stock:** `move_stock` rejects `new_qty < -0.0001`. Bypass risk: PATCH product `stock`.

**Warehouse:** no `warehouses` table. Stock lives on `products.stock` per store (product row is store-scoped).

HQ OWNER/ADMIN blocked from stock-in / cash / expense / shift / transfer writes (`forbid_company_kirim_write`) — by design for company cabinet.

---

## 6. CRM Audit

Customer 360: **PARTIAL**.

| Capability | Status |
|------------|--------|
| Profile (name, phone, email, note, active) | EXISTS |
| Purchase history | EXISTS `GET /api/customers/{id}` sales list |
| Total purchases / last purchase as stored fields | **MISSING** as columns — can be derived from sales (UNKNOWN if UI shows aggregates) |
| Debt | EXISTS `customers.debt` + `customer_ledger` + `pay-debt` |
| Credit limit | EXISTS |
| Loyalty points / tier | MISSING / PLANNED |
| Per-customer discount | MISSING / PLANNED |
| Birthday / favorites | MISSING / PLANNED |
| Segmentation | MISSING / PLANNED |
| Store-level customer | Customers are **company-scoped**, not `store_id` |

---

## 7. Payment Audit

### Retail POS tender

EXISTS as amounts on `sales`: `paid_cash`, `paid_card`, `paid_online`, `on_credit`. Mixed payment is **de-facto**, not a named `MIXED` type.

No Click/Payme/Uzcard/Humo **for the cart**. Online is a numeric field.

### SaaS subscription billing

PARTIAL:

- `GET /api/billing`, `POST /api/billing/checkout`
- Click/Payme webhook endpoints
- Demo pay pages
- Web Settings UI currently emphasizes **bank requisites** (not PSP buttons) — marketing landing may still mention Click/Payme

Webhooks and demo-pay: see Security.

### Refunds

Return reverses stock and adjusts cash/credit. Dedicated payment-provider refund: **MISSING**.

---

## 8. SaaS / Multi-tenant Audit

Isolation model: `company_id` on core tables; `store_id` on products/sales/stock/cash/expenses/shifts.

**Company isolation:** handlers generally filter `company_id == user.company_id`. Tests: `test_multi_store.py` (`test_company_isolation`, wrong-company cases), AI tools isolation tests.

**Store isolation:** `current_store()`; STORE role locked to `user.store_id`; switch-store forbidden for STORE; OWNER/ADMIN may switch.

**CRITICAL findings (do not fix in this phase):**

1. **Unauthenticated demo billing confirm** can activate a company’s plan if `payment_id` is known/guessable. Cross-tenant **integrity** (plan status), not product-data leak, but still SaaS-critical.
2. **Empty Click/Payme secrets skip verify** — unauthenticated webhooks can activate payments.
3. JWT `cid`/`sid` **not re-checked** against DB on each request. Effective tenant is `User.company_id`. Stolen token follows the user row. Cross-company leak via this path: **not observed** if user row is correct.

**Not observed in reviewed POS/catalog/ops paths:** query that omits `company_id` for another tenant’s products/sales.

**IDOR:** within a company, OWNER/ADMIN seeing other stores is largely by design. Cross-company IDOR on standard resource GETs: not observed.

**Username** is **globally unique** — tenant-local usernames are not supported.

**AI:** tools strip `company_id`/`store_id` args; queries use current user scope. Bug reports and conversations are company+user scoped.

Platform impersonate issues an owner JWT — powerful; protected by platform credentials.

---

## 9. Security Audit

### CRITICAL

None open after Phase 0 (2026-09-18). Prior demo-pay, webhook, and production-secret issues are closed.

### HIGH

None open after HIGH hardening (2026-09-18).

Closed:
- CORS `*` + credentials — explicit origins; production forbids `*`; empty production list = same-origin only.
- In-memory rate limit — keys normalized/capped; login IP+username buckets; still per-process (not Redis).
- Platform reset-password no longer returns the password; operator supplies the new password.
- JWT `cid` is checked against current `User.company_id`; suspended company and inactive user rejected. Permissions still use DB role.

### MEDIUM

9. `audit_logs` coverage is **narrow** (auth, some SaaS/platform/shift/transfer). Missing: sale, return, discount, product price, settings, staff permission changes. Stock PATCH and billing activation are now audited.
10. Customers company-wide; no store partition if that becomes a requirement.
11. SPA tokens in `localStorage` — XSS would steal session (standard SPA risk). `esc()` used widely; residual `innerHTML` pattern remains a discipline requirement.
12. `STORE` role is an architecture delta vs documented five roles.

### LOW

13. Global unique username collisions across tenants.
14. No `/api/v1` versioning.
15. SQLite file for production architecture (ops/lock/backup) — see Database.

### Checks that look acceptable

| Control | Status |
|---------|--------|
| Password hashing PBKDF2-HMAC-SHA256 120k | EXISTS |
| ORM parameterized queries; DDL identifiers hardcoded | SQL injection risk LOW |
| Asset path traversal guard | EXISTS |
| AI tenant scoping + secret redaction + injection detect | EXISTS |
| Input validation via Pydantic | EXISTS |
| `.env` gitignored; `.env.example` present | EXISTS |

`.env` **exists** under backend (keys include AI_*). Values not reported.

---

## 10. Database Audit

**Engine:** SQLAlchemy. Default URL SQLite. PostgreSQL-ready: **PARTIAL** (URL-driven engine; dialect-specific `PRAGMA`/`ALTER` extras are SQLite-only; no migration tool).

**Migrations:** `ensure_schema()` create_all + additive ALTERs. Not Alembic. Not reversible.

### Tables

| Table | Purpose | Important fields | Tenant |
|-------|---------|------------------|--------|
| companies | Tenant root / plan | plan, status, vat_percent, account_no | root |
| stores | Locations | name, is_active | company_id |
| users | Logins | username unique global, role, password_hash | company_id, optional store_id |
| categories | Product groups | name | company_id |
| products | Catalog + qty | sku, barcode, prices, **stock**, min_stock | company_id, store_id |
| stock_ins / stock_in_items | Goods receipt | number, supplier string, qty, buy_price | header: company+store |
| sales / sale_items | Tickets | payments, tax_total, returned_qty | header: company+store |
| customers | CRM | phone, debt, credit_limit | company_id only |
| customer_ledger | Debt movements | kind, amount | company_id |
| expenses | Costs | category, amount | company_id, store_id |
| cash_txns | Cash drawer | SALE/IN/OUT | company_id, store_id |
| cash_shifts | Shifts | opening/closing | company_id, store_id |
| suppliers | Vendor master | name, phone | company_id |
| stock_movements | Qty ledger | kind, qty, balance_after | company_id, store_id |
| stock_transfers / items | Inter-store | from/to store | company_id |
| billing_payments | SaaS invoices | plan, status, method | company_id |
| audit_logs | App audit | action, payload | optional company_id |
| ai_conversations / ai_messages / ai_bug_reports | AI | content, provider | company/user |

### Problems

| Issue | Severity |
|-------|----------|
| No warehouses table | architecture gap |
| No product_variants | architecture gap |
| Integer PKs not UUID | architecture delta |
| `stock` duplicated as cache on products vs movements | OK if always via `move_stock`; PATCH breaks this |
| `stock_ins.supplier` string vs `supplier_id` | inconsistent |
| Child tables without `company_id` (sale_items, etc.) | OK if parent always joined; extra defense missing |
| Missing timestamps on Category, StockInItem, SaleItem | minor |
| Missing FKs enforcement on SQLite | SQLite FK pragma **UNKNOWN** (not verified in this pass) |
| Indexes: company_id/store_id/barcode yes; **no extra composite** (e.g. sales by date+store) beyond `index=True` | possible report perf issue |
| Duplicate tables | **not observed** |

PostgreSQL cutover readiness: **MEDIUM**. Would need: Alembic (or equivalent), FK pragma strategy, replace SQLite-only DDL, backup/restore, concurrency tests.

---

## 11. API Audit

Prefix is **`/api` (not `/api/v1`)**. Auth: Bearer JWT unless noted. Permission via `require_perm(...)`.

### Auth `/api/auth`

| Method | Path | Auth | Perm | Purpose | DB |
|--------|------|------|------|---------|-----|
| POST | `/register` | no (rate limited) | — | Create company, store, OWNER | insert company/store/user/products |
| POST | `/login` | no (rate limited) | — | JWT | read user |
| GET | `/me` | JWT | any user | Profile + permissions + cabinet | read |
| POST | `/change-password` | JWT | self | Password | update user |
| POST | `/auth/switch-store` | JWT | not STORE | New JWT | read store |

### Catalog `/api`

| Method | Path | Perm | Purpose | DB |
|--------|------|------|---------|-----|
| GET/POST | `/categories` | products | Categories | read/write |
| GET/POST | `/products` | products | List/create; opening stock via ledger | write + movement |
| PATCH | `/products/{id}` | products | Update **including stock** | write product, **no movement** |
| POST | `/products/{id}/toggle` | products | Active flag | update |

### POS / sales

| Method | Path | Perm | Purpose | DB |
|--------|------|------|---------|-----|
| GET | `/pos/products` | pos | Search | read |
| POST | `/pos/sale` | pos | Checkout | sale, items, stock, cash, ledger |
| GET | `/sales` | pos | History | read |
| GET | `/sales/{id}` | pos | Receipt payload | read |
| POST | `/sales/{id}/return` | pos (not CASHIER) | Return | sale items, stock, cash/ledger |

Request/response: Pydantic in `schemas.py` (`SaleIn`, `ProductIn`, …). Exact field lists not duplicated here.

### Inventory / cash / reports / staff

| Method | Path | Perm | Notes |
|--------|------|------|-------|
| POST/GET | `/stock-ins` | stock | HQ write blocked |
| GET | `/stock-ins/{id}` | stock | |
| GET/POST | `/cash` | cash | HQ write blocked |
| GET | `/reports/dashboard` | reports | KPIs |
| GET | `/reports/analytics` | reports | JSON |
| GET | `/reports/export` | reports | XLSX |
| GET/POST/PATCH | `/staff`, `/staff/{id}` | staff | |
| POST | `/staff/{id}/toggle` | staff | |

### CRM / expenses / settings

| Method | Path | Perm |
|--------|------|------|
| GET/POST | `/customers` | customers |
| GET/PATCH | `/customers/{id}` | customers |
| POST | `/customers/{id}/pay-debt` | customers |
| GET/POST | `/expenses` | cash |
| GET | `/settings` | any JWT |
| PATCH | `/settings` | settings |

### SaaS billing / shifts / suppliers / transfers

| Method | Path | Auth | Perm |
|--------|------|------|------|
| GET/POST/PATCH | `/stores` | JWT | stores |
| GET | `/billing` | JWT | any |
| POST | `/billing/checkout` | JWT | billing |
| GET/POST | `/billing/demo-pay/{id}` `/confirm` | **none** | **none** |
| POST | `/billing/webhook/click\|payme` | signature or **skip** | none |
| GET/POST | `/shifts/current\|open\|close` | JWT | cash |
| GET/POST/PATCH | `/suppliers` | JWT | suppliers |
| GET/POST | `/transfers` | JWT | stock |

### Platform `/api/platform`

Platform JWT (`require_platform`). Login uses env credentials. Endpoints: me, overview, companies CRUD/patch, impersonate, reset-password, audit.

### AI `/api/ai`

All JWT. No extra RBAC beyond login for chat; **tools** inside chat enforce `TOOL_PERMS`.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/status` | Provider flags (no secrets) |
| POST | `/chat` | Assistant |
| GET/DELETE | `/history` | Per-user conversation |
| POST | `/report` | Bug row |

### Other

| Method | Path | Auth |
|--------|------|------|
| GET | `/api/health` | none |
| GET | `/` `/assets/...` | none |

**Missing vs architecture named APIs:** `/api/inventory` as module name (ops use `/stock-ins`, `/transfers`); `/api/payments` (fields on sale); `/api/purchases` (stock-ins).

---

## 12. Frontend Audit

- **Framework:** none (vanilla JS modules)
- **Entry:** `backend/app/web/index.html` → `assets/app.js`
- **Routing:** hash (`#/`, `#/login`, `#/register`, `#/platform`, `#/app/{page}`)
- **State:** `localStorage` + `window.__*` page globals; full innerHTML rerender
- **API:** `api()` fetch + Bearer
- **Pages:** dashboard, hisobotlar, pos, products, stock, transfers, sales, customers, cash, expenses, suppliers, stores, staff, settings
- **Cabinets:** company vs store; store hides stores/settings/staff/transfers
- **Billing UI:** bank requisites + plan select (no live Click/Payme buttons in current settings render)
- **XSS:** `esc()` helper; AI answers via `textContent`. Residual risk from `innerHTML` architecture
- **JS tests:** **MISSING**
- **PWA/kiosk:** manifest + PowerShell shortcut txt
- **Print:** browser `window.print` for receipt and cennik

Kassir UX (Phase 1): barcode Enter adds; F2 pay, Esc clear scan, F4 cash; QQS shown on POS and receipt; mixed tenders exist.

Manager: dashboard + reports + inventory + staff (if perm).

Owner: profit/analytics partial; AI widget; billing in settings.

---

## 13. Mobile Audit

- **Framework:** Flutter (`fixen_ai_mobile`)
- **Auth:** `POST /api/auth/login`, secure storage JWT
- **API:** `ApiClient` Bearer; 401 logout
- **State:** Riverpod
- **Real screens:** Login, Dashboard
- **Placeholders:** AI, Reports, Alerts
- **POS/checkout on mobile:** MISSING
- **Tests:** auth_repository, dashboard_repository, widget_test

`PHASE_STATUS.txt` describes phased mobile work. This audit did not modify `mobile/`.

---

## 14. AI Audit

| Item | Finding |
|------|---------|
| Endpoints | `/api/ai/status`, `/chat`, `/history`, `/report` |
| Provider | `OpenAICompatProvider` (`ai_provider`, `ai_base_url`, `ai_model`, `ai_api_key`) |
| Fallback | `FallbackProvider` **exists in code but is not wired** into `service.chat` when key missing → 503 |
| Knowledge | `knowledge.py` ARTICLES (~14 how-to ids) + error hints |
| Tools | Read-only: today sales, top products, low stock, inventory, product stock, sales/profit summary |
| DB access | ORM via `queries.py`; writes only AI tables |
| Permissions | Chat: any logged-in user; tools check `TOOL_PERMS` |
| Logging | `ai_messages` stores content, provider, latency, error |
| Tenant | Conversation per company+user; queries filter company (+ store scope) |
| Unsupervised writes | **not found** for sales/stock |

Future readiness:

| Capability | Ready? |
|------------|--------|
| Sales analysis | PARTIAL (tools) |
| Inventory analysis | PARTIAL |
| Customer analysis | MISSING as tools (inactive-90-days etc.) |
| Forecast / smart reorder | MISSING |
| Alerts (push/Telegram) | MISSING |
| AI executive reports | PARTIAL / manual chat |

AI seeing another tenant: **not observed** in query helpers; tests cover isolation.

---

## 15. Missing Features

### EXISTING (real in code)

POS checkout, products, barcode autogen, stock-in, transfers, sales/returns, customers + debt, expenses, cash + shifts, staff, stores + STORE login, company/store cabinets, dashboard/analytics/xlsx, suppliers, platform admin, AI chat+KB+tools, web print, Flutter login/dashboard, tests for multi-store and AI.

### PARTIAL

Purchase (no PO), profit reports, supplier FK on stock-in, Click/Payme billing, AI assistant vs BOS, mobile beyond dashboard, audit log coverage, PostgreSQL readiness, HQ vs store UX for transfers. Receipt QQS + mixed naming closed in Phase 1.

### MISSING (not in code)

Product variants, warehouses, write-off, opname, dedicated ADJUST API, exchange (policy: return+new sale), cancel-sale void endpoint, loyalty, marketing, Telegram/SMS integrations, retail payment PSPs, online orders, delivery, forecast, anomaly detection, API versioning, UUID PKs, Alembic, mobile AI/reports/alerts/POS.

### PLANNED (architecture vision — do not treat as bugs)

Omnichannel channels, loyalty tiers, marketing campaigns, AI forecast/automation, Click/Payme/Uzcard/Humo as POS tenders, Customer 360 extras (birthday, favorites, segments).

Do not mix these four buckets.

---

## 16. Technical Debt

- Monolithic routers (`routers_saas.py` ~37KB, `routers_ops.py` ~26KB, `app.js` ~109KB)
- SPA full-page innerHTML rerenders
- SQLite `ensure_schema` instead of migrations
- Stock PATCH uses ledger ADJUST (Phase 0); opname finalize via `move_stock` ADJUST (6D); cancel/write-off still missing
- Unversioned API
- STORE role vs documented RBAC
- Username global unique
- Billing demo-pay/webhooks closed Phase 0; production secrets fail-fast
- Fallback AI provider dead code
- Landing copy vs bank-requisites billing mismatch
- No frontend automated tests
- `even/` and `backups/` gitignored (contents not audited)

---

## 17. Critical Risks

| ID | Risk | P | Type |
|----|------|---|------|
| R1 | Unauthenticated demo-pay confirm — FIXED Phase 0 | — | — |
| R2 | Empty PSP webhook skip — FIXED Phase 0 | — | — |
| R3 | Insecure production secrets at startup — FIXED Phase 0 | — | — |
| R4 | PATCH stock bypasses ledger — FIXED Phase 0 | — | — |
| R5 | CORS star+credentials — FIXED HIGH hardening | — | — |
| R6 | Incomplete audit trail | P2 | Compliance / forensics |
| R7 | SQLite in production (locks, backup, scale) | P2 | Scalability |
| R8 | No variants — future catalog rewrite | P3 | Architecture |
| R9 | AI not full BOS — wrong expectations | P3 | Product |
| R10 | Rate limit still in-memory per process (documented, not Redis) | P3 | Ops |

No **P0** “app will not start” issue was found in this static audit. Runtime production process health was **not re-checked** in this pass.

---

## 18. Recommended Development Roadmap

The **vision** order puts Multi-store at PHASE 7. **This codebase already has Multi-store.** Therefore the practical order is:

| Phase | Focus | Why now |
|-------|--------|---------|
| **PHASE 0** | Architecture & Security Foundation | Close R1–R4; env secret policy; webhook deny-if-empty-secret; demo-pay auth; stock PATCH via ledger; document STORE role |
| **PHASE 1** | Core POS stabilization | Receipt tax, exchange/void policy, cashier shortcuts, sale/return tests |
| **PHASE 2** | Inventory + Products | ADJUST/write-off/opname; stop dual stock writes; index/report; variants **design only until approved** |
| **PHASE 3** | CRM | Customer 360 fields, history aggregates, still no loyalty yet |
| **PHASE 4** | Payments + Returns | Tender consistency; refund/cash drawer; do not fake PSP |
| **PHASE 5** | Purchase + Supplier | PO → receive → cost; wire `supplier_id` |
| **PHASE 6** | Reports + Analytics | Profit, cashier, store performance completeness |
| **PHASE 7** | Multi-store harden | Warehouses decision; HQ read vs write; keep STORE until approved |
| **PHASE 8** | Loyalty + Marketing | After CRM solid |
| **PHASE 9** | Omnichannel | Mobile POS, orders; Telegram as channel not just contact |
| **PHASE 10** | AI Business Assistant | Wire fallback; more tools; no unsupervised writes |
| **PHASE 11** | Forecast + Automation | Only after data quality (ledger + history) |

**Do not start a new feature until PHASE 0 items are scheduled.** This audit itself does not implement them.

---

## 19. Architecture Compliance Score

**Score: 84 / 100** (was 83 after Step 6C, 82 after Step 6B, 81 after Step 6A, 80 after Step 5)

Technical alignment with master architecture only.

| Area | Score | Note |
|------|------:|------|
| Vision / module coverage | 58 | Core strong; L3–L4 thin |
| Layering (FE/BE/DB/AI) | 74 | AI separate; JS still has UX state |
| Tenant isolation | 78 | Filters exist; billing holes |
| RBAC | 70 | Works; STORE delta; stale JWT claims |
| POS checkout integrity | 82 | Inclusive QQS on sale/receipt/dashboard; cashier discount cap; idempotency |
| Inventory auditability | 82 | ADJUST + transfer + opname finalize (6D); cancel/write-off still missing |
| CRM 360 | 48 | Debt yes; loyalty no |
| Payments architecture | 42 | Fields yes; integration layer weak |
| API design | 60 | REST+RBAC; unversioned; fat routers |
| Database / migrations | 54 | ORM ok; SQLite extras + opname tables; still no Alembic |
| Security posture | 78 | Phase 0 + HIGH hardening (CORS, rate-limit, reset-password, JWT cid) |
| AI readiness | 55 | Scoped tools; not BOS |
| Omnichannel | 28 | Web yes; mobile partial |
| Documentation / tests | 60 | AI+store tests; no FE tests |

This is **not** a rating of business success or UX polish.

---

## Appendix A — Git snapshot (audit start)

- Branch: `main`
- HEAD: `78e336c`
- Modified (left untouched): `backend/app/ai/knowledge.py`, `deps.py`, `routers_auth.py`, `routers_catalog.py`, `routers_more.py`, `routers_ops.py`, `routers_saas.py`, `schemas.py`, `security.py`, `web/assets/app.js`, `saas.js`, `index.html`, `tests/test_multi_store.py`
- Untracked at start: `.cursor/`, `docs/FIXEN_MASTER_ARCHITECTURE.md`, `mobile/`, kiosk shortcut txt

## Appendix B — Env key names (no values)

From `.env.example`: `JWT_SECRET`, `DATABASE_URL`, `APP_URL`, `CORS_ORIGINS`, `PLATFORM_OWNER_LOGIN`, `PLATFORM_OWNER_PASSWORD`, `CLICK_SERVICE_ID`, `CLICK_MERCHANT_ID`, `CLICK_SECRET`, `PAYME_MERCHANT_ID`, `PAYME_KEY`, `AI_ENABLED`, `AI_PROVIDER`, `AI_API_KEY`, `AI_BASE_URL`, `AI_MODEL`, `AI_MAX_TOKENS`, `AI_TIMEOUT_SEC`, `AI_MAX_HISTORY`, `AI_MAX_MESSAGE_CHARS`, `AI_RATE_LIMIT`, `AI_RATE_WINDOW`, `AI_TEMPERATURE`.

Backend `.env` **exists**. Values omitted.

## Appendix C — Files read (primary)

`main.py`, `config.py`, `db.py`, `models.py`, `schemas.py`, `security.py`, `deps.py`, `ledger.py`, `audit.py`, `plans.py`, `routers_*.py`, `ai/*`, `web/assets/*.js`, `index.html`, `backend/tests/*`, `mobile/lib/**` (via exploration), `README.md`, `.gitignore`.

END OF AUDIT.

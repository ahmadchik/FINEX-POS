# FIXEN POS — Phase 2 Products + Inventory Architecture

**Status:** STEP 1–6D implemented (product master, ledger, ADJUST, transfer, opname DB + OPEN API + UI + **finalize**)  
**Date:** 2026-09-19  
**Git HEAD (inspected):** `1cc862d34b0d4ca66cd9a894b640ae095c67ed37` (`main`)  
**Steps 2–6D code:** uncommitted (do not auto-start Step 6E / cancel)  
**Baseline tests before Step 6D:** 141 passed / 0 failed  

This document describes **what the code does today**, then proposes a **compatibility-first** path. It does not rewrite `FIXEN-MASTER-ARCHITECTURE.md`. Large items (product variants model, warehouse entity, UUID, Alembic, API versioning) require Ahmad’s explicit approval before implementation.

---

## 1. Current Architecture

FIXEN is a FastAPI monolith + vanilla JS SPA. Catalog and inventory live in the same backend as POS.

```
Company
  → Store
      → Product          (sellable unit: name + sku + barcode + stock cache)
      → StockIn          (kirim document)
      → StockTransfer    (store → store)
      → Sale / Return
      → StockMovement    (ledger rows written by move_stock)
```

There is **no Warehouse table**. There is **no ProductVariant table**. Stock quantity is a **cached column** on `products.stock`, updated only through `ledger.move_stock` (Phase 0 closed the PATCH `setattr(stock)` hole).

Live vs master vision (already recorded as deltas — do not “fix” silently):

| Master vision | Live code |
|---------------|-----------|
| Company → Stores → Warehouses → Products | Company → Stores → Products (`store_id`) |
| Product → Variant → SKU → Barcode | One `Product` row = one SKU + one barcode + one stock |
| `/api/inventory` | `/api/stock-ins`, `/api/transfers`, `move_stock` |
| UUID PKs, `/api/v1`, Alembic | Integer PKs, `/api`, `ensure_schema()` |

RBAC that touches inventory: `products` and `stock` permissions. Roles: OWNER/ADMIN (full), MANAGER (products+stock), WAREHOUSE (products+stock, no POS), CASHIER (POS only), extra **STORE** role (POS+products+stock; do not remove). HQ OWNER/ADMIN cannot write kirim/transfer/cash from company cabinet (`forbid_company_kirim_write`).

---

## 2. Current Product System

**Table:** `products` (`backend/app/models.py` `Product`)

| Field | Type | Today |
|-------|------|--------|
| `id` | int PK | EXISTS |
| `company_id` | FK companies | EXISTS, indexed, required for tenant isolation |
| `store_id` | FK stores | EXISTS, indexed — **catalog is per-store, not company-wide** |
| `category_id` | FK categories, nullable | EXISTS in DB/API; **not on product form UI** |
| `name` | string | EXISTS |
| `sku` | string default `""` | EXISTS; **no uniqueness**, not required |
| `barcode` | string, index | EXISTS; uniqueness **only in application** per `(company_id, store_id, barcode)` — **no DB unique index** |
| `unit` | string default `dona` | EXISTS |
| `buy_price` | float | EXISTS (cost) |
| `sell_price` | float | EXISTS (tax-inclusive sell price; POS uses this) |
| `stock` | float | EXISTS — **quantity cache**, not a ledger |
| `min_stock` | float default 0 | EXISTS — threshold field |
| `manufacturer` | string | PARTIAL stand-in for brand; **not on product form** |
| `vat_rate` | float nullable | PARTIAL — column exists; **POS/receipt use `Company.vat_percent`**, not this |
| `is_active` | bool | EXISTS; toggle API; inactive cannot be sold (Phase 1) |
| `created_at` | datetime | EXISTS |
| brand (entity) | — | MISSING |
| description | — | MISSING |
| wholesale price | — | MISSING |
| image | — | MISSING |
| product–supplier FK | — | MISSING (kirim uses string `supplier`) |

**Category:** `categories` is company-scoped (`company_id` + `name`). API: `GET/POST /api/categories`. No update/delete. No unique `(company_id, name)`.

**APIs (actual):**

| Method | Path | Perm | Isolation | Inventory |
|--------|------|------|-----------|-----------|
| GET | `/api/products?q=&barcode=` | `products` | `company_id` + `current_store()` | read cache |
| POST | `/api/products` | `products` | same | opening qty via `move_stock` kind `OPENING` |
| PATCH | `/api/products/{id}` | `products` | same store | **stock ignored** (not a master field write). Opening remains create-only. |
| POST | `/api/products/{id}/toggle` | `products` | same | none |
| GET | `/api/pos/products?q=` | `pos` | same, `is_active` only, limit 80 | read |
| GET/POST | `/api/categories` | `products` | `company_id` only | none |

**Search:** server `ilike` on name/barcode/sku (`%q%`). POS: exact barcode first, then unique name/barcode substring (`findScanProduct`). Table filter on products page is client-side only.

**Barcode:** empty on create → auto EAN-13 (`200…` + check digit), unique-retry in-process. Duplicate → 409. Cennik print exists (JsBarcode). Keyboard scanner = typed input + Enter.

### EXISTING
CRUD, per-store catalog, barcode generate + duplicate check, SKU field, unit, buy/sell, active flag, POS search/scan, opening stock via ledger.

### PARTIAL
Category (API without UI), manufacturer-as-brand, `vat_rate` unused by checkout, `min_stock` field without alerting module, SKU without uniqueness.

### MISSING
Brand entity, images, description, wholesale, variants, company-level product master, dedicated barcode table, pagination.

---

## 3. Current Inventory System

**Quantity source of truth (operational):** `Product.stock` (float, 3 dp in `move_stock`).

**Quantity source of truth (history):** `stock_movements` rows. There is **no API** that lists them. `StockMovement` is written only from `ledger.move_stock`.

**Kinds in code comments / writers:**

| Kind | Writer | Document |
|------|--------|----------|
| `OPENING` | `POST /products` | product create |
| `IN` | `POST /stock-ins` | kirim |
| `SALE` | `POST /pos/sale` | sale |
| `RETURN` | `POST /sales/{id}/return` | return |
| `TRANSFER_OUT` / `TRANSFER_IN` | `POST /transfers` | transfer |
| `ADJUST` | `POST /api/stock-adjustments` via `move_stock(kind=ADJUST)` | difference-based; PATCH stock ignored |

**MISSING as first-class operations:** stock OUT (non-sale), write-off, opname, receive-pending transfer, warehouse move.

**Negative stock policy:** `move_stock` refuses `new_qty < -0.0001` with HTTP 400 `"qoldiq yetarli emas"`. POS also pre-checks aggregated qty.

**Stock-in (`/api/stock-ins`):** immediate receive into current store. Updates `buy_price` if provided. `supplier` is a **string**; `supplier_id` column exists on `stock_ins` but create path does not set it. HQ cabinet blocked. History UI = last 50 kirim documents, not the movement ledger. **No `write_audit` on kirim** (only stock row).

**Stock-out:** only via SALE (and TRANSFER_OUT). No write-off endpoint.

**Transfer:** see §5 / §7.

**Adjustment:** see §8.

---

## 4. Current Stock Ledger

**Equivalent system already exists:** `stock_movements` + `move_stock()`. **Do not create a second ledger.**

Can it answer WHO / WHEN / WHAT / HOW MUCH / WHY / FROM / TO?

| Question | Column / join | Answerable today? |
|----------|----------------|-------------------|
| WHEN | `created_at` | YES |
| WHAT product | `product_id` | YES (id, not SKU snapshot) |
| HOW MUCH | `qty` (signed), `balance_after` | YES |
| WHO | `user_id` nullable | PARTIAL (null if no user) |
| WHY | `kind` + `note` + `ref_type`/`ref_id` | PARTIAL (`ADJUST` note often `"product.patch"`; no reason enum) |
| FROM WHERE | `store_id` on the row | PARTIAL (store, not warehouse) |
| TO WHERE | not on one row | PARTIAL — transfer uses **two** rows (`TRANSFER_OUT` at src, `TRANSFER_IN` at dst) linked by `ref_type=transfer` + `ref_id` |

Example mapping for:

`2026-09-18 · Ali · ST-001 · SALE · -3 · Urgut · Main`

- Date/user/product/kind/qty/store: **possible** if SKU `ST-001` is `products.sku` and Ali is `user_id`.
- Warehouse `Main`: **cannot** — no warehouse.

**Gap:** no GET `/api/stock-movements` (or similar). History cannot be shown in UI without a new read API on the **existing** table.

---

## 5. Current Multi-store Model

- Tenant: `company_id` on products, movements, stock-ins, transfers, sales.
- Location of stock: `store_id` on the **product row itself**. Transfer does **not** move a shared product; it decrements source product and increments (or **clones**) a destination product matched by **same barcode**.
- `current_store()`: STORE role locked to `user.store_id`; others use `user.store_id` or first company store.
- HQ cannot create kirim/transfer (403). Product CRUD from HQ still hits `current_store()` — OWNER may edit the default store catalog from company cabinet.
- Cross-company leakage: list/get paths checked in this audit filter `company_id` (and store where required). `db.get(Product, id)` is always followed by company/store checks on catalog, stock-in, POS, transfer source.
- Cross-store leakage: products are store-scoped. `GET /api/transfers` lists **company-wide** last 50 (STORE user can see other stores’ transfer headers: number, from, to, date — not line qty). Same-tenant, not IDOR across companies.

**`warehouse_id`:** not present. Future column must be additive and nullable.

---

## 6. Missing Capabilities

| Capability | Status |
|------------|--------|
| Company-level product master | MISSING (store-cloned products) |
| Variants (size/color/…) | MISSING |
| Brand entity / images / wholesale / description | MISSING |
| DB-unique barcode/SKU | MISSING |
| Warehouse | MISSING |
| `stock_balances` by location | MISSING (cache on product) |
| Movement history API / UI | MISSING |
| Dedicated adjustment API + reason | EXISTS (`POST /api/stock-adjustments`, Step 4) |
| Write-off | MISSING |
| Stock opname | DB + OPEN API + UI + **finalize POSTED** (6A–6D); no cancel endpoint |
| Transfer draft / receive / reject | MISSING (always `DONE`) |
| Low-stock alerts (push/Telegram) | MISSING |
| Critical vs min thresholds | MISSING (single `min_stock`) |
| Inventory reports module | PARTIAL (dashboard `low_stock` + Excel sales reports, not stock card) |
| Pagination / barcode unique index | MISSING |
| Purchase Order | OUT OF SCOPE (Layer 2 BUSINESS) — do not start |

---

## 7. Variant Architecture

**Today:** MISSING. Clothing example **SANTENNI T-Shirt BLACK/M … WHITE/XL** would be **six independent `Product` rows** (six barcodes, six `stock` values) at **each store**. POS already sells by `product_id`. Transfer matches clones by barcode, so each size/color must share the same barcode across stores to transfer.

**Do not implement in this step.** Variants are a **large architecture change** (cursor master rule). Approval required.

**Safest future (compatibility first):**

1. Keep `products` as the **sellable SKU** POS already uses (`product_id` on sale_items, stock_in_items, transfer items, movements).
2. Add optional grouping later, not a parallel catalog:
   - `parent_id` nullable on `products` **or** a thin `product_styles` table (`company_id`, name, brand…) with `products.style_id`.
   - Variant attributes: `color`, `size`, `style` columns or JSON `variant_attrs` on the **same product row**.
3. Avoid a new `product_variants.id` as the POS line key until a versioned API is approved — that would break every existing sale/return/transfer FK.

**Not recommended first:** replacing Product with Variant+SKU+Barcode tables and rewriting POS. That destroys working checkout.

**Clothing target model (later, after approval):**

```
Style: SANTENNI T-Shirt
  SKU/Product: ST-TS-BLK-M   barcode …  color BLACK  size M  stock @ store
  SKU/Product: ST-TS-BLK-L   …
```

UI can group by style; inventory and POS stay on the child row.

---

## 8. Warehouse Architecture

**Today:** MISSING as an entity. `WAREHOUSE` is only an **RBAC role**. Stock location = store.

**Do not implement in this step.** Warehouse under Store is master-vision Layer 1/2; introducing it changes every stock write.

**Future (after approval), additive:**

```
Company → Store → Warehouse (default one: "Asosiy ombor")
                → stock_balances (product_id, warehouse_id, qty)
```

Migration compatibility:

- Each existing store gets one default warehouse.
- `products.stock` remains the **store-level cache** = sum of warehouse balances (or the single default warehouse).
- `stock_movements.warehouse_id` nullable; backfill default. POS sale uses the store’s default warehouse until UI can choose.

Reports: filter by store now; warehouse later. Transfers today are store↔store; warehouse↔warehouse is a later extension of the **existing** `StockTransfer` document, not a new module.

---

## 9. Stock Movement Architecture

**Keep `move_stock` as the only writer of `products.stock` and `stock_movements`.**

Proposed (later) read/hardening — not a new ledger:

- `GET /api/stock-movements?product_id=&kind=&from=&to=` — tenant + store scoped.
- Require `qty > 0` on kirim/transfer item bodies (today negative qty could invert direction).
- Dedicated `POST /api/stock-adjustments` with `reason` calling `move_stock(..., kind="ADJUST")`.
- Optional kind `WRITE_OFF` still via `move_stock` (negative qty, reason required).
- Do not add Redis; do not dual-write stock outside `move_stock`.

Transfer is already two ledger rows + one `stock_transfers` header in a **single SQLAlchemy commit** (atomic if the request errors before commit; `get_db` rollbacks on exception).

---

## 10. Stock Opname Architecture

**Today (Step 6A–6D):** tables + OPEN API + SPA UI + **POST `/api/stock-opnames/{id}/finalize`**. Cancel endpoint still later.

- Header is company/store scoped (`company_id`, `store_id`). No `warehouse_id`. No `variant_id`.
- Statuses: `OPEN` | `POSTED` | `CANCELLED` (default `OPEN`).
- `number` VARCHAR(40) — same document-id style as `IN-`/`TR-`; generation is **not** implemented yet (API later).
- `counted_qty` and `difference` are nullable while OPEN. `system_qty` is FLOAT (same family as `products.stock` / `stock_movements.qty`).
- Partial unique index: one OPEN opname per `(company_id, store_id)`.
- Unique `(opname_id, product_id)` — one product once per opname.
- FKs: `NO ACTION` (no cascade delete of history). Relationship has no `delete-orphan`.
- `ensure_schema` creates missing tables via `Base.metadata.create_all` and `CREATE INDEX IF NOT EXISTS`. Existing rows are not rewritten.

**Step 6B API:** `POST/GET /api/stock-opnames`, `GET /api/stock-opnames/{id}`, line `POST/PATCH/DELETE`. Snapshot `system_qty` at line-add. `difference` stays NULL. HQ write blocked (`forbid_company_kirim_write`). Number `OP-{count:06d}` (same style as `IN-`/`TR-`, not a numbering service).

**Step 6C UI:** list/create/detail, barcode+qidiruv add line, counted blur/Enter PATCH, difference preview only, delete with confirm. HQ create hidden. POSTED/CANCELLED read-only.

**Step 6D finalize:** `POST /api/stock-opnames/{id}/finalize`. OPEN only. All lines must have non-null `counted_qty` (>= 0). `difference = counted_qty - system_qty` (snapshot not re-taken). Apply `new_stock = current live Product.stock + difference` via `move_stock(kind=ADJUST, ref_type="opname", ref_id=opname.id)`. Zero difference skips `move_stock` but stores `line.difference = 0`. Negative resulting stock → 400 + full rollback. Atomic one commit; HQ `forbid_company_kirim_write`; CASHIER 403. Audit `stock.opname.finalize` only on success. UI: «Санашни якунлаш» on OPEN + stock perm, confirm, submit lock, reload POSTED read-only.

**Not in 6D:** cancel endpoint, warehouse, variants, new ledger/kind.

---

## 11. Low Stock Architecture

**Today: PARTIAL.**

- Field `products.min_stock`.
- Products UI marks row when `stock <= min_stock`.
- Dashboard `low_stock` (active, `min_stock > 0`, `stock <= min_stock`, limit 8).
- AI tool `get_low_stock_products` same filter.

**MISSING:** critical vs min, notifications, reorder suggestions, company-wide HQ view, `min_stock = 0` products never appear (by design of current query).

**Future:** keep `min_stock`; add optional `critical_stock`; `GET /api/products?low=1`; no Telegram/omnichannel in Phase 2. Do not build Smart Reorder (Layer 4).

---

## 12. Database Proposal

**Do not create tables in this step.** No Alembic unless Ahmad approves (live pattern is `ensure_schema` extras). Integer PKs stay.

### Keep (do not drop)

`products`, `categories`, `stock_ins`, `stock_in_items`, `stock_movements`, `stock_transfers`, `stock_transfer_items`, `sales`, `sale_items`.

### Additive only (future, ordered)

| Table / change | When | Notes |
|----------------|------|--------|
| Unique index `(company_id, store_id, barcode)` where barcode ≠ `''` | Product stabilization | Matches today’s app check |
| Optional unique `(company_id, store_id, sku)` where sku ≠ `''` | Same | Empty SKU remains allowed |
| `products.parent_id` or `style_id` + color/size | Variants **if approved** | POS still uses `product_id` |
| `brands` | Optional, after master fields | `manufacturer` can map into brand name |
| `warehouses` + `stock_balances` | Warehouse **if approved** | Backfill one warehouse/store |
| `stock_movements.warehouse_id` nullable | With warehouses | |
| `stock_adjustments` header | Dedicated adjust/opname | Or reuse movements + reason enum |
| `stock_opnames` + `stock_opname_lines` | **Step 6A created** | Schema only; post later via existing `move_stock` ADJUST |

**Do not** replace `products.stock` in the first migration. Dual-run: cache + movements. Later balances must reconcile to cache before cache is deprecated.

`product_variants` as a **separate sellable PK** is the high-risk option — last resort.

---

## 13. API Proposal

Use **existing** prefixes. Do not invent `/api/v1` in Phase 2 without approval.

| Later endpoint | Purpose | Auth |
|----------------|---------|------|
| Keep `/api/products` | Master + search | `products` |
| Keep `/api/pos/products` | Cashier search | `pos` |
| Keep `/api/stock-ins` | Kirim | `stock` + HQ guard |
| Keep `/api/transfers` | Store transfer | `stock` + HQ guard |
| Add `GET /api/stock-movements` | Ledger read | `stock` or `reports` |
| Add `POST /api/stock-adjustments` | Reasoned ADJUST | `stock` |
| Later `POST/GET /api/stock-opnames` | Count | `stock` |
| Later warehouse/variant routes | Only if approved | |

Every new route: JWT, `company_id` from DB user, `current_store()` or explicit store check, no cross-company `db.get` without compare.

Kirim/transfer: validate `qty > 0` (behavior fix, not a new module).

---

## 14. UI Proposal

**Remain (do not redesign):** Products page, Kirim page, Transfers page, POS scan, Cennik, dashboard low-stock widget, store cabinet hiding HQ kirim/transfer forms.

**Future improvements (not this step):**

- Product form: category, manufacturer/brand, SKU help, hide raw stock on edit in favor of Adjust/Opname.
- Products: server search, pagination, low-stock filter.
- New read-only **Stock history** (movement table).
- Adjust dialog: qty + reason (not PATCH stock field).
- Transfer: line items / detail (GET one transfer).
- Opname wizard later.
- No large POS redesign; POS keeps `product_id`.

---

## 15. Security Considerations

- Tenant: never drop `company_id` / `store_id` filters.
- HQ kirim guard: keep; do not let company cabinet write stock.
- STORE extra role: keep until Ahmad approves removal.
- Adjustment/opname/write-off: `stock` permission; CASHIER must not gain catalog stock writes.
- Audit: extend `audit_logs` for kirim, adjust, opname, write-off (kirim is a current gap).
- Transfer qty and stock-in qty must be positive server-side.
- Barcode unique index prevents race 409 bypass.
- No secrets in product payloads; no `Access-Control-Allow-Origin: *` with credentials.
- Variants/warehouses must not leak via `db.get` on integer IDs (IDOR).

---

## 16. Migration Strategy

```
OLD (now)
  products.stock cache + stock_movements + per-store product clones
        ↓
COMPATIBILITY (Phase 2 implementation, after approval)
  same tables; constraints; movement read API; dedicated adjust;
  Product remains POS sellable unit
        ↓
NEW ARCHITECTURE (later, approved slices)
  optional style grouping → optional default warehouse → balances
```

Rules:

- Do not DELETE products, movements, sales, stock_ins, transfers.
- Do not change sale_item `product_id` meaning.
- Existing `tax_total` / POS checkout must keep working (Phase 1).
- Opening/IN/SALE/RETURN/TRANSFER/ADJUST kinds stay.
- Backfill: unique barcodes; default warehouse rows only when warehouse work is approved.
- SQLite `ensure_schema` extras first; PostgreSQL-ready types (no SQLite-only features).

If a step needs a breaking API, stop and ask Ahmad.

---

## 17. Implementation Order

Master-doc preferred list started with variants and warehouses **before** using the existing ledger. **Live code requires a different order**, because:

1. `move_stock` + `stock_movements` already exist — do not rebuild a ledger (user rule: do not create a new ledger if equivalent exists).
2. Transfer already exists — harden, do not rewrite.
3. Variants and warehouses are **large** changes and would break POS/`product_id`/clone-by-barcode if done early.
4. Purchase Order is out of Phase 2.

**Recommended sequence (after this audit is approved):**

| # | Slice | Why first |
|---|--------|-----------|
| 1 | Product master stabilization | Fields/UI (category, manufacturer), barcode/SKU uniqueness in DB, pagination, no N+1 on category |
| 2 | SKU / barcode foundation | Unique indexes; POS/kirim scan stay Enter-exact; no variant table yet |
| 3 | Expose existing ledger (read API + Stock history UI) | Unblocks WHO/WHEN/WHAT without new tables |
| 4 | Dedicated adjustment (+ require qty>0 on kirim/transfer) | Reason/user/time/location=store/audit; stop using PATCH stock as the human adjust path |
| 5 | Transfer harden | GET detail, positive qty, keep atomic commit; status stays `DONE` until receive-flow is approved |
| 6 | Low stock | Filter/report on existing `min_stock`; optional `critical_stock` column |
| 7 | Write-off as `move_stock` kind | Thin, auditable OUT without sale |
| 8 | Stock opname | New docs posting **through** `move_stock` ADJUST |
| 9 | Inventory report (stock card) | Reads movements + cache; POS unchanged |
| 10 | POS integration check | Regression only: sale/return still call `move_stock` |
| 11 | **Product Variant** | **Only after Ahmad approval** — grouping on existing products |
| 12 | **Warehouse + stock_balances** | **Only after Ahmad approval** — default warehouse per store, cache remains |

Items 11–12 are last, not first, to protect working POS and multi-store clone-by-barcode.

**Out of this phase:** Loyalty, Marketing, Omnichannel, Forecast, Advanced AI, Purchase Order, Mobile inventory, UI redesign.

---

## Master architecture compatibility

Checked against `FIXEN-MASTER-ARCHITECTURE.md` and `.cursor/rules/fixen-master-architecture.mdc`.

| Topic | Conflict? | Handling |
|-------|-----------|----------|
| Vision Product→Variant→SKU | Live is flatter | Propose grouping later; **do not silently rewrite master** |
| Vision Warehouse | Missing | Design only; implement only with approval |
| `move_stock` / no dual stock write | Align | Keep as law |
| Tenant isolation | Align | Keep filters |
| STORE extra role | Delta | Keep |
| Unversioned `/api`, integer PKs, SQLite | Delta | Do not migrate in Phase 2 |
| Purchase as PO→Receive | Out of scope | Do not start PO |
| Large change approval | Align | Variants/warehouse gated |

No master document was edited in this step.

---

## Critical risks (current system)

1. **`products.stock` float cache** — rounding vs ledger; must stay single-writer (`move_stock`).
2. **No DB unique barcode** — race can duplicate barcodes in one store.
3. **Kirim/transfer item `qty > 0`** — **closed in Step 5** (`Field(gt=0)` + endpoint reject; no silent clamp).
4. **Transfer clones Product by barcode** — variants/warehouses cannot be naively layered; clone rule must be preserved or redesigned with approval.
5. **No movement list API** — audit questions exist in DB but not in product UI.
6. **PATCH product stock** — **closed in Step 4** (`data.pop("stock")`; human adjust is `POST /api/stock-adjustments`).
7. **Kirim has no `audit_logs` row.**
8. **`GET /products` unbounded** + category lazy load (N+1) + dashboard loads all period sale lines for profit — scale risk, not a current correctness bug.
9. **`LIKE %q%`** cannot use barcode index for search.
10. **HQ `current_store()` product writes** vs HQ kirim 403 — catalog vs inventory policy is inconsistent.

---





## Step 6D implementation status (2026-09-19)

Implemented (**finalize / atomic reconciliation only**):

- `POST /api/stock-opnames/{id}/finalize` — `require_perm("stock")` + `current_store()` + `forbid_company_kirim_write`. Cross-company/other store → 404. CASHIER → 403. HQ OWNER/ADMIN → 403.
- OPEN only; POSTED/CANCELLED → 409 (no duplicate ADJUST).
- All lines: `counted_qty` not NULL, not NaN, not negative (0 valid). Failure keeps OPEN, no stock/movement/audit.
- `difference = counted_qty - system_qty` persisted at finalize. Live apply: `move_stock` on **current** `Product.stock`, not a re-snapshot of `system_qty`.
- Non-zero difference only: `kind=ADJUST`, `ref_type="opname"`, `ref_id=opname.id`. Zero difference: no movement.
- Negative `live + difference` → 400 (`qoldiq yetarli emas`); entire transaction rollback (no partial stock, no line.difference, status stays OPEN).
- Success: `status=POSTED`, `posted_at=now`, audit `stock.opname.finalize`, one commit.
- UI: «Санашни якунлаш» when OPEN and not HQ cabinet; confirm; lock; reload.

Tests: `backend/tests/test_phase2_opname_finalize.py`.

Do **not** start cancel / Step 6E until review.

## Step 6C implementation status (2026-09-19)

Implemented (**UI only**; no finalize / cancel / stock writes):

- Nav: **Sanash** (`stock` perm; CASHIER hidden). Not in HQ-only filter — store users see it.
- List: `GET /api/stock-opnames` with page/limit and `X-Total-Count`.
- Create: `POST /api/stock-opnames` (hidden in company cabinet). 409 → «Бу дўконда очиқ саноқ мавжуд.»
- Detail: snapshot `system_qty` shown as-is. OPEN warning about live stock vs snapshot.
- Add line: `GET /api/products?q=` (limit 20, barcode first) then `POST .../lines`. Duplicate 409 mapped in UI.
- Counted: PATCH on blur/Enter; empty = not counted (—); 0 valid; negative rejected. Difference is **preview only**.
- Delete: confirm modal + `DELETE .../lines/{id}`.
- POSTED/CANCELLED: read-only, no finalize button.
- Submit lock + dirty counted confirm on nav.

Tests: backend suite unchanged semantically. No new E2E harness.

Do **not** start Step 6D until review.

## Step 6B implementation status (2026-09-19)

Implemented (**OPEN API only**; no UI / finalize / cancel / stock writes):

- `POST /api/stock-opnames` — `require_perm("stock")` + `current_store()` + `forbid_company_kirim_write`. `status=OPEN`, `number=OP-{count:06d}` (company count, same pattern as `IN-`/`TR-`). Duplicate OPEN → 409 (pre-check + DB partial unique). Audit `stock.opname.create`.
- `GET /api/stock-opnames` — company+store scoped, paginated (`page`/`limit`, default 50 max 200, `X-Total-Count`). Line count batched (no N+1). HQ may **read** current store, not company-wide edit.
- `GET /api/stock-opnames/{id}` — same isolation; cross-company/other store → 404. Lines include snapshot `system_qty` (not live stock), product name/SKU/barcode. Does **not** recompute snapshot.
- `POST /api/stock-opnames/{id}/lines` — OPEN only; product must be current company/store + active; `system_qty = Product.stock` at add time; `counted_qty` optional; `difference` NULL; duplicate product → 409.
- `PATCH .../lines/{line_id}` — OPEN only; `counted_qty` may be 0; negative rejected (422); `difference` not persisted (finalize later).
- `DELETE .../lines/{line_id}` — OPEN only. POSTED/CANCELLED line writes → 409.
- CASHIER 403. STORE only own store. No `move_stock`, no `products.stock` mutation, no `stock_movements`.

Not implemented: UI (6C), finalize/cancel (6D), variants, warehouses.

Tests: `backend/tests/test_phase2_opname_api.py`.

Step 6C UI follow-up: see section above.

## Step 6A implementation status (2026-09-19)

Implemented (**database foundation only**; no API / UI / finalize / cancel / stock writes):

- Tables: `stock_opnames`, `stock_opname_lines` (SQLAlchemy models + `ensure_schema` `create_all`).
- Tenant: every opname has `company_id` + `store_id`. Lines: `opname_id` + `product_id`.
- Status: `OPEN` / `POSTED` / `CANCELLED`. Timestamps: `created_at`, nullable `posted_at` / `cancelled_at`.
- Constraints (DB-level): partial unique `uq_stock_opnames_company_store_open` on `(company_id, store_id) WHERE status = 'OPEN'`; unique `uq_stock_opname_lines_opname_product` on `(opname_id, product_id)`.
- Indexes: `ix_stock_opnames_company_store_created` `(company_id, store_id, created_at)`; `ix_stock_opname_lines_opname_id` (`opname_id` also from FK `index=True`).
- FKs `NO ACTION` — no cascade that could delete historical documents.
- `number` column exists; numbering service **not** added.
- `move_stock`, `products.stock`, `stock_movements`, sales/returns/transfers/kirim/adjust APIs **unchanged**.
- No sample opname rows inserted into local `finup_pos.db`. After `ensure_schema`: products=29, stock_movements=43 (unchanged); opname tables empty.

Not implemented: API, UI, barcode/search, counting workflow, finalize ADJUST batch, cancel endpoint, variants, warehouses, `stock_balances`, new movement kind.

Tests: `backend/tests/test_phase2_opname_schema.py` (isolated in-memory SQLite; does not import `app.main`).

Step 6B API follow-up: see section above.

## Step 5 implementation status (2026-09-18)

Implemented (transfer harden only; status remains `DONE`; no receive/reject flow):

- `POST /api/transfers`: `qty` must be `> 0` (schema `Field(gt=0)` + endpoint). Zero/negative/malformed rejected (422/400). No clamp.
- Source stock pre-check; `move_stock` still refuses negative resulting stock. Insufficient → 400, no dest clone persisted (one commit at end; `get_db` rollback / session close).
- Two ledger rows in one transaction: `TRANSFER_OUT` (−qty at source) and `TRANSFER_IN` (+qty at dest), `ref_type=transfer`, `ref_id=stock_transfers.id`. Notes include destination/source store name.
- Dest product: match non-empty barcode, else non-empty SKU, else clone (empty barcode no longer matches a random empty-barcode dest row). Clone `stock=0` then `move_stock` IN — no `setattr` of qty.
- Isolation: src/dst `company_id == user.company_id` and `is_active`. Cross-company → 400. Product must belong to source store + same company (else 404). Inactive source product → 400.
- STORE: `from_store_id` must equal `user.store_id` (403 otherwise). Policy unchanged. OWNER/ADMIN/MANAGER/WAREHOUSE may transfer from any same-company store when not in HQ cabinet. HQ `forbid_company_kirim_write` still 403. CASHIER has no `stock` perm.
- `GET /api/stores` still `stores` perm (STORE remains 403). New `GET /api/transfer-stores` (`stock` perm) returns `{id,name,current}` for the transfer form only.
- `GET /api/transfers/{id}` company-scoped detail + lines. List adds `from_store_id`/`to_store_id` (backward compatible extra fields).
- Audit `transfer.create` payload: from/to store ids, number, items qty/product ids.
- Kirim: `StockInItemIn.qty` `Field(gt=0)` + endpoint reject; inactive product 400. No kirim audit row (pre-existing gap, not added here).
- Idempotency: **not supported** (sale keys only). Duplicate POST is a second transfer until stock runs out. UI confirm + submit lock.
- UI: cabinet-first HQ hide; preview remaining stock; confirm; STORE source locked; row click shows detail.

Not implemented: transfer draft/receive/reject, warehouse, variants, opname API/UI/finalize, write-off, PO.

Tests: `backend/tests/test_phase2_transfers.py`.

## Step 4 implementation status (2026-09-18)

Implemented (dedicated adjustment only; no second ledger):

- **API:** `POST /api/stock-adjustments`
- **Semantic (difference-based):** `new_stock = current_stock + qty` at transaction time (not a target overwrite). Example: 100 + (−3) = 97.
- **Body:** `{product_id, qty, reason}` (`qty` signed float; `reason` min 3 chars).
- **Writer:** `move_stock(..., kind="ADJUST", note=reason, ref_type="stock_adjust")` only. `products.stock` is not `setattr` from Product PATCH.
- **Product PATCH:** `stock` is popped and ignored. Master fields (name, SKU, barcode, prices, min_stock, …) still PATCH. Opening stock still `move_stock` OPENING on create.
- **Validation:** reject qty 0 / NaN; unknown or foreign product 404; inactive product 400; resulting stock < 0 → 400 (no silent clamp); malformed qty → 422.
- **Permissions:** existing `require_perm("stock")`. OWNER / ADMIN / MANAGER / WAREHOUSE allowed. CASHIER denied (no `stock` perm). Extra **STORE** role still has `stock` — policy preserved, not changed. HQ `forbid_company_kirim_write` is **not** applied (same as previous PATCH adjust / product writes via `current_store()`).
- **Isolation:** `company_id` + `current_store().id` must match the product. Cross-company and cross-store → 404.
- **Concurrency:** additive delta on current DB stock inside the request transaction; does not write a client-seen target.
- **Audit:** `write_audit` action `stock.adjust` (who). Ledger row explains what.
- **History:** ADJUST appears on `GET /api/stock-movements` immediately (signed qty, balance_after, note, user, date).
- **UI:** Products «Tuzatish» — current / difference / result preview, reason, confirm. Edit form still does not send stock.
- **Idempotency:** **not supported.** Sale `idempotency_key` is sale-table only. Two identical POSTs are two deltas (10+5+5=20). UI disables confirm after submit. Do not invent a second idempotency store.
- **DB:** no new tables/columns. Uses existing `stock_movements` + `audit_logs`.

Not implemented: variants, warehouse, stock_balances, opname, write-off, PO, kirim/transfer qty>0 harden (Step 5+).

Tests: `backend/tests/test_phase2_stock_adjust.py` plus PATCH/history updates.

## Step 3 implementation status (2026-09-18)

Implemented:

- Read-only `GET /api/stock-movements` on existing `stock_movements` (no second ledger).
- Filters: `product_id`, `kind`, `from`, `to`, `page`, `limit` (default 50, max 200).
- Auth: JWT + `stock` permission + `company_id` + `current_store()`. CASHIER has no `stock` perm.
- Product Tarix modal: current stock, signed qty, balance, user, kind, ref_type/ref_id.
- Index: `ix_stock_movements_company_store_created` on `(company_id, store_id, created_at)`.

Not implemented: variants, warehouse, opname, write-off, transfer receive/reject.

## Step 2 implementation status (2026-09-18)

Implemented (compatibility-first):

- Product form: category, manufacturer, SKU, barcode, min_stock, is_active. Opening stock on create only (`move_stock` OPENING). Edit does not send `stock`.
- Unique indexes (non-empty only): `uq_products_company_store_barcode`, `uq_products_company_store_sku` on `(company_id, store_id, col)`.
- Exact barcode tried first on `GET /api/products?q=` and `GET /api/pos/products?q=`.
- Pagination: `page` (default 1), `limit` (default 200, max 500). Response remains a JSON array. Headers `X-Total-Count`, `X-Page`, `X-Limit`.
- Category N+1: `joinedload(Product.category)`.
- Category assign: must belong to the same `company_id`.
- HQ policy unchanged: OWNER/ADMIN may write products via `current_store()`; kirim/transfer still 403 from company cabinet.

Not implemented (as required): variants, warehouse, stock_balances, opname, write-off, PO.

Local SQLite `backend/finup_pos.db` duplicate scan before index: SKU groups 0, barcode groups 0.

END OF PHASE 2 STEP 1 ARCHITECTURE (audit + proposal only).


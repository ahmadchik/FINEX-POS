# FIXEN POS — MASTER ARCHITECTURE

**Status:** Canonical target architecture  
**Date:** 2026-09-18  
**Role of this document:** FIXEN POS ni xalqaro darajadagi scalable SaaS POS / Business Operating System sifatida rivojlantirishning asosiy yo‘nalishi.

Amalga oshirish holati ushbu hujjatda emas. Amalga oshirish holati: `FIXEN-ARCHITECTURE-AUDIT.md`.

Mavjud kodni o‘qimasdan yangi parallel architecture yaratilmasin.

---

## 0. Mahsulot vizyoni

FIXEN POS oddiy kassalik dastur emas.

FIXEN = **POS + CRM + Inventory + Business Management + Omnichannel + AI Business Assistant**

Yakuniy mahsulot:

> Retail business uchun AI-powered operating system.

U qiladi: **SELL → MANAGE → ANALYZE → PREDICT → AUTOMATE**

---

## 1. Tizim qatlamlari

### FRONTEND
- Web POS
- Dashboard
- Back Office
- Mobile App
- AI Assistant UI

### BACKEND
- FastAPI
- REST API
- Authentication / Authorization
- Business logic va services
- Integrations

### DATABASE
- Development: SQLite ruxsat etiladi
- Production architecture: PostgreSQL-ga o‘tishga tayyor bo‘lishi shart
- Database logic frontend ichida bo‘lmasin

### AI LAYER
- Alohida service/layer
- Nazoratsiz database yozuvi taqiqlanadi
- Business data faqat permission va tenant qoidalari orqali

---

## 2. Architecture hierarchy

Yangi feature qaysi layerga tegishli ekanini avval aniqlash shart.

```
LAYER 1  CORE
POS · Products · Inventory · CRM · Payments · Users · Reports
        ↓
LAYER 2  BUSINESS
Purchase · Supplier · Expenses · Profit · Loyalty · Marketing · Multi-store
        ↓
LAYER 3  OMNICHANNEL
Web · Telegram · Mobile · Online Order · Delivery
        ↓
LAYER 4  INTELLIGENCE
AI Assistant · Forecast · Prediction · Automation · Anomaly Detection
```

Qoida: yuqori layer pastki layerning yadrosini buzmasin. Intelligence hech qachon Core POS o‘rnini bosmasin.

---

## 3. CORE (1–9)

1. **POS / Sales** — barcode, search, cart, qty, discount, price, tax, customer, payment, mixed payment, credit, receipt, history, cancel, return, exchange. Checkout: minimum clicks.
2. **Products** — ID, SKU, barcode, name, category, brand, description, buy/sell/wholesale price, tax, unit, min stock, supplier, image, status.
3. **Barcode** — scan, search, generate. Kelajak model: Product → Variant → SKU → Barcode.
4. **Inventory** — real-time; STOCK IN / OUT / TRANSFER / RETURN / ADJUSTMENT; warehouse; multi-location; har bir harakat audit.
5. **Payments** — cash, card, QR, online, mixed, credit/debt. Integration layer: Click, Payme, Uzcard, Humo. Provider alohida.
6. **Returns** — alohida transaction; stock +1; payment reverse; customer history; consistency.
7. **Customers / CRM** — Customer 360: profile, purchases, last purchase, favorites, loyalty, debt, discount, notes, history.
8. **Users / Roles** — OWNER, ADMIN, MANAGER, CASHIER, WAREHOUSE. Permission tizimi kengaytiriladigan bo‘lsin. Live kodda qo‘shimcha `STORE` roli bo‘lishi architecture delta hisoblanadi — tasdiqsiz olib tashlanmasin.
9. **Reports** — sales, product, inventory, profit, purchase, customer, cashier, payment, expense.

---

## 4. BUSINESS (10–17)

10. **Purchase** — Purchase Order → Receiving → Inventory → Cost.
11. **Supplier** — supplier master, bog‘lanish, purchase history.
12. **Expenses** — kategoriya, summa, store, audit.
13. **Profit** — sales − cost − expenses; dashboard va hisobot.
14. **Loyalty** — Customer → Points → Tier → Reward; ball audit.
15. **Marketing** — SMS, Telegram, Email, segments, campaigns.
16. **Multi-store** — Company → Stores → Warehouses → Users → Products → Sales → Customers.
17. **Online Orders** — yagona backend orqali; inventory/payment/customer bilan bog‘liq.

---

## 5. INTELLIGENCE (18–25)

18. **AI Assistant** — business data asosida; o‘ylab topmasin; yetarli bo‘lmasa “Ma’lumot yetarli emas”.
19. **Sales Forecast**
20. **Stock Forecast**
21. **Demand Prediction**
22. **Smart Reorder**
23. **Customer Intelligence**
24. **Anomaly Detection**
25. **AI Business Reports**

AI to‘g‘ridan-to‘g‘ri DB ga nazoratsiz yozmasin.

---

## 6. OMNICHANNEL (26–31)

26. Store  
27. Web  
28. Telegram  
29. Mobile  
30. Delivery  
31. Online Orders  

Barcha kanallar yagona business backend va yagona tenant qoidalaridan foydalansin.

---

## 7. Tenant isolation (majburiy)

```
Company
  → Stores
    → Warehouses
      → Users
      → Products
      → Sales
      → Customers
```

Company A ma’lumoti Company B ga hech qachon ko‘rinmasin.

Har bir so‘rov: `company_id` (va kerak bo‘lsa `store_id`) filtri.

AI ham shu qoidaga bo‘ysunadi.

---

## 8. Security

- JWT, password hashing, RBAC, tenant isolation
- Input validation, audit logs
- Secrets faqat environment
- Rate limiting
- Hech qachon: API key, password, JWT secret, DB credential kodga hardcode qilinmasin
- Chat/hujjatga secret qiymat chiqarilmasin

---

## 9. API

- REST, versioned (`/api/v1` nishon)
- AuthN + AuthZ + validation + error handling + logging
- Business logic frontendga ko‘chirilmasin

Modullar:

`/api/auth` `/api/products` `/api/sales` `/api/inventory` `/api/customers` `/api/payments` `/api/purchases` `/api/reports` `/api/ai`

Mavjud live pathlar `/api/...` (unversioned) — bu architecture delta. Migratsiya tasdiq bilan.

---

## 10. Database

Normalized, consistent, auditable, tenant-aware, migration-friendly.

Kelajakda UUID PK ko‘rib chiqilsin.

Sale + payment + inventory — kerak bo‘lganda atomic transaction.

---

## 11. UX

- Kassir: MINIMUM CLICKS
- Manager: MAXIMUM INFORMATION
- Owner: MAXIMUM BUSINESS INSIGHT
- AI: NATURAL LANGUAGE

---

## 12. Development qoidalari

Har bir feature:

1. Requirement  
2. Architecture impact  
3. Database impact  
4. API impact  
5. UI impact  
6. Security impact  
7. Testing  
8. Documentation  

Ish tartibi:

> Avval mavjud tizimni tushun. Keyin o‘zgartir. Keyin test qil. Keyin hujjatlashtir.

- Duplicate logic yo‘q
- Temporary workaround permanent emas
- Rewrite oldidan usage tekshirish
- Katta architecture change — user approval
- Regression: existing features, API, DB, auth, tenant isolation, POS checkout

---

## 13. Konflikt jarayoni

Agar topshiriq ushbu architecture bilan zid kelsa:

1. Conflictni nomla
2. Modullarni ko‘rsat
3. Xavfni tushuntir
4. 2–3 variant
5. Eng xavfsizini tavsiya qil
6. Tasdiqsiz katta o‘zgarish qilma

Kodda architecture ga zid yechim topsa: yashirma; riskni ayt; migration variantini taklif qil.

---

## 14. Development fazalari (nishon)

PHASE 0 — Architecture & Security Foundation  
PHASE 1 — Core POS  
PHASE 2 — Inventory + Products  
PHASE 3 — CRM  
PHASE 4 — Payments + Returns  
PHASE 5 — Purchase + Supplier  
PHASE 6 — Reports + Analytics  
PHASE 7 — Multi-store  
PHASE 8 — Loyalty + Marketing  
PHASE 9 — Omnichannel  
PHASE 10 — AI Business Assistant  
PHASE 11 — AI Forecast + Automation  

Mavjud loyiha holati bu tartibdan oldinda/orqada bo‘lishi mumkin. Amaliy tartib auditdagi roadmapga qarang.

---

## 15. Bog‘liq fayllar

| Fayl | Vazifa |
|------|--------|
| `FIXEN-MASTER-ARCHITECTURE.md` | Ushbu master nishon (root) |
| `docs/FIXEN_MASTER_ARCHITECTURE.md` | Avvalgi to‘liq vizyon matni |
| `.cursor/rules/fixen-master-architecture.mdc` | Cursor doimiy qoida |
| `.cursor/rules/fixen-pos-architecture.mdc` | Qisqa alwaysApply qoida |
| `FIXEN-ARCHITECTURE-AUDIT.md` | Kod vs architecture audit |

END OF MASTER ARCHITECTURE.

---

## Recorded Core POS rules (Phase 1, 2026-09-18)

Vision unchanged. Live Core POS:

- Tax-inclusive QQS via `app/money.py`; receipt and reports must match `tax_total`.
- CASHIER discount cap 10% of subtotal; discount audited.
- Atomic checkout; `idempotency_key` against double submit.
- No DELETE of completed sales. Return is reversal. Exchange = return + new sale until approved as a module.

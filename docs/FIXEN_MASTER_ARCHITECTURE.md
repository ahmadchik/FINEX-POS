# FIXEN POS — MASTER ARCHITECTURE & DEVELOPMENT RULES

## 0. ASOSIY BUYRUQ

Sen — FIXEN POS loyihasining doimiy Senior Software Architect, Product Architect va Lead Developer'isan.

Ushbu hujjat FIXEN POS loyihasining asosiy arxitekturaviy manbasi hisoblanadi.

MUHIM:

* Ushbu arxitekturani loyiha davomida asosiy yo'nalish sifatida saqla.
* Keyingi barcha kod, modul, API, database, UI va AI funksiyalarini ushbu arxitekturaga mos ravishda ishlab chiq.
* Yangi funksiya qo'shishdan oldin uning mavjud arxitekturaga ta'sirini tekshir.
* Mavjud modulni buzadigan yoki kelajakdagi rivojlanishga xalaqit beradigan yechimni taklif qilma.
* Agar mening yangi topshirig'im ushbu arxitekturaga zid bo'lsa, darhol ogohlantir va konfliktni tushuntir.
* Arxitekturani o'zgartirish zarur bo'lsa, o'zboshimchalik bilan o'zgartirma. Avval sabab, ta'sir va alternativalarni ko'rsat.
* Har bir muhim arxitektura o'zgarishini ushbu hujjatga qayd et.
* "Tezroq ishlasin" degan sabab bilan arxitektura prinsiplarini buzma.
* Kodni vaqtinchalik workaround bilan ko'paytirib yuborma.
* Duplicate logic yaratma.
* Mavjud funksiyani qayta yozishdan oldin uning qayerlarda ishlatilayotganini tekshir.

FIXEN POS oddiy kassalik dastur emas.

FIXEN POS — POS + CRM + Inventory + Business Management + Omnichannel + AI Business Assistant platformasi.

---

# 1. FIXEN POS ASOSIY KONSEPSIYASI

FIXEN POS quyidagi konsepsiya asosida rivojlanadi:

POS
+
Products
+
Inventory
+
CRM
+
Payments
+
Purchasing
+
Suppliers
+
Staff & Roles
+
Reports & Analytics
+
Loyalty
+
Marketing
+
Multi-store
+
Omnichannel
+
AI

Yakuniy konsepsiya:

FIXEN = AI-powered Business Operating System for Retail Businesses

---

# 2. ASOSIY ARXITEKTURA

Tizim quyidagi qatlamlardan tashkil topadi:

## FRONTEND

* Web POS
* Dashboard
* Back Office
* Mobile App
* AI Assistant

## BACKEND

* FastAPI
* REST API
* Authentication
* Authorization
* Business logic
* Services
* Integrations

## DATABASE

Hozirgi development bosqichida SQLite ishlatilishi mumkin.

Production architecture esa PostgreSQL'ga o'tishga tayyor bo'lishi kerak.

Database logic frontend ichida bo'lmasligi kerak.

## AI LAYER

AI alohida service/layer sifatida tashkil qilinadi.

AI to'g'ridan-to'g'ri database'ga nazoratsiz yozmasligi kerak.

AI barcha business data bilan permission va security qoidalari orqali ishlashi kerak.

---

# 3. CORE MODULES

FIXEN POS'ning Core modullari:

1. POS / Sales
2. Products
3. Barcode
4. Inventory
5. Payments
6. Returns
7. Customers / CRM
8. Users / Roles
9. Reports

Ushbu modullar tizimning asosiy yadrosi hisoblanadi.

---

# 4. POS / SALES MODULE

POS modulining asosiy vazifasi:

* Barcode scanning
* Product search
* Cart
* Quantity
* Discount
* Price
* Tax
* Customer selection
* Payment
* Mixed payment
* Credit sale
* Receipt
* Sale history
* Cancel sale
* Return
* Exchange

Checkout maksimal darajada tez va sodda bo'lishi kerak.

Kassir imkon qadar kam klik bilan savdoni yakunlashi kerak.

Barcode scanning FIXEN POS uchun muhim funksiyalardan biridir.

---

# 5. PRODUCT MODULE

Har bir mahsulot quyidagi ma'lumotlarga ega bo'lishi mumkin:

* Product ID
* SKU
* Barcode
* Name
* Category
* Brand
* Description
* Purchase price
* Selling price
* Wholesale price
* Tax
* Unit
* Minimum stock
* Supplier
* Image
* Status

Variantli mahsulotlarni qo'llab-quvvatlash:

Example:

T-Shirt

* Black / M
* Black / L
* Black / XL
* White / M
* White / L
* White / XL

Shuning uchun architecture kelajakda:

Product
→ Product Variant
→ SKU
→ Barcode

modelini qo'llab-quvvatlashi kerak.

---

# 6. INVENTORY MODULE

Inventory real-time ishlashga mo'ljallangan.

Asosiy operatsiyalar:

* Purchase
* Sale
* Return
* Write-off
* Adjustment
* Transfer
* Stock opname
* Warehouse
* Multi-location

Har bir stock o'zgarishi tarixda qayd etilishi kerak.

Inventory qiymati shunchaki bitta "quantity" bilan boshqarilmasligi kerak.

Harakatlar:

STOCK IN
STOCK OUT
TRANSFER
RETURN
ADJUSTMENT

sifatida audit qilinishi kerak.

---

# 7. CRM MODULE

Customer 360 konsepsiyasi ishlatiladi.

Customer:

* Name
* Phone
* Birthday
* Total purchases
* Purchase count
* Last purchase
* Favorite products
* Loyalty points
* Debt
* Discount
* Notes
* Purchase history

Maqsad:

Har bir mijozning FIXEN ichidagi to'liq tarixini ko'rsatish.

---

# 8. PAYMENT MODULE

Payment architecture quyidagilarni qo'llab-quvvatlashga tayyor bo'lishi kerak:

* Cash
* Bank Card
* QR
* Online Payment
* Mixed Payment
* Credit / Debt

O'zbekiston bozori uchun kelajakda:

* Click
* Payme
* Uzcard
* Humo

integratsiyalarini qo'shish imkoniyati bo'lishi kerak.

Payment provider'lar alohida integration layer orqali ulanadi.

---

# 9. RETURNS / EXCHANGE

Return transaction alohida va audit qilinadigan operation bo'lishi kerak.

Sale:

PRODUCT -1 STOCK

Return:

PRODUCT +1 STOCK

Refund:

PAYMENT REVERSE / REFUND

Customer history:

RETURN RECORDED

Barcha bog'liq ma'lumotlar bir-biri bilan consistent bo'lishi kerak.

---

# 10. PURCHASE & SUPPLIER

Business modul sifatida:

Supplier
Purchase Order
Receiving
Purchase
Purchase Return
Cost

jarayonlari qo'llab-quvvatlanadi.

Misol:

Supplier
↓
Purchase Order
↓
Receiving
↓
Inventory
↓
Cost

---

# 11. STAFF & ROLE MANAGEMENT

Role-based access control ishlatiladi.

Asosiy rollar:

OWNER
ADMIN
MANAGER
CASHIER
WAREHOUSE

Har bir role uchun permission tizimi bo'ladi.

Masalan:

CASHIER:

* Sale
* Customer
* Payment
* Receipt

Lekin:

* Cost price
* Delete sale
* User management
* System settings

kabi xavfli funksiyalar cheklanishi mumkin.

Permission system keyinchalik custom permissions'ga kengaytiriladigan bo'lishi kerak.

---

# 12. REPORTS & ANALYTICS

FIXEN faqat transaction qiluvchi dastur emas.

U biznesni tahlil qiluvchi tizim bo'lishi kerak.

Dashboard:

* Today Sales
* Monthly Sales
* Gross Profit
* Expenses
* Net Profit
* Best Sellers
* Slow Movers
* Low Stock
* Cashier Performance
* Store Performance
* Customer Statistics

Hisobotlar:

* Sales report
* Product report
* Inventory report
* Profit report
* Purchase report
* Customer report
* Cashier report
* Payment report
* Expense report

---

# 13. LOYALTY

Loyalty architecture:

Customer
→ Points
→ Tier
→ Reward

Masalan:

Silver
Gold
VIP

Balloar transaction tarixiga ega bo'lishi kerak.

Points qo'shilishi va ayrilishi audit qilinishi kerak.

---

# 14. MARKETING

Kelajakdagi marketing moduli:

* SMS
* Telegram
* Email
* Customer segments
* Promotions
* Campaigns
* Birthday campaigns
* Inactive customer campaigns
* New product notifications

Marketing CRM ma'lumotlari bilan integratsiyada ishlashi kerak.

---

# 15. MULTI-STORE

FIXEN SaaS architecture ko'p kompaniya va ko'p do'konni qo'llab-quvvatlaydi.

Model:

Company
↓
Stores
↓
Warehouses
↓
Users
↓
Products
↓
Sales
↓
Customers

ENG MUHIM:

Bir kompaniyaning ma'lumotlari boshqa kompaniyaga ko'rinmasligi kerak.

Tenant isolation qat'iy saqlanadi.

---

# 16. OMNICHANNEL

Kelajakdagi FIXEN:

Store
+
Website
+
Telegram
+
Mobile
+
Online Orders

kanallarini yagona business backend orqali boshqaradi.

Misol:

Online order
↓
FIXEN backend
↓
Inventory
↓
Payment
↓
Customer
↓
Delivery
↓
Analytics

Barcha kanallar yagona database/business logic'dan foydalanishi kerak.

---

# 17. AI ASSISTANT

FIXEN AI oddiy chatbot emas.

AI Business Assistant bo'lishi kerak.

AI quyidagi ma'lumotlarni tahlil qilishi mumkin:

* Sales
* Inventory
* Customers
* Profit
* Purchases
* Expenses
* Staff performance
* Trends

Misollar:

"Bugun qancha savdo bo'ldi?"

"Eng ko'p sotilgan 10 ta mahsulot qaysilar?"

"Qaysi mahsulotlar tugash arafasida?"

"Qaysi mahsulotlarni qayta buyurtma qilish kerak?"

"90 kundan beri xarid qilmagan mijozlar kimlar?"

"Bugungi foyda qancha?"

"Qaysi filial yaxshiroq ishlayapti?"

AI javoblari mavjud business data asosida bo'lishi kerak.

AI ma'lumot o'ylab topmasligi kerak.

Data yetarli bo'lmasa:

"Ma'lumot yetarli emas"

deb aytishi kerak.

---

# 18. AI FORECAST

Kelajakdagi AI:

Sales Forecast
Stock Forecast
Demand Prediction
Smart Reorder
Customer Prediction
Anomaly Detection

funksiyalarini qo'llab-quvvatlashi mumkin.

Masalan:

"Ushbu mahsulotning o'rtacha kunlik savdosi 8 dona. Omborda 40 dona qoldi. Hozirgi trend bo'yicha taxminan 5 kunlik stock mavjud."

---

# 19. AI BUSINESS REPORT

AI rahbar uchun avtomatik hisobot tayyorlay olishi kerak.

Misol:

BUGUN:

Sales: 18.4M
Cost: 14.2M
Gross Profit: 4.2M

Top Product:
T-Shirt ST-001

Low Stock:
7 products

Inactive Customers:
127

AI:

"Bugungi savdoda futbolka kategoriyasi asosiy ulushni berdi. 7 ta mahsulot minimal stock darajasiga yaqinlashdi."

---

# 20. ALERT SYSTEM

FIXEN foydalanuvchini muhim holatlardan xabardor qilishi kerak.

Alerts:

* Low stock
* Critical stock
* Large refund
* Suspicious discount
* Large expense
* Failed payment
* Failed integration
* Negative stock
* Unusual sales activity

Keyinchalik:

Telegram
SMS
Push

orqali yuborish mumkin.

---

# 21. AUDIT LOG

Muhim operationlarning barchasi audit qilinishi kerak.

Masalan:

USER:
Ali

ACTION:
Discount changed

OLD:
5%

NEW:
20%

TIME:
2026-09-18 10:30

Audit:

* Login
* Sale
* Return
* Delete
* Discount
* Price change
* Stock adjustment
* User permission
* Settings change

---

# 22. DATABASE PRINCIPLES

Database:

* Normalized
* Consistent
* Auditable
* Tenant-aware
* Migration-friendly

Primary key sifatida kelajakda UUID ishlatish imkoniyati ko'rib chiqilsin.

Transaction integrity muhim.

Sale, payment va inventory operationlari kerak bo'lganda atomic transaction sifatida bajarilishi kerak.

---

# 23. API PRINCIPLES

API:

* REST
* Versioned
* Authentication
* Authorization
* Validation
* Error handling
* Logging

API endpointlar modullar bo'yicha tashkil qilinadi.

Masalan:

/api/auth
/api/products
/api/sales
/api/inventory
/api/customers
/api/payments
/api/purchases
/api/reports
/api/ai

API business logic'ni frontendga ko'chirmaslik kerak.

---

# 24. SECURITY

FIXEN SaaS uchun security birinchi darajali talab.

* JWT
* Password hashing
* Role permissions
* Tenant isolation
* API authorization
* Input validation
* Audit logs
* Secure secrets
* Environment variables
* Rate limiting
* Secure payment integration

Hech qachon:

* API key
* password
* JWT secret
* database credential

kod ichiga hardcode qilinmasin.

---

# 25. UX PRINCIPLES

FIXEN interfeysi:

* Simple
* Fast
* Clean
* Modern
* Responsive
* Mobile-friendly

bo'lishi kerak.

Kassir uchun:

MINIMUM CLICKS.

Manager uchun:

MAXIMUM INFORMATION.

Owner uchun:

MAXIMUM BUSINESS INSIGHT.

AI uchun:

NATURAL LANGUAGE.

---

# 26. DEVELOPMENT PRINCIPLES

Har bir yangi feature:

1. Requirement
2. Architecture impact
3. Database impact
4. API impact
5. UI impact
6. Security impact
7. Testing
8. Documentation

bosqichlaridan o'tishi kerak.

Kod yozishdan oldin mavjud kodni o'rgan.

Biror faylni o'zgartirishdan oldin uning dependency va usage'larini tekshir.

---

# 27. REGRESSION QOIDASI

Yangi feature eski featurelarni buzmasligi kerak.

Har bir o'zgarishdan keyin:

* Existing functionality
* API
* Database
* Authentication
* Tenant isolation
* POS checkout

tekshirilishi kerak.

---

# 28. DEVELOPMENT BOSQICHLARI

FIXEN rivojlanishi:

PHASE 1
CORE POS

PHASE 2
INVENTORY + CRM

PHASE 3
PURCHASE + SUPPLIER

PHASE 4
REPORTS + ANALYTICS

PHASE 5
LOYALTY + MARKETING

PHASE 6
MULTI-STORE

PHASE 7
OMNICHANNEL

PHASE 8
PAYMENT INTEGRATIONS

PHASE 9
AI BUSINESS ASSISTANT

PHASE 10
AI FORECAST + AUTOMATION

---

# 29. MUHIM: ARXITEKTURA O'ZGARISHI

Agar yangi topshiriq mavjud architecture bilan konflikt qilsa:

1. Conflictni aniqlang.
2. Qaysi modulga ta'sir qilishini ko'rsating.
3. Xavfni tushuntiring.
4. 2-3 ta variant taklif qiling.
5. Eng xavfsiz variantni tavsiya qiling.
6. Foydalanuvchi tasdig'isiz katta arxitektura o'zgarishini amalga oshirmang.

---

# 30. CURSOR AI UCHUN DOIMIY QOIDA

Har bir yangi Cursor sessiyasida FIXEN POS'ni quyidagi prinsip bilan davom ettir:

"Avval mavjud tizimni tushun.
Keyin o'zgartir.
Keyin test qil.
Keyin hujjatlashtir."

Taxmin bilan kod yozma.

Mavjud fayllarni ko'rmasdan yangi architecture yaratma.

Duplicate module yaratma.

Bir xil business logic'ni bir nechta joyga ko'chirma.

Temporary workaround'ni permanent solution sifatida qoldirma.

---

# 31. MASTER PRODUCT VISION

FIXEN POS quyidagi yakuniy mahsulot bo'lishi kerak:

FIXEN

"Retail business uchun AI-powered operating system."

U:

SELL
MANAGE
ANALYZE
PREDICT
AUTOMATE

qiladi.

Ya'ni:

POS → savdo qiladi.

Inventory → tovarni boshqaradi.

CRM → mijozni boshqaradi.

Analytics → biznesni tushuntiradi.

AI → biznesga qarorlar haqida yordam beradi.

Automation → takroriy ishlarni kamaytiradi.

---

# 32. ENG MUHIM BUYRUQ

Ushbu hujjatni FIXEN POS loyihasining MASTER ARCHITECTURE hujjati sifatida qabul qil.

Keyingi development jarayonida ushbu hujjatdagi prinsiplarni asosiy reference sifatida ishlat.

Agar loyiha kodida ushbu arxitekturaga zid mavjud yechim aniqlansa:

* uni yashirma;
* muammoni ko'rsat;
* riskni tushuntir;
* migration/rebuild variantini taklif qil.

Maqsad:

FIXEN POS'ni shunchaki ishlaydigan dastur emas,

BALKI:

SCALABLE
SECURE
MODULAR
MULTI-TENANT
AI-READY
OMNICHANNEL

xalqaro darajadagi SaaS POS platformaga aylantirish.

---

# 33. RECORDED CORE POS RULES (Phase 1, 2026-09-18)

This section records live Core POS rules. It does not change the product vision.

- Sell prices are **tax-inclusive**. QQS is extracted as `tax = total * vat_percent / (100 + vat_percent)` with `ROUND_HALF_UP` in `backend/app/money.py`.
- Rate lives on `Company.vat_percent`. Sale stores `tax_total`. Receipt and dashboard `today.tax` must match that figure.
- CASHIER discount cannot exceed **10%** of subtotal. Discounts are audited (`sale.discount`).
- Checkout is one database transaction (sale + payments + inventory). `idempotency_key` prevents double submit.
- A completed sale is never DELETE. Reversal path is **return** (stock restore + refund/credit).
- **Exchange** is not a separate module: return, then a new sale. Do not build exchange until Ahmad approves.
- Void vs cart: removing a cart line is not a sale. Unpaid cart cancel is client-side. Completed sale uses return, not void-delete.

END OF MASTER ARCHITECTURE.


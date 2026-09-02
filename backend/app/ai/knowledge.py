from __future__ import annotations

import re
from functools import lru_cache

# Knowledge is derived from the live FINEX POS UI (app.js) and HTTPException texts.
# Keep articles actionable: menu name + steps, not generic POS advice.

ARTICLES: list[dict] = [
    {
        "id": "products-add",
        "pages": ["products"],
        "tags": ["tovar", "mahsulot", "qo'sh", "qosh", "yangi tovar", "barcode", "shtrix"],
        "title": "Yangi tovar qo'shish",
        "body": (
            "Chap menyudan **Tovarlar** ni oching.\n"
            "Yuqoridagi sariq formaga: Nomi, Barcode (majburiy), Sotuv narxi ni yozing. "
            "Ixtiyoriy: SKU, xarid narxi, qoldiq, min qoldiq, birlik (standart: dona).\n"
            "**Qo'shish** tugmasi tovarni joriy do'konga yozadi.\n"
            "Tahrirlash: qatordagi **Tahrir** — maydonlar to'ladi, yana Qo'shish saqlaydi.\n"
            "Agar 'Bu barcode allaqachon bor' chiqsa — boshqa shtrix-kod qo'ying yoki mavjud tovarni tahrirlang."
        ),
    },
    {
        "id": "products-barcode",
        "pages": ["products", "pos", "stock"],
        "tags": ["barcode", "shtrix", "skaner", "cennik"],
        "title": "Shtrix-kod (barcode)",
        "body": (
            "Tovar qo'shayotganda **Barcode** maydoniga skaner yoki qo'lda kod yoziladi — majburiy.\n"
            "POS va Kirim oynalarida qidiruv/skaner shu kod bo'yicha topadi.\n"
            "Cennik chop etish: Tovarlar jadvalida **Cennik** — 58x30 mm termoetiketka, JsBarcode CODE128.\n"
            "Kod takrorlansa server 409 qaytaradi."
        ),
    },
    {
        "id": "pos-sale",
        "pages": ["pos"],
        "tags": ["sotuv", "savdo", "pos", "kassa", "to'lov", "tolov", "chek"],
        "title": "Sotuvni amalga oshirish",
        "body": (
            "Menyudan **POS** ni oching. Qidirish/barcode maydoniga yozing yoki skanerlang, tovarni bosing — savatga tushadi.\n"
            "Miqdor, chegirma, mijoz (ixtiyoriy), naqd/karta/Click-Payme summalarini kiriting. **To'lov**.\n"
            "Qarzga savdo: mijoz tanlang + 'Qarzga' belgilang.\n"
            "Obuna tugagan bo'lsa savdo yopiladi (402) — Sozlamalar/Billing.\n"
            "Kassir smena ochiq bo'lishi kerak: 'Avval kassa smenasini oching'.\n"
            "Qoldiq yetmasa: '{nom}: qoldiq yetarli emas' — avval **Kirim** qiling."
        ),
    },
    {
        "id": "pos-shift",
        "pages": ["pos", "cash"],
        "tags": ["smena", "kassa smena", "ochish", "yopish"],
        "title": "Kassa smenasi",
        "body": (
            "POS tepasida smena holati. Yopiq bo'lsa **Smena ochish**, ochiq bo'lsa **Smena yopish**.\n"
            "Savdo (CASHIER/OWNER/ADMIN/MANAGER, cash ruxsati) smena ochiq bo'lganda yoziladi.\n"
            "Allaqachon ochiq smena qayta ochilmaydi."
        ),
    },
    {
        "id": "stock-in",
        "pages": ["stock"],
        "tags": ["kirim", "ombor", "qoldiq", "zahira", "sklad"],
        "title": "Ombor kirimi va qoldiq",
        "body": (
            "Qoldiq **Tovarlar** jadvalida (Qoldiq ustuni, min dan past qizil).\n"
            "Boshqaruv panelida **Kam qoldiq** bloki bor (reports ruxsati).\n"
            "Kirim: menyu **Kirim**. Yetkazuvchi, barcode yoki mahsulot, miqdor, xarid narxi → **Qator qo'shish** → **Kirim qilish**.\n"
            "Qatorlar yo'q bo'lsa saqlanmaydi. Tarixdan hujjatni bosib detallarni ko'rasiz."
        ),
    },
    {
        "id": "returns",
        "pages": ["sales"],
        "tags": ["qaytarish", "vozvrat", "refund", "chek"],
        "title": "Tovarni qaytarish",
        "body": (
            "Menyudan **Savdolar** (yoki cheklar ro'yxati). Chekni oching.\n"
            "Qaytarish faqat **manager/admin/owner** da bor — kassirga 403: 'Qaytarish uchun manager/admin kerak'.\n"
            "Qator bo'yicha miqdor, avval qaytarilganidan oshirmaslik. Qoldiq va kassa teskari yoziladi."
        ),
    },
    {
        "id": "reports",
        "pages": ["dashboard", "hisobotlar"],
        "tags": ["hisobot", "excel", "dashboard", "foyda", "statistika"],
        "title": "Hisobot chiqarish",
        "body": (
            "Boshqaruv paneli: bugungi savdo, cheklar, foyda, kassa, top tovarlar, kam qoldiq.\n"
            "**Hisobotlar**: davr filtri, analitika, **Excel** yuklab olish (Finex_Hisobot_template).\n"
            "Kassirda reports ruxsati yo'q — dashboard o'rniga POS ochiladi."
        ),
    },
    {
        "id": "cash-expenses",
        "pages": ["cash", "expenses"],
        "tags": ["kassa", "naqd", "xarajat", "chiqim", "kirim pul"],
        "title": "Kassa va xarajatlar",
        "body": (
            "**Kassa**: naqd kirim/chiqim, izoh majburiy, chiqimda kassada yetarli naqd bo'lishi kerak.\n"
            "**Xarajatlar**: kategoriya, summa, izoh — do'kon bo'yicha."
        ),
    },
    {
        "id": "customers",
        "pages": ["customers"],
        "tags": ["mijoz", "qarz", "kredit", "debt"],
        "title": "Mijozlar va qarz kitobi",
        "body": (
            "**Mijozlar** da qo'shish, qarz, limit. POS da mijoz tanlab qarzga sotish mumkin.\n"
            "Limit oshsa: 'Mijoz kredit limiti oshdi'. Qarz to'lash: mijoz kartochkasida to'lov."
        ),
    },
    {
        "id": "transfers-stores",
        "pages": ["transfers", "stores"],
        "tags": ["transfer", "filial", "do'kon", "dokon", "ko'chirish"],
        "title": "Do'konlar va transfer",
        "body": (
            "Bir nechta do'kon (tarif limiti). Chapda do'kon select — almashtirish.\n"
            "**Transfer**: qaysi do'kondan qaysisiga, tovar va miqdor. Bir xil do'kon mumkin emas. "
            "Tarif do'kon sonini cheklashi mumkin (402)."
        ),
    },
    {
        "id": "staff-roles",
        "pages": ["staff"],
        "tags": ["xodim", "rol", "ruxsat", "kassir", "admin", "omborchi"],
        "title": "Xodimlar va rollar",
        "body": (
            "OWNER va ADMIN: barcha menyu (pos, products, stock, cash, reports, staff, settings, customers, stores, suppliers, billing).\n"
            "MANAGER: pos, products, stock, cash, reports, customers, suppliers (qaytarish mumkin).\n"
            "CASHIER: pos, cash, customers.\n"
            "WAREHOUSE: products, stock, suppliers.\n"
            "Egasi tahrirlanmaydi/o'chirilmaydi. Tarif user limitidan oshsa 402."
        ),
    },
    {
        "id": "settings-billing",
        "pages": ["settings"],
        "tags": ["sozlama", "billing", "tarif", "obuna", "to'lov", "click", "payme"],
        "title": "Sozlamalar va obuna",
        "body": (
            "Sozlamalar: kompaniya nomi, valyuta, QQS, til.\n"
            "Billing: FREE 30 kun, PRO / ENTERPRISE / VIP. Click/Payme yoki Demo to'lov.\n"
            "Obuna tugasa savdo 402: 'Obuna tugagan. Billing orqali to'lang.' — Sozlamalar pastidagi Billing."
        ),
    },
    {
        "id": "nav-overview",
        "pages": ["dashboard", "home"],
        "tags": ["meny", "qayer", "qanday och", "interfeys", "yordam"],
        "title": "Asosiy menyu",
        "body": (
            "Chap panel (ruxsatga qarab): Boshqaruv, Hisobotlar, POS, Tovarlar, Kirim, Transfer, "
            "Savdolar, Mijozlar, Kassa, Xarajatlar, Yetkazuvchilar, Do'konlar, Xodimlar, Sozlamalar.\n"
            "Pastda til: uz / ru / en. Do'kon select — joriy filial."
        ),
    },
]

ERROR_HINTS: list[dict] = [
    {"match": "qoldiq yetarli emas", "hint": "Savatdagi miqdor ombordagi qoldiqdan katta. Tovarlar/Kirim orqali qoldiqni oshiring yoki savat miqdorini kamaytiring."},
    {"match": "Avval kassa smenasini oching", "hint": "POS tepasida smena yopiq. 'Smena ochish' ni bosing, keyin To'lov."},
    {"match": "Obuna tugagan", "hint": "Sozlamalar → Billing. Tarif to'lang yoki demo to'lov. PAST_DUE/SUSPENDED da savdo yozilmaydi."},
    {"match": "Savat bo'sh", "hint": "Avval barcode/qidiruvdan tovar qo'shing, keyin To'lov."},
    {"match": "To'lov summasi yetarli emas", "hint": "Naqd+karta+online jami (qarzga bo'lmasa) chek summasidan kam. Summalarni to'ldiring yoki Qarzga ni belgilang."},
    {"match": "Mijoz kredit limiti oshdi", "hint": "Mijozlar da kredit limitini oshiring yoki qarzni undiring, yoki qarzga savdoni olib tashlang."},
    {"match": "Qaytarish uchun manager/admin kerak", "hint": "Kassir qaytara olmaydi. OWNER/ADMIN/MANAGER bilan kiring."},
    {"match": "Bu barcode allaqachon bor", "hint": "Shtrix-kod band. Boshqa kod yozing yoki shu kodli tovarni Tahrir qiling."},
    {"match": "Ruxsat yo'q", "hint": "Bu menyu sizning rolingizda yopiq. Do'kon egasidan ruxsat so'rang."},
    {"match": "Kassada yetarli naqd yo'q", "hint": "Chiqim/qaytarish uchun kassada naqd yetarli emas. Avval naqd kirim qiling."},
    {"match": "Do'kon topilmadi", "hint": "Filial yo'q yoki nofaol. Do'konlar bo'limidan do'kon oching/tanlang."},
    {"match": "Authentication required", "hint": "Qayta kiring. Token muddati tugagan bo'lishi mumkin (JWT soatlar cheklangan)."},
    {"match": "Login yoki parol noto'g'ri", "hint": "Login/parolni tekshiring. Platform egasi #/platform dan boshqa forma."},
    {"match": "Juda ko'p urinish", "hint": "Rate limit. Biroz kuting, keyin qayta urinib ko'ring."},
    {"match": "Tarif limiti", "hint": "Do'kon yoki xodim soni tarifga to'lgan. Billingdan tarifni yangilang."},
]


# Uzbek Cyrillic -> Latin so retrieve matches UI/KB (Latin menus).
_CYR = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ж": "j", "з": "z",
    "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p",
    "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "x", "ц": "s",
    "ъ": "", "ь": "", "э": "e", "ў": "o", "қ": "q", "ғ": "g", "ҳ": "h",
    "ё": "e", "ю": "yu", "я": "ya", "ч": "c", "ш": "sh",
})


def _norm(s: str) -> str:
    x = (s or "").lower().replace("‘", "'").replace("’", "'")
    x = x.translate(_CYR)
    return re.sub(r"\s+", " ", x)


def retrieve(question: str, page: str = "", last_error_message: str = "", limit: int = 4) -> list[dict]:
    q = _norm(question)
    tokens = set(re.findall(r"[a-zA-Z0-9_']+|[\u0400-\u04FF]+", q))
    scored: list[tuple[float, dict]] = []
    for art in ARTICLES:
        score = 0.0
        if page and page in art["pages"]:
            score += 3.0
        title = _norm(art["title"])
        tags = " ".join(art["tags"])
        if q and q in _norm(art["body"]):
            score += 2.0
        for t in art["tags"]:
            if t in q:
                score += 2.5
        for tok in tokens:
            if len(tok) < 3:
                continue
            if tok in title or tok in tags or tok in _norm(art["body"]):
                score += 0.4
        if score > 0:
            scored.append((score, art))
    scored.sort(key=lambda x: x[0], reverse=True)
    picked = [a for _, a in scored[:limit]]
    if not picked and page:
        picked = [a for a in ARTICLES if page in a["pages"]][:2]
    if not picked:
        picked = [a for a in ARTICLES if a["id"] == "nav-overview"]
    return picked


def diagnose_error(message: str) -> str:
    msg = message or ""
    low = msg.lower()
    for row in ERROR_HINTS:
        if row["match"].lower() in low:
            return f"{msg}\n\n{row['hint']}"
    return ""


@lru_cache(maxsize=1)
def kb_system_block() -> str:
    parts = []
    for a in ARTICLES:
        parts.append(f"### {a['title']}\n{a['body']}")
    return "\n\n".join(parts)

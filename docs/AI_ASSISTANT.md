# FINEX POS AI Assistant

End-user yordamchi. Cursor Agent / developer workflow emas.
Birinchi versiya: tushuntirish, diagnostika, tavsiya. Kod/schema/server amallarini bajarmaydi.

## Architecture

User (POS UI)
  -> POST /api/ai/chat (JWT)
  -> sanitize + page/role/error context (whitelist)
  -> Knowledge Base retrieve
  -> AI Provider (OpenAI-compatible) yoki Fallback (KB)
  -> javob + SQLite history

Provider abstraction: `app/ai/providers/`
- `OpenAICompatProvider` — OpenAI, Groq, OpenRouter (`AI_BASE_URL` + `AI_API_KEY`)
- `FallbackProvider` — kalit yo'q yoki API xato bo'lsa, Knowledge Base

Frontend kalit ko'rmaydi. Barcha chaqiruvlar backend orqali.

## Setup (local)

1. `backend/.env` yarating (`.env.example` dan).
2. Ixtiyoriy: `AI_API_KEY` qo'ying. Bo'sh qolsa ham Assistant ishlaydi (KB fallback).
3. `python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001`
4. Kabinetga kiring. O'ng pastki **AI** tugmasi.

Production/server deploy bu hujjat bilan qilinmaydi.

## Environment variables

| O'zgaruvchi | Default | Ma'no |
|---|---|---|
| AI_ENABLED | true | false = faqat KB fallback matni |
| AI_PROVIDER | openai | `openai` yoki `none` |
| AI_API_KEY | (bo'sh) | Backend only |
| AI_BASE_URL | https://api.openai.com/v1 | Compatible API |
| AI_MODEL | gpt-4o-mini | Model nomi |
| AI_MAX_TOKENS | 800 | Javob limiti |
| AI_TIMEOUT_SEC | 25 | HTTP timeout |
| AI_MAX_HISTORY | 12 | Promptga kiradigan oldingi xabarlar |
| AI_MAX_MESSAGE_CHARS | 2000 | User xabar kesish |
| AI_RATE_LIMIT | 30 | User uchun so'rov soni |
| AI_RATE_WINDOW | 3600 | Rate limit oynasi (soniya) |
| AI_TEMPERATURE | 0.3 | Sampling |

## Knowledge Base

Kod: `backend/app/ai/knowledge.py` (`ARTICLES`, `ERROR_HINTS`).
Manba: haqiqiy menyu (`app.js`) va `HTTPException` matnlari.

Maqolalar: tovar, barcode, POS, smena, kirim, qaytarish, hisobot, kassa, mijoz, transfer, rollar, billing.

## API

Barchasi `Authorization: Bearer <user JWT>` talab qiladi.

- `GET /api/ai/status` — provider nomi, online/fallback (secret yo'q)
- `POST /api/ai/chat` — `{ "message", "context": { "page", "last_error" } }`
- `GET /api/ai/history`
- `DELETE /api/ai/history`
- `POST /api/ai/report` — qoniqarsiz javob / xato haqida xabar

Context whitelist: page, role (serverdan), plan, company_status, writable, last_error.status/message/path.
Token, parol, API key, boshqa tenant ma'lumoti yuborilmaydi.

## Security

- JWT `get_current_user`
- Rate limit `ai:{user_id}`
- Redact: api_key/password/token/JWT
- Prompt injection pattern rad etiladi
- System prompt: sirni ochma, kodni o'zgartirma
- Log: user id, page, latency, provider, xato turi — to'liq biznes matn emas
- History user + company bilan bog'langan

## Database

Yangi jadvallar (mavjud jadvallar o'zgarmaydi):

- `ai_conversations`
- `ai_messages`
- `ai_bug_reports`

`ensure_schema()` / `create_all` lokal SQLite da yaratadi.

## Testing

```bash
cd backend
python -m pip install pytest httpx
python -m pytest tests/test_ai_knowledge.py tests/test_ai_api.py -q
```

Senariylar: savol, KB javob, 401, 422, rol, page context, xato diagnostikasi, history, report, secret yo'qligi.

## Roadmap

- Telegram/email xabarnoma
- Action tools (faqat ruxsat bilan)
- Prompt cache
- Platform Inbox da `ai_bug_reports` ko'rinishi
- Streaming javob

## Deployment checklist (hozir bajarilmasin)

- `AI_API_KEY` ni server `.env` ga qo'yish
- `AI_MODEL` / limitlarni belgilash
- HTTPS orqasida API
- Platform parolini default dan almashtirish


## Model vs Knowledge Base (2026-09)

AI_API_KEY bo'sh bo'lsa chat **503** qaytaradi — KB ni tayyor javob qilib yubormaydi.
KB `retrieve()` orqali 1–2 maqola kontekst sifatida modelga ketadi.
Fallback dump o'chirilgan.

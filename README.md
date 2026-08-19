# FINEX POS

Кичик ва ўрта бизнес учун **савдо, омбор ва касса** SaaS платформаси.

FINEX оиласи:
- **FINEX-CRM** — тўқимачилик ишлаб чиқариш
- **FINEX POS** — савдо дўкони (бу лойиҳа)

## MVP (1-босқич)

Рўйхатдан ўтиш → компания + дўкон → товарлар → кирим → POS савдо → касса → ҳисобот.

Кейинги босқичлар: кўп дўкон, offline-sync, Click/Payme, Telegram, AI.

## Ишга тушириш

```bash
cd FINUP-POS/backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
```

- Web: http://127.0.0.1:8001
- API docs: http://127.0.0.1:8001/docs

## Demo

Рўйхатдан ўтинг — биринчи дўкон ва намуна товарлар автоматик яратилади.

from __future__ import annotations

from ..knowledge import diagnose_error, retrieve
from .base import ChatResult


class FallbackProvider:
    name = "fallback"

    def complete(self, messages: list[dict], *, max_tokens: int = 800, temperature: float = 0.3, timeout: float = 25) -> ChatResult:
        user = ""
        page = ""
        err = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                user = m.get("content") or ""
                break
        for m in messages:
            if m.get("role") != "system":
                continue
            c = m.get("content") or ""
            if "page=" in c:
                for part in c.replace("{", " ").replace("}", " ").split():
                    if part.startswith("page="):
                        page = part.split("=", 1)[-1].strip(",")
            if "Xato diagnostikasi" in c:
                err = c
        articles = retrieve(user, page=page)
        diag = diagnose_error(user)
        if not diag and err:
            diag = err
        chunks = []
        if diag:
            chunks.append(diag)
        for a in articles:
            chunks.append("**" + a["title"] + "**\n" + a["body"])
        if not chunks:
            chunks.append(
                "Hozir tashqi AI ulanmagan. Chap menyudagi bo'lim nomi bilan savol bering "
                "(Tovarlar, POS, Kirim, Hisobotlar)."
            )
        text = "\n\n".join(chunks)
        if max_tokens:
            text = text[: max(400, max_tokens * 4)]
        return ChatResult(text=text, provider=self.name, model="knowledge-base", fallback=True)

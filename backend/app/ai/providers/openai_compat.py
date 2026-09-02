from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from .base import ChatResult


class OpenAICompatProvider:
    """OpenAI Chat Completions API (also Groq/OpenRouter if base_url + key match)."""

    name = "openai"

    def __init__(self, api_key: str, base_url: str, model: str):
        self.api_key = api_key
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.model = model or "gpt-4o-mini"

    def complete(self, messages: list[dict], *, max_tokens: int, temperature: float, timeout: float) -> ChatResult:
        url = self.base_url + "/chat/completions"
        payload = {
            "model": self.model,
            "messages": [{"role": m["role"], "content": m["content"]} for m in messages if m.get("role") in ("system", "user", "assistant")],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.api_key,
            },
        )
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:400]
            raise RuntimeError(f"AI HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError("AI tarmoq xatosi") from exc
        latency = int((time.perf_counter() - t0) * 1000)
        choice = (raw.get("choices") or [{}])[0]
        text = ((choice.get("message") or {}).get("content") or "").strip()
        usage = raw.get("usage") or {}
        if not text:
            raise RuntimeError("AI bo'sh javob qaytardi")
        return ChatResult(
            text=text,
            provider=self.name,
            model=str(raw.get("model") or self.model),
            latency_ms=latency,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
        )

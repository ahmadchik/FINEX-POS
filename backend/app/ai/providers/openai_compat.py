from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from .base import ChatResult


def parse_openai_tool_calls(message: dict | None) -> list[dict]:
    if not isinstance(message, dict):
        return []
    raw = message.get("tool_calls") or []
    if not isinstance(raw, list):
        return []
    out = []
    for i, tc in enumerate(raw):
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
        args = fn.get("arguments")
        if isinstance(args, dict):
            args_s = json.dumps(args)
        else:
            args_s = str(args or "{}")
        out.append(
            {
                "id": str(tc.get("id") or f"call_{i}"),
                "type": "function",
                "function": {"name": str(fn.get("name") or ""), "arguments": args_s},
            }
        )
    return out


def messages_for_api(messages: list[dict]) -> list[dict]:
    out = []
    for m in messages:
        role = (m or {}).get("role")
        if role in ("system", "user"):
            out.append({"role": role, "content": m.get("content") or ""})
        elif role == "assistant":
            item: dict = {"role": "assistant", "content": m.get("content") if m.get("content") is not None else ""}
            calls = parse_openai_tool_calls(m) if m.get("tool_calls") else []
            if calls:
                item["tool_calls"] = calls
                if not (m.get("content") or "").strip():
                    item["content"] = None
            out.append(item)
        elif role == "tool":
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": str(m.get("tool_call_id") or ""),
                    "content": m.get("content") or "",
                }
            )
    return out


class OpenAICompatProvider:
    """OpenAI Chat Completions API (also Groq/OpenRouter if base_url + key match)."""

    name = "openai"

    def __init__(self, api_key: str, base_url: str, model: str):
        self.api_key = api_key
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.model = model or "gpt-4o-mini"

    def complete(
        self,
        messages: list[dict],
        *,
        max_tokens: int,
        temperature: float,
        timeout: float,
        tools: list | None = None,
    ) -> ChatResult:
        url = self.base_url + "/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages_for_api(messages),
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
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
        message = choice.get("message") or {}
        text = (message.get("content") or "").strip()
        tool_calls = parse_openai_tool_calls(message)
        usage = raw.get("usage") or {}
        if not text and not tool_calls:
            raise RuntimeError("AI bo'sh javob qaytardi")
        return ChatResult(
            text=text,
            provider=self.name,
            model=str(raw.get("model") or self.model),
            latency_ms=latency,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            tool_calls=tool_calls,
        )

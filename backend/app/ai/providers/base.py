from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ChatResult:
    text: str
    provider: str
    model: str = ""
    latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    fallback: bool = False
    error: str = ""
    extra: dict = field(default_factory=dict)


class AiProvider(Protocol):
    name: str

    def complete(self, messages: list[dict], *, max_tokens: int, temperature: float, timeout: float) -> ChatResult:
        ...

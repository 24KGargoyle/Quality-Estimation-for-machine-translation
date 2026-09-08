"""Thin wrapper around the Anthropic Messages API.

Centralizing this call makes prompt-construction (`agents/prompts.py`)
testable independently from the network call, and gives us one place to add
logging/latency capture.
"""
from __future__ import annotations

import time

from meeting_intel.config import get_settings

settings = get_settings()


class LLMNotConfiguredError(Exception):
    pass


class LLMResult:
    def __init__(self, text: str, latency_ms: int, model: str):
        self.text = text
        self.latency_ms = latency_ms
        self.model = model


def _client():
    if not settings.llm_configured:
        raise LLMNotConfiguredError("ANTHROPIC_API_KEY is not configured.")
    import anthropic

    return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)


async def complete(*, system: str, messages: list[dict], max_tokens: int = 1024) -> LLMResult:
    start = time.perf_counter()
    response = await _client().messages.create(
        model=settings.llm_model,
        system=system,
        messages=messages,
        max_tokens=max_tokens,
    )
    latency_ms = int((time.perf_counter() - start) * 1000)
    text = "".join(block.text for block in response.content if block.type == "text")
    return LLMResult(text=text, latency_ms=latency_ms, model=settings.llm_model)

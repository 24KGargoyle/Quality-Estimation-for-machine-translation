"""Opt-in external web research, kept separate from meeting evidence."""
from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

from meeting_intel.config import get_settings

logger = logging.getLogger("meeting_intel.web_research")

# Trigger words suggesting the question is about general best practice /
# technical guidance rather than "what happened in this meeting" — the only
# case web research should fire (§3.2: never for a plain "what did X say").
_RESEARCH_TRIGGER_WORDS = (
    "best practice", "best practices", "how to", "recommend", "recommendation",
    "documentation", "official docs", "compare", "approach", "architecture pattern",
    "industry standard", "reference architecture", "guidance", "tutorial",
)
_PERSON_QUESTION_PATTERNS = (
    "what did", "what does", "who is", "who said", "did say", "responsible for", "role",
)


def should_research_web(query: str) -> bool:
    q = query.lower()
    if any(p in q for p in _PERSON_QUESTION_PATTERNS):
        return False
    return ("search the web" in q or "web research" in q) and any(w in q for w in _RESEARCH_TRIGGER_WORDS)


def extract_research_topic(query: str) -> str:
    """A short search-engine-friendly topic string — strips generic
    question scaffolding, keeps the substantive noun phrase."""
    q = re.sub(
        r"\b(what|are|is|the|common|approaches|for|about|discussed|in|this|meeting|"
        r"can|you|tell|me|please|do|we|have|any)\b",
        " ",
        query.lower(),
    )
    return re.sub(r"\s+", " ", q).strip() or query.strip()


@dataclass
class WebResult:
    title: str
    snippet: str
    url: str


@dataclass
class WebResearchResult:
    configured: bool
    query: str
    results: list[WebResult]
    note: str | None = None


class WebResearchNotConfiguredError(RuntimeError):
    pass


class WebResearchProvider(ABC):
    @abstractmethod
    async def research(self, topic: str, *, max_results: int = 3) -> WebResearchResult: ...


class NotConfiguredWebResearchProvider(WebResearchProvider):
    async def research(self, topic: str, *, max_results: int = 3) -> WebResearchResult:
        return WebResearchResult(
            configured=False, query=topic, results=[],
            note="Web research is not configured (set WEB_RESEARCH_PROVIDER=azure_openai and WEB_RESEARCH_DEPLOYMENT).",
        )


class AzureWebResearchProvider(WebResearchProvider):
    async def research(self, topic: str, *, max_results: int = 3) -> WebResearchResult:
        settings = get_settings()
        if not (settings.azure_openai_endpoint and settings.azure_openai_api_key and settings.web_research_deployment):
            raise WebResearchNotConfiguredError("Azure web research is not configured.")
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    settings.azure_openai_endpoint.rstrip("/") + "/openai/v1/responses",
                    headers={"api-key": settings.azure_openai_api_key},
                    json={"model": settings.web_research_deployment, "tools": [{"type": "web_search"}],
                          "input": topic[:1000], "store": False},
                )
                response.raise_for_status()
                data = response.json()
            results = []
            seen = set()
            for item in data.get("output", []):
                for content in item.get("content", []):
                    for citation in content.get("annotations", []):
                        url = citation.get("url", "")
                        if citation.get("type") == "url_citation" and url.startswith(("https://", "http://")) and url not in seen:
                            seen.add(url)
                            results.append(WebResult(title=citation.get("title", url), snippet="External web source", url=url))
            return WebResearchResult(configured=True, query=topic, results=results[:max_results])
        except (httpx.HTTPError, ValueError, KeyError):
            raise WebResearchNotConfiguredError("External research is temporarily unavailable.") from None


_provider: WebResearchProvider | None = None


def get_web_research_provider() -> WebResearchProvider:
    global _provider
    if _provider is None:
        settings = get_settings()
        _provider = AzureWebResearchProvider() if settings.web_research_provider == "azure_openai" else NotConfiguredWebResearchProvider()
    return _provider

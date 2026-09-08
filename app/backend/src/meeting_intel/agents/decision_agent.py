"""Decision/Action-Item Agent.

Deliberately conservative: it only ever reports a *potential* decision for a
human to confirm (see docs/AGENT_ARCHITECTURE.md) — nothing here writes a
`Decision` row with status=confirmed. That happens only via the
POST /api/discussions/{id}/decisions confirmation endpoint.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from meeting_intel.agents.prompts import build_decision_messages
from meeting_intel.llm.client import LLMNotConfiguredError, complete


@dataclass
class ActionItemSuggestion:
    task: str
    owner: str


@dataclass
class DecisionSuggestion:
    detected: bool
    decision_text: str | None = None
    action_items: list[ActionItemSuggestion] = field(default_factory=list)


def _parse(text: str) -> DecisionSuggestion:
    lines = {ln.split(":", 1)[0].strip(): ln.split(":", 1)[1].strip() for ln in text.splitlines() if ":" in ln}
    detected = lines.get("DECISION_DETECTED", "no").lower().startswith("y")
    decision_text = lines.get("DECISION_TEXT") or None
    action_items = []
    raw_items = lines.get("ACTION_ITEMS", "")
    for part in raw_items.split(";"):
        part = part.strip()
        if not part:
            continue
        if "->" in part:
            task, owner = part.split("->", 1)
            action_items.append(ActionItemSuggestion(task=task.strip(), owner=owner.strip() or "unassigned"))
        else:
            action_items.append(ActionItemSuggestion(task=part, owner="unassigned"))
    return DecisionSuggestion(detected=detected, decision_text=decision_text, action_items=action_items)


async def detect_decision(group_history: list[dict]) -> DecisionSuggestion:
    if len(group_history) < 2:
        return DecisionSuggestion(detected=False)
    system, messages = build_decision_messages(group_history=group_history)
    try:
        result = await complete(system=system, messages=messages, max_tokens=300)
    except LLMNotConfiguredError:
        return DecisionSuggestion(detected=False)
    return _parse(result.text)

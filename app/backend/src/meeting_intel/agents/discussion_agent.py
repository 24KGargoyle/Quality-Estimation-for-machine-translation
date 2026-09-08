"""Discussion Agent: assists a group conversation using historical meeting
context (from the meeting the discussion was shared from) plus the live
group conversation, keeping the two clearly distinguished (see prompts.py)."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from meeting_intel.agents.prompts import build_discussion_messages, format_excerpts
from meeting_intel.db.models import Meeting
from meeting_intel.llm.client import LLMNotConfiguredError, complete
from meeting_intel.retrieval.hybrid_search import hybrid_search


async def assist_discussion(
    db: AsyncSession,
    *,
    meeting: Meeting | None,
    group_history: list[dict],
    question: str,
) -> str:
    meeting_context = "(no linked meeting for this discussion)"
    if meeting is not None:
        chunks = await hybrid_search(db, meeting_ids=[meeting.id], query=question, top_k=6)
        meeting_context = f"Meeting: {meeting.title}\n{format_excerpts(chunks)}"

    system, messages = build_discussion_messages(
        meeting_context=meeting_context, group_history=group_history, question=question
    )
    try:
        result = await complete(system=system, messages=messages)
    except LLMNotConfiguredError:
        return (
            "The AI model is not configured in this environment (missing ANTHROPIC_API_KEY), "
            "so I can't assist with this discussion right now."
        )
    return result.text

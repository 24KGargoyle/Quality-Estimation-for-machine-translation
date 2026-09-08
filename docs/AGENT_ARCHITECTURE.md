# Agent Architecture

No general-purpose agent framework (CrewAI, LangGraph, etc.) is used — the brief is explicit
that agents should be added "only where it provides real value," and this task's requirements
(strict meeting isolation, exact grounding/citations, conservative decision detection) are
better served by small, individually testable, deterministic-where-possible Python modules
under `app/backend/src/meeting_intel/agents/` than by a generic multi-agent runtime. If CrewAI
is confirmed as a hard client requirement, it can be introduced at the orchestration layer
described below without touching retrieval, the database, or the Teams integration — those are
already isolated behind `retrieval/hybrid_search.py`, `db/models.py`, and
`conversations/provider.py` respectively.

## Pipeline

```
Meeting Router  ─▶  Retrieval Agent  ─▶  Answer Agent
(meeting_router.py)  (retrieval_agent.py)  (answer_agent.py)
```

- **Meeting Router** (`agents/meeting_router.py`): decides retrieval scope. Default is always
  the single current meeting. Cross-meeting retrieval only activates on explicit phrasing
  ("compare this with last week's meeting", "across meetings", …) — see
  `docs/RAG_ARCHITECTURE.md`. Also extracts a speaker filter when the question names a known
  participant (e.g. "What did Chetan say…" → `speaker=Chetan`).
- **Retrieval Agent** (`agents/retrieval_agent.py`): resolves the meeting id(s) + speaker filter
  from the router, then calls `retrieval/hybrid_search.py`.
- **Answer Agent** (`agents/answer_agent.py`): builds the grounded prompt (`agents/prompts.py`),
  calls the LLM, parses citation markers (`[S1]`, `[S2]`, …) back to the exact retrieved chunk
  metadata, and reports `evidence_sufficient=False` with a fixed fallback message when there's
  nothing to ground an answer in.

For group discussions:

```
Discussion Agent (discussion_agent.py)
  = historical meeting context (hybrid_search over the linked meeting)
  + live group conversation history
  + the current question
```

The prompt (`prompts.py: DISCUSSION_SYSTEM_PROMPT`) explicitly instructs the model to keep
**historical fact**, **current discussion**, **current decision**, and **unresolved question**
distinct rather than merging a past meeting's content with the group's live opinions.

For decisions/action items:

```
Decision Agent (decision_agent.py)
```

Conservative by construction: `detect_decision()` only ever returns a *suggestion*
(`DecisionSuggestion.detected`, never persisted). The only way a `Decision` row is created is a
human hitting **Confirm Decision**, which calls `POST /api/discussions/{id}/decisions` — the
agent itself never writes to the `decisions` table. This matches the brief's requirement to
never auto-declare a decision.

## Prompt-injection defense

All prompts (`agents/prompts.py`) are built with strict separation between:
1. System instructions (never influenced by data)
2. Conversation/group history (context, not new instructions)
3. Retrieved transcript/group content (untrusted **data**, wrapped in `<retrieved_transcript_excerpts>`
   / `<current_group_conversation>` tags with an explicit warning immediately before them)
4. The current user's question (the only text treated as an instruction)

See `docs/SECURITY.md` for the full threat model and a concrete test case
(`tests/unit/test_prompts_and_grounding.py::test_build_meeting_qa_messages_separates_untrusted_data`).

## LLM

`llm/client.py` wraps the Anthropic Messages API (`ANTHROPIC_API_KEY`, model configurable via
`LLM_MODEL`, default `claude-sonnet-5`). Every agent that calls the LLM handles
`LLMNotConfiguredError` by returning an honest "the AI model isn't configured" message rather
than crashing or fabricating an answer — verified in this environment, since no Anthropic API
key was available to exercise a live call (see `IMPLEMENTATION_REPORT.md`).

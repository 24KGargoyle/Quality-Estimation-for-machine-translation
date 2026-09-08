# Feedback & Evaluation

## Collection

Every AI message in private chat supports 👍/👎 (`POST /api/messages/{message_id}/feedback`).
A 👎 can optionally include a structured reason:

`incorrect_answer`, `wrong_speaker`, `wrong_meeting`, `missing_information`, `wrong_timestamp`,
`not_relevant`, `other` — plus a free-text comment.

Each `feedback` row (`db/models.py: Feedback`) stores the question, answer, meeting id, rating,
reason, and the retrieved source chunk ids (`retrieved_source_ids`) — enough to reconstruct
exactly what evidence the system had when it answered, without re-running retrieval.

**Feedback does not automatically retrain or fine-tune the model.** It is evaluation data. This
is stated explicitly here and in the Feedback UI page copy per the brief's requirement not to
overclaim.

## What feedback is used for

```
Feedback (thumbs + reason + Q/A + sources)
   ↓
Evaluation dataset (a feedback row IS an eval example: question, retrieved sources, answer, label)
   ↓
Metrics — read off the stored data directly:
   - retrieval quality: for 👎/wrong_speaker or wrong_timestamp, check whether retrieved_source_ids
     actually match the reported issue
   - answer quality: 👍/👎 rate segmented by meeting, by whether evidence_sufficient was true/false
   - speaker attribution: wrong_speaker rate specifically
   - ranking quality: for missing_information, whether a better chunk existed in the meeting but
     wasn't in the top-k (compare against GET /api/meetings/{id}/sources)
   ↓
Failure pattern identification (manual review of GET /api/feedback, grouped by reason)
   ↓
Retrieval/prompt improvement (e.g. adjust retrieval_top_k, retrieval_min_score in config.py,
  or the grounding instructions in agents/prompts.py)
   ↓
Regression test (add the failing question as a new case in tests/unit/test_prompts_and_grounding.py
  or tests/e2e/test_full_flow.py so the fix is locked in)
```

`GET /api/feedback` (tenant admins see all tenant feedback; other users see their own) is the
entry point for this loop today. A batch export script pulling this into a CSV/JSONL eval
dataset file is a natural next step — not built in this pass (see
`IMPLEMENTATION_REPORT.md`), since the live `feedback` table already contains everything an
export would need; building the export machinery around it depends on which eval tool the team
adopts.

## Regression testing in place today

`tests/unit/test_prompts_and_grounding.py` fixes the exact grounding/citation behavior
(citation-to-chunk mapping, fallback message text, out-of-range citation handling) so a future
prompt change that breaks grounding fails CI immediately rather than being caught only via
production feedback.

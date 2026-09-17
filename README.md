# Quality Estimation for Machine Translation

This repository contains two independent pieces of work:

## 1. Quality Estimation (QE) for Machine Translation

The original challenge: estimating translation quality without a reference translation, using
HTER regression and multilingual BERT. See `README_Challenge2.md` for the full write-up,
`Challenge2_FullDetailed_Report.pdf` for the detailed report, and `build_qe_labels.py`/
`train_qe_regression.py`/`translate_and_evaluate.py` for the pipeline. This part of the repo is
unrelated to the Teams Meeting Intelligence platform below and was not touched by that work.

```
pip install -r requirements.txt
python build_qe_labels.py
python train_qe_regression.py
```

## 2. Teams Meeting Intelligence platform (`app/`)

A separate application: Microsoft Teams meeting transcripts *and* historical meeting folders
(Word/Excel/PDF/PowerPoint/CSV/text) → retrieval-augmented Q&A, group discussion, and
decision/action-item tracking, built on FastAPI + Next.js.

```
Microsoft Teams ── Graph API ── FastAPI backend (Entra ID auth, meeting ingestion, AI agents)
                                        │                    │
                                        ▼                    ▼
                          Azure SQL Database          Azure AI Search
                          (app/transactional data)    (keyword + vector + semantic hybrid search)
                                        │                    │
                                        └────────┬───────────┘
                                                 ▼
                                          Azure OpenAI (or Anthropic Claude)
                                                 │
                                                 ▼
                                  Meeting Intelligence (answers, discussion, decisions)
                                                 │
                                                 ▼
                                          back to Teams
```

**No PostgreSQL dependency anywhere in this app.** The relational store is SQLite (local
dev/tests, zero setup) or Azure SQL Database (production); transcript search is an honestly-
labeled in-memory provider (dev/tests) or Azure AI Search (production, hybrid keyword + vector +
semantic ranking). See `docs/MIGRATION_FROM_POSTGRES.md` for the full history of that change.

### Quick start (local, no Azure resources required)

```bash
cd app/backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in ANTHROPIC_API_KEY (or leave blank to run without LLM answers)
alembic upgrade head
uvicorn meeting_intel.main:app --app-dir src --reload --port 8000
```

```bash
cd app/frontend
npm install
cp .env.example .env.local
npm run dev
```

Open `http://localhost:3000`. See `docs/DEPLOYMENT.md` for the full setup, and
`docs/AZURE_SETUP.md` for provisioning Azure SQL Database / Azure AI Search / Azure OpenAI for
production use.

### Documentation

| Doc | Covers |
|---|---|
| `docs/ARCHITECTURE.md` | Component overview, directory layout, request flow, known limitations |
| `docs/DATABASE.md` | Schema, tables, migrations, tenant isolation |
| `docs/RAG_ARCHITECTURE.md` | Ingestion (live + historical), the `SearchProvider` abstraction, retrieval, grounding/citations |
| `docs/HISTORICAL_IMPORT.md` | Historical Meeting Data Import: supported formats, parser architecture, meeting association, duplicate detection, security |
| `docs/AZURE_SETUP.md` | Provisioning Azure SQL Database, Azure AI Search, Azure OpenAI, Azure Blob Storage |
| `docs/MIGRATION_FROM_POSTGRES.md` | What changed when PostgreSQL was removed, and why (historical) |
| `docs/TEAMS_INTEGRATION.md` | Graph/Teams meeting resolution, authorization, Entra ID security, Teams messaging |
| `docs/MICROSOFT_GRAPH_PERMISSIONS.md` | Exact Graph app registration and permissions |
| `docs/AGENT_ARCHITECTURE.md` | The router/answer/discussion/decision agent pipeline, prompt-injection defense |
| `docs/SECURITY.md` | Threat model |
| `docs/TESTING.md` | What's tested, how to run the suite, what's explicitly out of scope |
| `docs/DEPLOYMENT.md` | Local setup, production deployment notes |
| `docs/API.md` | API reference |
| `docs/FEEDBACK_AND_EVALUATION.md` | Feedback pipeline |
| `ARCHITECTURE_ASSESSMENT.md`, `IMPLEMENTATION_REPORT.md` | Original pre-implementation assessment and initial build report (predate the PostgreSQL removal — see `docs/MIGRATION_FROM_POSTGRES.md` for what changed since) |
| `docs/audits/PRE_UPGRADE_AUDIT.md`, `docs/audits/POST_UPGRADE_AUDIT.md` | Before/after audit for the Historical Meeting Data Import upgrade |

### Tests

```bash
cd app/backend
source .venv/bin/activate
python -m pytest -q
```

107 tests, no external database or Azure resource required — see `docs/TESTING.md`.

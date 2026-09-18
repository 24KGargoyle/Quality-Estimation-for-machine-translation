"""Shared IntelligencePanel -> IntelligencePanelSchema conversion, used by
both `/api/chat` and `/api/meetings/{id}/intelligence` so the two endpoints
never drift in shape."""
from __future__ import annotations

from meeting_intel.agents.intelligence_panel import IntelligencePanel
from meeting_intel.api.schemas import (
    IntelligencePanelSchema,
    RelatedDocumentSchema,
    WebResearchSchema,
    WebResultSchema,
)


def panel_to_schema(panel: IntelligencePanel) -> IntelligencePanelSchema:
    web = None
    if panel.web_research is not None:
        web = WebResearchSchema(
            configured=panel.web_research.configured,
            query=panel.web_research.query,
            results=[
                WebResultSchema(title=r.title, snippet=r.snippet, url=r.url) for r in panel.web_research.results
            ],
            note=panel.web_research.note,
        )
    return IntelligencePanelSchema(
        related_topics=panel.related_topics,
        related_documents=[
            RelatedDocumentSchema(
                source_file=d.source_file, document_type=d.document_type, file_type=d.file_type,
                location=d.location,
            )
            for d in panel.related_documents
        ],
        related_people=panel.related_people,
        ideas=panel.ideas,
        web_research=web,
    )

"""ConversationProvider abstraction.

Business logic (group chat, "Discuss with Group", the Discussion Agent) talks
to this interface, never directly to WebSockets or the Graph API. This is
what lets a "group" be an internal group today and a Microsoft Teams chat or
channel later without touching the agent layer.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from meeting_intel.db.models import TeamsMapping


class ConversationProvider(ABC):
    @abstractmethod
    async def broadcast(self, group_id: str, message: dict) -> None:
        """Deliver a new message to live participants of this group."""

    @abstractmethod
    async def post_shared_context(self, group_id: str, *, html_content: str) -> None:
        """Push AI-shared meeting context into the underlying conversation surface."""


class InternalChatProvider(ConversationProvider):
    async def broadcast(self, group_id: str, message: dict) -> None:
        from meeting_intel.realtime.ws_manager import ws_manager

        await ws_manager.broadcast(group_id, message)

    async def post_shared_context(self, group_id: str, *, html_content: str) -> None:
        # Internal groups only need the DB row (created by the caller) + a
        # live broadcast; nothing external to push to.
        return None


class TeamsChatProvider(ConversationProvider):
    def __init__(self, teams_chat_id: str):
        self.teams_chat_id = teams_chat_id

    async def broadcast(self, group_id: str, message: dict) -> None:
        # Teams delivers messages to its own clients; nothing to push here.
        # Still fan out to any internal viewers (e.g. an embedded web view).
        from meeting_intel.realtime.ws_manager import ws_manager

        await ws_manager.broadcast(group_id, message)

    async def post_shared_context(self, group_id: str, *, html_content: str) -> None:
        from meeting_intel.graph.client import get_graph_client

        await get_graph_client().send_chat_message(chat_id=self.teams_chat_id, content_html=html_content)


async def get_provider(db: AsyncSession, *, group_id: str) -> ConversationProvider:
    mapping = (
        await db.execute(select(TeamsMapping).where(TeamsMapping.group_id == group_id))
    ).scalar_one_or_none()
    if mapping and mapping.teams_chat_id:
        return TeamsChatProvider(mapping.teams_chat_id)
    return InternalChatProvider()

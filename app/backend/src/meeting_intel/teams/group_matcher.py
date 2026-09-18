"""Deterministic matching of an existing Teams group chat against a
meeting's resolved participants (§5 of the upgrade). No fuzzy/similarity
matching — only exact participant-set comparisons on real Entra
object ids, per the spec's explicit "do not make weak guesses".
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MatchedChat:
    chat_id: str
    topic: str | None
    member_user_ids: set[str]
    member_names: list[str]
    match_kind: str  # "exact"


def _chat_member_ids(chat: dict) -> set[str]:
    ids = set()
    for member in chat.get("members", []):
        uid = member.get("userId")
        if uid:
            ids.add(uid)
    return ids


def _chat_member_names(chat: dict) -> list[str]:
    return [m.get("displayName", "Unknown") for m in chat.get("members", [])]


def find_matching_chat(chats: list[dict], target_user_ids: set[str]) -> MatchedChat | None:
    """Match complete identity sets; never include extra or unresolved recipients."""
    if not target_user_ids:
        return None

    for chat in sorted(chats, key=lambda c: c["id"]):
        members = chat.get("members", [])
        if chat.get("chatType", "group") != "group" or any(not m.get("userId") for m in members):
            continue
        if _chat_member_ids(chat) == target_user_ids:
            return MatchedChat(chat["id"], chat.get("topic"), target_user_ids,
                               _chat_member_names(chat), "exact")
    return None

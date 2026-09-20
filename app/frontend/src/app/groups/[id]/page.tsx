"use client";

import { useEffect, useRef, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import RequireAuth from "@/components/RequireAuth";
import Conversation, { ConversationHandle } from "@/components/Conversation";
import GroupMembers from "@/components/GroupMembers";
import { useAuth } from "@/lib/auth";
import { api, wsBase } from "@/lib/api";
import { ActionItemSchema, DecisionSchema, GroupMessageSchema, SuggestedDecision } from "@/lib/types";

function GroupWorkspace() {
  const params = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const groupId = params.id;
  const discussionId = searchParams.get("discussion");
  const { user } = useAuth();

  const [messages, setMessages] = useState<GroupMessageSchema[]>([]);
  const [input, setInput] = useState("");
  const [askAi, setAskAi] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [suggestion, setSuggestion] = useState<SuggestedDecision | null>(null);
  const [decisions, setDecisions] = useState<DecisionSchema[]>([]);
  const [actionItems, setActionItems] = useState<ActionItemSchema[]>([]);
  const [editableDecision, setEditableDecision] = useState("");
  const conversationRef = useRef<ConversationHandle>(null);
  const wsRef = useRef<WebSocket | null>(null);

  function refreshMessages() {
    api.get<GroupMessageSchema[]>(`/api/groups/${groupId}/messages`).then(setMessages).catch(() => {});
  }
  function refreshDecisions() {
    api.get<DecisionSchema[]>(`/api/discussions/groups/${groupId}/decisions`).then(setDecisions).catch(() => {});
    api.get<ActionItemSchema[]>(`/api/discussions/groups/${groupId}/action-items`).then(setActionItems).catch(() => {});
  }

  useEffect(() => {
    refreshMessages();
    refreshDecisions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groupId]);

  useEffect(() => {
    const token = window.localStorage.getItem("mi_token");
    if (!token) return;
    const ws = new WebSocket(`${wsBase()}/api/groups/${groupId}/ws?token=${encodeURIComponent(token)}`);
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as GroupMessageSchema;
        setMessages((prev) => (prev.some((m) => m.id === data.id) ? prev : [...prev, data]));
      } catch {
        // ignore malformed frames
      }
    };
    wsRef.current = ws;
    return () => ws.close();
  }, [groupId]);


  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim() || sending) return;
    conversationRef.current?.followLatest();
    setError(null);
    setSending(true);
    const content = input;
    setInput("");
    try {
      await api.post(`/api/groups/${groupId}/messages`, { content, ask_ai: askAi });
      refreshMessages();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send your message.");
      setInput(content);
    } finally {
      setSending(false);
    }
  }

  async function checkForDecision() {
    if (!discussionId) return;
    const s = await api.get<SuggestedDecision>(`/api/discussions/${discussionId}/suggested-decision`);
    setSuggestion(s);
    if (s.detected) setEditableDecision(s.decision_text || "");
  }

  async function confirmDecision() {
    if (!discussionId || !suggestion) return;
    await api.post(`/api/discussions/${discussionId}/decisions`, {
      decision_text: editableDecision,
      action_items: suggestion.action_items.map((a) => ({ task: a.task, owner_name: a.owner })),
    });
    setSuggestion(null);
    refreshDecisions();
  }

  return (
    <div className="group-workspace mx-auto grid max-w-7xl gap-6 lg:grid-cols-[minmax(0,1fr)_280px]">
      <div className="chat-panel flex flex-col rounded-xl border border-neutral-200">
        <Conversation ref={conversationRef} label="Group conversation">
          {messages.length === 0 && <p className="chat-empty"><strong>Bring everyone into the conversation.</strong>Share a message with your group to get started.</p>}
          {messages.map((m) => {
            const isMe = m.sender_user_id === user?.userId;
            const isAi = !m.sender_user_id;
            return (
              <div key={m.id} className={`flex ${isMe ? "justify-end" : "justify-start"}`}>
                <div
                  className={`max-w-[80%] rounded-2xl px-4 py-2.5 text-sm ${
                    isMe
                      ? "rounded-br-sm border border-blue-100 bg-blue-50 text-neutral-900"
                      : isAi
                      ? "rounded-bl-sm border border-blue-200 bg-blue-50"
                      : "rounded-bl-sm border border-neutral-200 bg-white"
                  }`}
                >
                  {!isMe && <div className="mb-0.5 text-xs font-semibold text-neutral-500">{m.sender_name}</div>}
                  <p className="whitespace-pre-wrap">{m.content}</p>
                </div>
              </div>
            );
          })}
          {sending && <p role="status" className="text-xs text-neutral-500">Sending message?</p>}
        </Conversation>

        {error && <p role="alert" className="px-4 py-2 text-sm text-red-600">{error}</p>}
        <form onSubmit={handleSend} className="chat-composer flex flex-col gap-2 border-t border-neutral-200">
          <label className="flex items-center gap-2 text-xs text-neutral-500">
            <input type="checkbox" checked={askAi} onChange={(e) => setAskAi(e.target.checked)} />
            Get an AI response
          </label>
          <div className="flex w-full gap-2">
            <textarea
              aria-label="Message the group"
              rows={1}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); e.currentTarget.form?.requestSubmit(); } }}
              className="flex-1 rounded-md border border-neutral-300 px-3 py-2 text-sm"
              placeholder="Message the group…"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={sending}
            />
            <button
              type="submit"
              disabled={sending || !input.trim()}
              className="rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              Send
            </button>
          </div>
        </form>
      </div>

      <aside className="space-y-4">
        <GroupMembers key={groupId} groupId={groupId} />
        {discussionId && (
          <div className="rounded-xl border border-neutral-200 bg-white p-4">
            <h3 className="text-sm font-semibold">Decision detection</h3>
            <button
              onClick={checkForDecision}
              className="mt-2 w-full rounded-md border border-neutral-300 px-3 py-1.5 text-xs hover:bg-neutral-50"
            >
              Check for a decision
            </button>
            {suggestion && !suggestion.detected && (
              <p className="mt-2 text-xs text-neutral-400">No clear decision detected yet.</p>
            )}
            {suggestion?.detected && (
              <div className="mt-3 rounded-md bg-amber-50 p-3 text-xs">
                <p className="font-medium text-amber-700">Potential decision detected</p>
                <textarea
                  className="mt-2 w-full rounded border border-amber-200 bg-white px-2 py-1 text-xs"
                  value={editableDecision}
                  onChange={(e) => setEditableDecision(e.target.value)}
                />
                <button
                  onClick={confirmDecision}
                  className="mt-2 w-full rounded-md bg-amber-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-amber-700"
                >
                  Confirm Decision
                </button>
              </div>
            )}
          </div>
        )}

        <div className="rounded-xl border border-neutral-200 bg-white p-4">
          <h3 className="text-sm font-semibold">Decisions</h3>
          <div className="mt-2 space-y-2">
            {decisions.map((d) => (
              <div key={d.id} className="rounded-md bg-neutral-50 p-2 text-xs">
                {d.decision_text}
              </div>
            ))}
            {decisions.length === 0 && <p className="text-xs text-neutral-400">None yet.</p>}
          </div>
        </div>

        <div className="rounded-xl border border-neutral-200 bg-white p-4">
          <h3 className="text-sm font-semibold">Action items</h3>
          <div className="mt-2 space-y-2">
            {actionItems.map((a) => (
              <div key={a.id} className="rounded-md bg-neutral-50 p-2 text-xs">
                <div>{a.task}</div>
                <div className="mt-0.5 text-neutral-400">
                  Owner: {a.owner_name || "Unassigned"} · {a.status}
                </div>
              </div>
            ))}
            {actionItems.length === 0 && <p className="text-xs text-neutral-400">None yet.</p>}
          </div>
        </div>
      </aside>
    </div>
  );
}

export default function GroupPage() {
  return (
    <RequireAuth>
      <GroupWorkspace />
    </RequireAuth>
  );
}

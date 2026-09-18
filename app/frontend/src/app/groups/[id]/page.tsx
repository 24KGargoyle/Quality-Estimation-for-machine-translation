"use client";

import { useEffect, useRef, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import RequireAuth from "@/components/RequireAuth";
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
  const [suggestion, setSuggestion] = useState<SuggestedDecision | null>(null);
  const [decisions, setDecisions] = useState<DecisionSchema[]>([]);
  const [actionItems, setActionItems] = useState<ActionItemSchema[]>([]);
  const [editableDecision, setEditableDecision] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
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

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim()) return;
    setSending(true);
    const content = input;
    setInput("");
    try {
      await api.post(`/api/groups/${groupId}/messages`, { content, ask_ai: askAi });
      refreshMessages();
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
    <div className="mx-auto grid max-w-5xl gap-6 px-4 py-6 lg:grid-cols-[1fr_280px]">
      <div className="flex min-h-[500px] flex-col rounded-xl border border-neutral-200 bg-neutral-50/60 dark:border-neutral-800 dark:bg-neutral-900/40">
        <div className="flex-1 space-y-3 overflow-y-auto p-4">
          {messages.map((m) => {
            const isMe = m.sender_user_id === user?.userId;
            const isAi = !m.sender_user_id;
            return (
              <div key={m.id} className={`flex ${isMe ? "justify-end" : "justify-start"}`}>
                <div
                  className={`max-w-[80%] rounded-2xl px-4 py-2.5 text-sm ${
                    isMe
                      ? "rounded-br-sm bg-neutral-900 text-white dark:bg-white dark:text-neutral-900"
                      : isAi
                      ? "rounded-bl-sm border border-blue-200 bg-blue-50 dark:border-blue-900 dark:bg-blue-950/40"
                      : "rounded-bl-sm border border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900"
                  }`}
                >
                  {!isMe && <div className="mb-0.5 text-xs font-semibold text-neutral-500">{m.sender_name}</div>}
                  <p className="whitespace-pre-wrap">{m.content}</p>
                </div>
              </div>
            );
          })}
          <div ref={bottomRef} />
        </div>

        <form onSubmit={handleSend} className="flex flex-col gap-2 border-t border-neutral-200 p-3 dark:border-neutral-800">
          <label className="flex items-center gap-2 text-xs text-neutral-500">
            <input type="checkbox" checked={askAi} onChange={(e) => setAskAi(e.target.checked)} />
            Ask Meeting Copilot to weigh in on this message
          </label>
          <div className="flex gap-2">
            <input
              className="flex-1 rounded-md border border-neutral-300 px-3 py-2 text-sm dark:border-neutral-700 dark:bg-neutral-950"
              placeholder="Message the group…"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={sending}
            />
            <button
              type="submit"
              disabled={sending || !input.trim()}
              className="rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-white dark:text-neutral-900"
            >
              Send
            </button>
          </div>
        </form>
      </div>

      <aside className="space-y-4">
        <GroupMembers key={groupId} groupId={groupId} />
        {discussionId && (
          <div className="rounded-xl border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-900">
            <h3 className="text-sm font-semibold">Decision detection</h3>
            <button
              onClick={checkForDecision}
              className="mt-2 w-full rounded-md border border-neutral-300 px-3 py-1.5 text-xs hover:bg-neutral-50 dark:border-neutral-700 dark:hover:bg-neutral-800"
            >
              Check for a decision
            </button>
            {suggestion && !suggestion.detected && (
              <p className="mt-2 text-xs text-neutral-400">No clear decision detected yet.</p>
            )}
            {suggestion?.detected && (
              <div className="mt-3 rounded-md bg-amber-50 p-3 text-xs dark:bg-amber-950/30">
                <p className="font-medium text-amber-700 dark:text-amber-400">Potential decision detected</p>
                <textarea
                  className="mt-2 w-full rounded border border-amber-200 bg-white px-2 py-1 text-xs dark:border-amber-900 dark:bg-neutral-950"
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

        <div className="rounded-xl border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-900">
          <h3 className="text-sm font-semibold">Decisions</h3>
          <div className="mt-2 space-y-2">
            {decisions.map((d) => (
              <div key={d.id} className="rounded-md bg-neutral-50 p-2 text-xs dark:bg-neutral-800/60">
                {d.decision_text}
              </div>
            ))}
            {decisions.length === 0 && <p className="text-xs text-neutral-400">None yet.</p>}
          </div>
        </div>

        <div className="rounded-xl border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-900">
          <h3 className="text-sm font-semibold">Action items</h3>
          <div className="mt-2 space-y-2">
            {actionItems.map((a) => (
              <div key={a.id} className="rounded-md bg-neutral-50 p-2 text-xs dark:bg-neutral-800/60">
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

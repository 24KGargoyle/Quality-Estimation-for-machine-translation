"use client";

import { useEffect, useRef, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import RequireAuth from "@/components/RequireAuth";
import ChatMessage from "@/components/ChatMessage";
import { api, ApiError } from "@/lib/api";
import { ChatResponse, ConversationDetail, MeetingDetail, MessageSchema } from "@/lib/types";

function fmtDuration(seconds: number | null) {
  if (!seconds) return "Unknown";
  const m = Math.round(seconds / 60);
  return `${m} minute${m === 1 ? "" : "s"}`;
}

function MeetingWorkspace() {
  const params = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const meetingId = params.id;

  const [meeting, setMeeting] = useState<MeetingDetail | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(
    searchParams.get("conversation")
  );
  const [messages, setMessages] = useState<MessageSchema[]>([]);
  const [input, setInput] = useState("");
  const [documentId, setDocumentId] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.get<MeetingDetail>(`/api/meetings/${meetingId}`).then(setMeeting).catch(() => {});
  }, [meetingId]);

  useEffect(() => {
    if (!conversationId) return;
    api
      .get<ConversationDetail>(`/api/conversations/${conversationId}`)
      .then((c) => setMessages(c.messages))
      .catch(() => {});
  }, [conversationId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim()) return;
    setError(null);
    setNotice(null);
    const question = input;
    setInput("");
    setMessages((prev) => [
      ...prev,
      { id: `tmp-${Date.now()}`, role: "user", content: question, sender_user_id: null, created_at: new Date().toISOString(), sources: [] },
    ]);
    setSending(true);
    try {
      const res = await api.post<ChatResponse>("/api/chat", {
        meeting_id: meetingId,
        document_id: documentId || null,
        conversation_id: conversationId,
        message: question,
      });
      setConversationId(res.conversation_id);
      if (res.cross_meeting) {
        setNotice("This answer draws on multiple meetings you're authorized to see, because you asked to compare/search across meetings.");
      }
      const conv = await api.get<ConversationDetail>(`/api/conversations/${res.conversation_id}`);
      setMessages(conv.messages);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to get an answer");
    } finally {
      setSending(false);
    }
  }

  if (!meeting) {
    return <div className="p-8 text-sm text-neutral-500">Loading meeting…</div>;
  }

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6 px-4 py-6">
      <div className="rounded-xl border border-neutral-200 bg-white p-5 dark:border-neutral-800 dark:bg-neutral-900">
        <div className="flex items-center gap-2">
          <h1 className="text-lg font-semibold">{meeting.title}</h1>
          {meeting.is_historical && (
            <span className="rounded-full bg-blue-100 px-2 py-0.5 text-xs text-blue-700 dark:bg-blue-900/40 dark:text-blue-300">
              Historical
            </span>
          )}
        </div>
        <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
          <div>
            <div className="text-xs text-neutral-400">Meeting ID</div>
            <div>{meeting.ms_meeting_id}</div>
          </div>
          <div>
            <div className="text-xs text-neutral-400">Duration</div>
            <div>{fmtDuration(meeting.duration_seconds)}</div>
          </div>
          <div>
            <div className="text-xs text-neutral-400">Participants</div>
            <div>{meeting.participant_count}</div>
          </div>
          <div>
            <div className="text-xs text-neutral-400">Transcript</div>
            <div>{meeting.transcript_available ? "Available" : "Unavailable"}</div>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {meeting.participants.map((p) => (
            <span
              key={p.display_name}
              className="rounded-full bg-neutral-100 px-2.5 py-0.5 text-xs text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300"
            >
              {p.display_name}
            </span>
          ))}
        </div>

        {meeting.documents.length > 0 && (
          <div className="mt-4 border-t border-neutral-100 pt-3 dark:border-neutral-800">
            <div className="text-xs text-neutral-400">Documents: {meeting.document_count}</div>
            <ul className="mt-1.5 space-y-1 text-sm text-neutral-600 dark:text-neutral-300">
              {meeting.documents.map((d) => (
                <li key={d.id} className="flex items-center gap-2">
                  <span className="text-neutral-400">├──</span>
                  <span>{d.relative_path}</span>
                  <span className="text-xs text-neutral-400">({d.document_type})</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <div className="flex min-h-[400px] flex-col rounded-xl border border-neutral-200 bg-neutral-50/60 dark:border-neutral-800 dark:bg-neutral-900/40">
        <div className="flex-1 space-y-4 overflow-y-auto p-4">
          {messages.length === 0 && (
            <p className="text-center text-sm text-neutral-400">
              Ask about this meeting — e.g. &ldquo;What did Chetan say about CrewAI?&rdquo;
            </p>
          )}
          {messages.map((m) => (
            <ChatMessage key={m.id} message={m} />
          ))}
          <div ref={bottomRef} />
        </div>

        {notice && <p className="px-4 pb-1 text-xs text-blue-600 dark:text-blue-400">{notice}</p>}
        {error && <p className="px-4 pb-1 text-xs text-red-600">{error}</p>}
        {meeting.documents.length > 0 && (
          <div className="px-4 pb-3">
            <label htmlFor="question-document" className="mb-1 block text-sm">Answer from</label>
            <select
              id="question-document"
              value={documentId}
              disabled={sending}
              onChange={(e) => {
                setDocumentId(e.target.value);
                setConversationId(null);
                setMessages([]);
                setError(null);
                setNotice(null);
              }}
              className="w-full rounded-md border border-neutral-300 bg-white p-2 text-sm dark:border-neutral-700 dark:bg-neutral-950"
            >
              <option value="">All documents in this meeting</option>
              {meeting.documents.map((doc) => (
                <option key={doc.id} value={doc.id}>{doc.source_file}</option>
              ))}
            </select>
            <p className="mt-1 text-xs text-neutral-500">Select a transcript to restrict answers and citations to that file.</p>
          </div>
        )}
        {!meeting.transcript_available && meeting.documents.length === 0 && (
          <p className="px-4 pb-2 text-xs text-amber-600 dark:text-amber-400">
            This meeting has no transcript indexed yet, so questions can&apos;t be answered from it.
          </p>
        )}

        <form onSubmit={handleSend} className="flex gap-2 border-t border-neutral-200 p-3 dark:border-neutral-800">
          <input
            className="flex-1 rounded-md border border-neutral-300 px-3 py-2 text-sm dark:border-neutral-700 dark:bg-neutral-950"
            placeholder="Ask about this meeting…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={sending}
          />
          <button
            type="submit"
            disabled={sending || !input.trim()}
            className="rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-white dark:text-neutral-900"
          >
            {sending ? "Thinking…" : "Send"}
          </button>
        </form>
      </div>
    </div>
  );
}

export default function MeetingWorkspacePage() {
  return (
    <RequireAuth>
      <MeetingWorkspace />
    </RequireAuth>
  );
}

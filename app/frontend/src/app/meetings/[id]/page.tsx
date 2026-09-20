"use client";

import { useEffect, useRef, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import Icon from "@/components/Icon";
import RequireAuth from "@/components/RequireAuth";
import IntelligencePanel from "@/components/IntelligencePanel";
import { IntelligencePanel as IntelligenceData } from "@/lib/types";
import Conversation, { ConversationHandle } from "@/components/Conversation";
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
  const [intelligence, setIntelligence] = useState<IntelligenceData | null>(null);
  const [input, setInput] = useState("");
  const [documentId, setDocumentId] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const conversationRef = useRef<ConversationHandle>(null);

  useEffect(() => {
    api.get<MeetingDetail>(`/api/meetings/${meetingId}`).then(setMeeting).catch(() => setError("Could not load this meeting. Refresh to try again."));
  }, [meetingId]);

  useEffect(() => {
    if (!conversationId) return;
    api
      .get<ConversationDetail>(`/api/conversations/${conversationId}`)
      .then((c) => setMessages(c.messages))
      .catch(() => setError("Could not load conversation history. Refresh to try again."));
  }, [conversationId]);


  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim() || sending) return;
    conversationRef.current?.followLatest();
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
      setIntelligence(res.intelligence);
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
    return <div role={error ? "alert" : "status"} className="p-8 text-sm text-neutral-500">{error || "Loading meeting..."}</div>;
  }

  return (
    <div className="workspace mx-auto flex max-w-7xl flex-col">
      <details className="meeting-context"><summary className="meeting-summary"><span className="meeting-summary-icon"><Icon name="meetings" size={22} /></span><span className="meeting-summary-title"><span className="eyebrow">MEETING WORKSPACE</span><strong>{meeting.title}</strong></span><span className="meeting-summary-meta">{meeting.participant_count} participants / {fmtDuration(meeting.duration_seconds)}</span><span className="details-label">Details +</span></summary><div className="meeting-detail-content">
        <div className="flex items-center gap-2">
          <h1 className="text-lg font-semibold">{meeting.title}</h1>
          {meeting.is_historical && (
            <span className="rounded-full bg-blue-100 px-2 py-0.5 text-xs text-blue-700">
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
              className="rounded-full bg-neutral-100 px-2.5 py-0.5 text-xs text-neutral-600"
            >
              {p.display_name}
            </span>
          ))}
        </div>

        {meeting.documents.length > 0 && (
          <div className="mt-4 border-t border-neutral-100 pt-3">
            <div className="text-xs text-neutral-400">Documents: {meeting.document_count}</div>
            <ul className="mt-1.5 space-y-1 text-sm text-neutral-600">
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
      </div></details>

      <div className="workspace-columns flex flex-col items-stretch gap-4 lg:flex-row">
      <div className="chat-panel w-full min-w-0 flex flex-col rounded-xl border border-neutral-200">
        <div className="chat-toolbar"><span><Icon name="spark" size={18} /> Meeting Assistant</span><span>Grounded in your meeting</span></div>
        <Conversation ref={conversationRef} label="Meeting conversation">
          {messages.length === 0 && (
            <div className="chat-empty"><span className="copilot-emblem"><Icon name="spark" size={32} /></span><p className="eyebrow">A NEW PERSPECTIVE</p><strong>What would you like<br />to uncover?</strong><p>Go beyond the transcript. Ask a question and find clarity in your meeting.</p><div className="prompt-starters">{["What were the key decisions?", "Summarize the main discussion.", "What are the next steps?"].map((prompt) => <button key={prompt} onClick={() => { setInput(prompt); document.getElementById("meeting-prompt")?.focus(); }}><Icon name="feedback" size={16} />{prompt}<Icon name="arrow" size={15} /></button>)}</div></div>
          )}
          {messages.map((m, index) => (
            <ChatMessage key={m.id} message={m} meetingId={meetingId} question={messages[index - 1]?.content ?? ""} />
          ))}
          {sending && <p role="status" className="text-sm text-neutral-500">Thinking through your meeting...</p>}
        </Conversation>

        {notice && <p className="px-4 pb-1 text-xs text-blue-600">{notice}</p>}
        {error && <p role="alert" className="px-4 pb-1 text-xs text-red-600">{error}</p>}
        {meeting.documents.length > 0 && (
          <div className="answer-scope">
            <label htmlFor="question-document" className="mb-1 block text-sm">Answer sources</label>
            <select
              id="question-document"
              value={documentId}
              disabled={sending}
              onChange={(e) => {
                setIntelligence(null);
                setDocumentId(e.target.value);
                setConversationId(null);
                setMessages([]);
                setError(null);
                setNotice(null);
              }}
              className="w-full rounded-md border border-neutral-300 bg-white p-2 text-sm"
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
          <p className="px-4 pb-2 text-xs text-amber-600">
            This meeting has no transcript indexed yet, so questions can&apos;t be answered from it.
          </p>
        )}

        <form onSubmit={handleSend} className="chat-composer flex gap-2 border-t border-neutral-200">
          <textarea
            id="meeting-prompt"
            aria-label="Ask about this meeting"
            rows={1}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); e.currentTarget.form?.requestSubmit(); } }}
            className="flex-1 rounded-md border border-neutral-300 px-3 py-2 text-sm"
            placeholder="Ask about this meeting…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={sending}
          />
          <button
            type="submit"
            disabled={sending || !input.trim()}
            className="rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {sending ? "Thinking…" : "Send"}
          </button>
        </form>
      </div>
      <IntelligencePanel data={intelligence} />
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

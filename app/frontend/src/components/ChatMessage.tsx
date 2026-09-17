"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { MessageSchema, SourceSchema } from "@/lib/types";
import ShareToGroupModal from "./ShareToGroupModal";

function sourceLabel(s: SourceSchema): string {
  if (s.document_type === "transcript" || !s.source_file) {
    return `Speaker: ${s.speaker || "Unknown"} · Timestamp: ${s.start_timestamp} · Source: Meeting transcript`;
  }
  if (s.page_number != null) return `File: ${s.source_file} · Page: ${s.page_number}`;
  if (s.sheet_name) return `File: ${s.source_file} · Sheet: ${s.sheet_name}`;
  if (s.slide_number != null) return `File: ${s.source_file} · Slide: ${s.slide_number}`;
  if (s.section) return `File: ${s.source_file} · Section: ${s.section}`;
  return `File: ${s.source_file}`;
}

const REASONS = [
  { value: "incorrect_answer", label: "Incorrect answer" },
  { value: "wrong_speaker", label: "Wrong speaker" },
  { value: "wrong_meeting", label: "Wrong meeting" },
  { value: "missing_information", label: "Missing information" },
  { value: "wrong_timestamp", label: "Wrong timestamp" },
  { value: "not_relevant", label: "Not relevant" },
  { value: "other", label: "Other" },
];

export default function ChatMessage({ message }: { message: MessageSchema }) {
  const [rating, setRating] = useState<"up" | "down" | null>(null);
  const [showReasons, setShowReasons] = useState(false);
  const [showShare, setShowShare] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isUser = message.role === "user";

  async function submitFeedback(value: "up" | "down", reason?: string) {
    setError(null);
    try {
      await api.post(`/api/messages/${message.id}/feedback`, { rating: value, reason });
      setRating(value);
      setShowReasons(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to submit feedback");
    }
  }

  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[75%] rounded-2xl rounded-br-sm bg-neutral-900 px-4 py-2.5 text-sm text-white dark:bg-white dark:text-neutral-900">
          {message.content}
        </div>
      </div>
    );
  }

  return (
    <div className="flex justify-start">
      <div className="max-w-[80%] rounded-2xl rounded-bl-sm border border-neutral-200 bg-white px-4 py-3 text-sm dark:border-neutral-800 dark:bg-neutral-900">
        <p className="whitespace-pre-wrap">{message.content}</p>

        {message.sources.length > 0 && (
          <div className="mt-3 space-y-2 border-t border-neutral-100 pt-2 dark:border-neutral-800">
            {message.sources.map((s, i) => (
              <div key={i} className="rounded-md bg-neutral-50 px-2.5 py-1.5 text-xs dark:bg-neutral-800/60">
                <div className="font-medium text-neutral-600 dark:text-neutral-300">{sourceLabel(s)}</div>
                <div className="mt-0.5 text-neutral-500 dark:text-neutral-400">&ldquo;{s.excerpt}&rdquo;</div>
              </div>
            ))}
          </div>
        )}

        <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-neutral-500">
          <button
            onClick={() => submitFeedback("up")}
            className={`rounded px-1.5 py-0.5 hover:bg-neutral-100 dark:hover:bg-neutral-800 ${rating === "up" ? "text-green-600" : ""}`}
          >
            👍 Helpful
          </button>
          <button
            onClick={() => setShowReasons((v) => !v)}
            className={`rounded px-1.5 py-0.5 hover:bg-neutral-100 dark:hover:bg-neutral-800 ${rating === "down" ? "text-red-600" : ""}`}
          >
            👎 Not helpful
          </button>
          <button onClick={() => setShowShare(true)} className="rounded px-1.5 py-0.5 hover:bg-neutral-100 dark:hover:bg-neutral-800">
            💬 Discuss with Group
          </button>
        </div>

        {showReasons && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {REASONS.map((r) => (
              <button
                key={r.value}
                onClick={() => submitFeedback("down", r.value)}
                className="rounded-full border border-neutral-200 px-2 py-0.5 text-[11px] hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-800"
              >
                {r.label}
              </button>
            ))}
          </div>
        )}

        {error && <p className="mt-2 text-xs text-red-600">{error}</p>}

        {showShare && <ShareToGroupModal messageId={message.id} onClose={() => setShowShare(false)} />}
      </div>
    </div>
  );
}

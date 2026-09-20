"use client";

import { useEffect, useState } from "react";
import RequireAuth from "@/components/RequireAuth";
import { api } from "@/lib/api";
import { FeedbackRow } from "@/lib/types";

// Render common answer formatting as React text nodes; never inject HTML.
function FeedbackAnswer({ text }: { text: string }) {
  const blocks = text.replace(/\s+- (?=\*\*)/g, "\n- ").split(/\n+/).filter((line) => line.trim());
  const inline = (line: string) => line.split(/(\*\*[^*]+\*\*)/g).map((part, index) =>
    part.startsWith("**") && part.endsWith("**")
      ? <strong key={index} className="font-semibold text-neutral-900">{part.slice(2, -2)}</strong>
      : part
  );
  return <div className="space-y-2 text-[13px] leading-5 text-neutral-600">
    {blocks.map((line, index) => /^\s*[-*]\s+/.test(line)
      ? <ul key={index} className="list-disc pl-5"><li>{inline(line.replace(/^\s*[-*]\s+/, ""))}</li></ul>
      : <p key={index} className="whitespace-pre-wrap">{inline(line)}</p>)}
  </div>;
}

function FeedbackContent() {
  const [rows, setRows] = useState<FeedbackRow[]>([]);

  useEffect(() => {
    api.get<FeedbackRow[]>("/api/feedback").then(setRows).catch(() => {});
  }, []);

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <h1 className="text-xl font-semibold">Feedback</h1>
      <p className="mt-1 text-sm text-neutral-500">
        Your ratings and feedback on assistant responses.
      </p>

      <div className="mt-6 space-y-4">
        {rows.map((f) => (
          <div key={f.id} className="rounded-lg border border-neutral-200 bg-white p-4 text-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${f.rating === "up" ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"}`}>
                {f.rating === "up" ? "Helpful" : "Not helpful"}
              </span>
              {f.reason && <span className="text-xs text-neutral-400">{f.reason.replace(/_/g, " ")}</span>}
            </div>
            {f.question && <div className="mt-3"><h2 className="mb-1 text-xs font-medium text-neutral-500">Question</h2><p className="text-sm font-medium leading-5">{f.question}</p></div>}
            {f.answer && <div className="mt-3 border-t border-neutral-100 pt-3"><h2 className="mb-2 text-xs font-medium text-neutral-500">Assistant response</h2><FeedbackAnswer text={f.answer} /></div>}
          </div>
        ))}
        {rows.length === 0 && <p className="text-sm text-neutral-400">No feedback submitted yet.</p>}
      </div>
    </div>
  );
}

export default function FeedbackPage() {
  return (
    <RequireAuth>
      <FeedbackContent />
    </RequireAuth>
  );
}

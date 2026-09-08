"use client";

import { useEffect, useState } from "react";
import RequireAuth from "@/components/RequireAuth";
import { api } from "@/lib/api";
import { FeedbackRow } from "@/lib/types";

function FeedbackContent() {
  const [rows, setRows] = useState<FeedbackRow[]>([]);

  useEffect(() => {
    api.get<FeedbackRow[]>("/api/feedback").then(setRows).catch(() => {});
  }, []);

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <h1 className="text-xl font-semibold">Feedback</h1>
      <p className="mt-1 text-sm text-neutral-500">
        Feedback you&apos;ve given on AI answers. This is used for retrieval/answer-quality
        evaluation — see docs/FEEDBACK_AND_EVALUATION.md — not to automatically retrain the model.
      </p>

      <div className="mt-6 space-y-2">
        {rows.map((f) => (
          <div key={f.id} className="rounded-lg border border-neutral-200 bg-white p-3 text-sm dark:border-neutral-800 dark:bg-neutral-900">
            <div className="flex items-center justify-between">
              <span className={f.rating === "up" ? "text-green-600" : "text-red-600"}>
                {f.rating === "up" ? "👍 Helpful" : "👎 Not helpful"}
              </span>
              {f.reason && <span className="text-xs text-neutral-400">{f.reason.replace(/_/g, " ")}</span>}
            </div>
            {f.question && <p className="mt-2 text-xs text-neutral-500">Q: {f.question}</p>}
            {f.answer && <p className="mt-1 text-xs text-neutral-600 dark:text-neutral-300">A: {f.answer}</p>}
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

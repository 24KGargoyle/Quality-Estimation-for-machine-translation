"use client";

import { useEffect, useState } from "react";
import RequireAuth from "@/components/RequireAuth";
import { api } from "@/lib/api";
import { MeetingSummary, SearchResult } from "@/lib/types";

function fmtTs(seconds: number) {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function SearchContent() {
  const [meetings, setMeetings] = useState<MeetingSummary[]>([]);
  const [meetingId, setMeetingId] = useState("");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get<MeetingSummary[]>("/api/meetings").then((ms) => {
      setMeetings(ms);
      if (ms.length > 0) setMeetingId(ms[0].id);
    });
  }, []);

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!meetingId || !query.trim()) return;
    setBusy(true);
    try {
      const res = await api.get<SearchResult[]>(
        `/api/meetings/${meetingId}/search?q=${encodeURIComponent(query)}`
      );
      setResults(res);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl px-4 py-8">
      <h1 className="text-xl font-semibold">Search</h1>
      <p className="mt-1 text-sm text-neutral-500">
        Hybrid keyword + semantic search over a single meeting&apos;s transcript, with no AI generation —
        just the raw ranked evidence.
      </p>

      <form onSubmit={handleSearch} className="mt-6 flex flex-col gap-3 sm:flex-row">
        <select
          className="rounded-md border border-neutral-300 px-3 py-2 text-sm dark:border-neutral-700 dark:bg-neutral-950"
          value={meetingId}
          onChange={(e) => setMeetingId(e.target.value)}
        >
          {meetings.map((m) => (
            <option key={m.id} value={m.id}>
              {m.title}
            </option>
          ))}
        </select>
        <input
          className="flex-1 rounded-md border border-neutral-300 px-3 py-2 text-sm dark:border-neutral-700 dark:bg-neutral-950"
          placeholder="Search this meeting…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <button
          type="submit"
          disabled={busy}
          className="rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-white dark:text-neutral-900"
        >
          Search
        </button>
      </form>

      <div className="mt-6 space-y-2">
        {results.map((r) => (
          <div key={r.chunk_id} className="rounded-lg border border-neutral-200 bg-white p-3 text-sm dark:border-neutral-800 dark:bg-neutral-900">
            <div className="text-xs font-medium text-neutral-500">
              {r.speaker || "Unknown"} · {fmtTs(r.start_seconds)}
            </div>
            <div className="mt-1">{r.text}</div>
          </div>
        ))}
        {results.length === 0 && <p className="text-sm text-neutral-400">No results yet.</p>}
      </div>
    </div>
  );
}

export default function SearchPage() {
  return (
    <RequireAuth>
      <SearchContent />
    </RequireAuth>
  );
}

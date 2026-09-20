"use client";

import { useEffect, useState } from "react";
import Icon from "@/components/Icon";
import RequireAuth from "@/components/RequireAuth";
import IntelligencePanel from "@/components/IntelligencePanel";
import { api } from "@/lib/api";
import { highlightEvidence } from "@/lib/highlight";
import { IntelligencePanel as IntelligencePanelData, MeetingSummary, SearchResult } from "@/lib/types";

function fmtTs(seconds: number) {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function resultLabel(r: SearchResult): string {
  if (r.file_type === "vtt") {
    return `${r.speaker || "Unknown"} · ${fmtTs(r.start_seconds)}`;
  }
  if (r.page_number != null) return `${r.source_file} · Page ${r.page_number}`;
  if (r.sheet_name) return `${r.source_file} · Sheet: ${r.sheet_name}`;
  if (r.slide_number != null) return `${r.source_file} · Slide ${r.slide_number}`;
  if (r.section) return `${r.source_file} · Section: ${r.section}`;
  return r.source_file ?? "Document";
}

function SearchContent() {
  const [meetings, setMeetings] = useState<MeetingSummary[]>([]);
  const [meetingId, setMeetingId] = useState("");
  const [query, setQuery] = useState("");
  const [lastQuery, setLastQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [intelligence, setIntelligence] = useState<IntelligencePanelData | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.get<MeetingSummary[]>("/api/meetings").then((ms) => {
      setMeetings(ms);
      if (ms.length > 0) setMeetingId(ms[0].id);
    }).catch(() => setError("Could not load meetings. Refresh to try again."));
  }, []);

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!meetingId || !query.trim()) return;
    setError(null);
    setBusy(true);
    try {
      const [searchRes, intelRes] = await Promise.all([
        api.get<SearchResult[]>(`/api/meetings/${meetingId}/search?q=${encodeURIComponent(query)}`),
        api.get<IntelligencePanelData>(`/api/meetings/${meetingId}/intelligence?q=${encodeURIComponent(query)}`),
      ]);
      setResults(searchRes);
      setIntelligence(intelRes);
      setLastQuery(query);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="search-page mx-auto max-w-7xl">
      <header className="search-heading"><h1>Search</h1><p>Choose a meeting and search its documents.</p></header>
      <form onSubmit={handleSearch} className="evidence-search">
        <div className="search-scope"><label htmlFor="search-meeting">LOOK IN</label>
        <select id="search-meeting"
          aria-label="Meeting to search"
          className="rounded-md border border-neutral-300 px-3 py-2 text-sm"
          value={meetingId}
          onChange={(e) => setMeetingId(e.target.value)}
        >
          {meetings.map((m) => (
            <option key={m.id} value={m.id}>
              {m.title}
            </option>
          ))}
        </select></div>
        <div className="search-query"><Icon name="search" size={22} />
        <input
          className="flex-1 rounded-md border border-neutral-300 px-3 py-2 text-sm"
          aria-label="Search this meeting…" placeholder="Search this meeting…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        </div><button
          type="submit"
          disabled={busy}
          className="rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {busy ? "Searching..." : "Find evidence"} <Icon name="arrow" size={17} />
        </button>
      </form>
      {error && <p role="alert" className="mt-3 text-sm text-red-600">{error}</p>}

      {lastQuery && <div className="search-results-layout">
        <div className="evidence-results"><div className="section-heading"><h2>{`Results for "${lastQuery}"`}</h2><span className="text-xs text-neutral-500">{results.length} results</span></div>
          {results.map((r) => (
            <div
              key={r.chunk_id}
              className="evidence-result"
            >
              <div className="text-xs font-medium text-neutral-500">{resultLabel(r)}</div>
              <div className="mt-1">{highlightEvidence(r.text, [lastQuery])}</div>
            </div>
          ))}
          {results.length === 0 && <p role="status" className="text-sm text-neutral-500">No results found. Try another phrase or meeting.</p>}
        </div>

        <IntelligencePanel data={intelligence} />
      </div>}
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

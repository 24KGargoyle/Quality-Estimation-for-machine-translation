"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import RequireAuth from "@/components/RequireAuth";
import { api, ApiError } from "@/lib/api";
import { MeetingDetail, MeetingSummary } from "@/lib/types";

function statusBadge(status: string) {
  const styles: Record<string, string> = {
    ready: "bg-green-100 text-green-700",
    pending: "bg-neutral-100 text-neutral-600",
    indexing: "bg-amber-100 text-amber-700",
    failed: "bg-red-100 text-red-700",
    no_transcript: "bg-neutral-100 text-neutral-500",
  };
  return styles[status] || styles.pending;
}

function MeetingsContent() {
  const router = useRouter();
  const [meetings, setMeetings] = useState<MeetingSummary[]>([]);
  const [meetingId, setMeetingId] = useState("");
  const [title, setTitle] = useState("");
  const [showManual, setShowManual] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function refresh() {
    api.get<MeetingSummary[]>("/api/meetings").then(setMeetings).catch(() => {});
  }

  useEffect(refresh, []);

  async function handleLoad(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const meeting = await api.post<MeetingDetail>("/api/meetings/load", {
        meeting_id: meetingId,
        title: title || undefined,
        transcript_vtt: showManual ? transcript : undefined,
      });
      router.push(`/meetings/${meeting.id}`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 503) {
        setError(
          "Microsoft Graph is not configured in this environment, so live Teams meeting lookup " +
            "is unavailable. Paste a transcript below to load this meeting manually."
        );
        setShowManual(true);
      } else {
        setError(err instanceof ApiError ? err.message : "Failed to load meeting");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="meetings-library-page mx-auto max-w-7xl">
      <p className="eyebrow">YOUR SHARED KNOWLEDGE</p><h1 className="text-xl font-semibold">The meeting library.</h1>
      <p className="mt-1 text-sm text-neutral-500">
        Enter a Teams Meeting ID to load its transcript and start asking questions.
      </p>

      <div className="meeting-library-layout"><form onSubmit={handleLoad} className="mt-6 rounded-xl border border-neutral-200 bg-white p-5">
        <h2 className="text-lg font-semibold mb-1">Bring a meeting in.</h2><p className="text-sm text-neutral-500 mb-6">Start with a Teams Meeting ID or a transcript.</p><div className="grid gap-4">
          <div>
            <label htmlFor="meetings-field-1" className="mb-1 block text-xs font-medium text-neutral-500">Meeting ID</label>
            <input id="meetings-field-1"
              className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm"
              value={meetingId}
              onChange={(e) => setMeetingId(e.target.value)}
              placeholder="123 456 789"
              required
            />
          </div>
          <div>
            <label htmlFor="meetings-field-2" className="mb-1 block text-xs font-medium text-neutral-500">Title (optional)</label>
            <input id="meetings-field-2"
              className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Architecture Discussion"
            />
          </div>
        </div>

        <button
          type="button"
          onClick={() => setShowManual((v) => !v)}
          className="mt-3 text-xs text-neutral-500 underline"
        >
          {showManual ? "Hide" : "This meeting's transcript isn't reachable via Graph — paste it manually"}
        </button>

        {showManual && (
          <textarea
            className="mt-2 h-32 w-full rounded-md border border-neutral-300 px-3 py-2 font-mono text-xs"
            value={transcript}
            onChange={(e) => setTranscript(e.target.value)}
            placeholder={"WEBVTT\n\n00:00:00.000 --> 00:00:05.000\n<v Speaker Name>What was said...</v>"}
          />
        )}

        {error && <p className="mt-3 text-xs text-amber-600">{error}</p>}

        <button
          type="submit"
          disabled={busy}
          className="mt-4 mx-auto block rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white hover:bg-neutral-800 disabled:opacity-50"
        >
          {busy ? "Loading…" : "Load meeting"}
        </button>
      </form>

      <div className="meeting-library-list"><div className="section-heading"><h2>All meetings</h2><span>{meetings.length} in your library</span></div>
        {meetings.map((m) => (
          <Link
            key={m.id}
            href={`/meetings/${m.id}`}
            className="flex items-center justify-between rounded-lg border border-neutral-200 bg-white px-4 py-3 hover:border-neutral-300"
          >
            <div>
              <div className="text-sm font-medium">{m.title}</div>
              <div className="text-xs text-neutral-500">
                Meeting ID {m.ms_meeting_id} · {m.participant_count} participants
                {m.duration_seconds ? ` · ${Math.round(m.duration_seconds / 60)} min` : ""}
              </div>
            </div>
            <span className={`rounded-full px-2 py-0.5 text-xs ${statusBadge(m.status)}`}>{m.status}</span>
          </Link>
        ))}
        {meetings.length === 0 && <p className="text-sm text-neutral-400">No meetings loaded yet.</p>}
      </div>
    </div></div>
  );
}

export default function MeetingsPage() {
  return (
    <RequireAuth>
      <MeetingsContent />
    </RequireAuth>
  );
}

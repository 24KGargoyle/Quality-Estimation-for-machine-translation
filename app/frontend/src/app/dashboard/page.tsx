"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import RequireAuth from "@/components/RequireAuth";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";
import { ConversationSummary, GroupSummary, MeetingSummary } from "@/lib/types";

function DashboardContent() {
  const { user } = useAuth();
  const [meetings, setMeetings] = useState<MeetingSummary[]>([]);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [groups, setGroups] = useState<GroupSummary[]>([]);

  useEffect(() => {
    api.get<MeetingSummary[]>("/api/meetings").then(setMeetings).catch(() => {});
    api.get<ConversationSummary[]>("/api/conversations").then(setConversations).catch(() => {});
    api.get<GroupSummary[]>("/api/groups").then(setGroups).catch(() => {});
  }, []);

  return (
    <div className="mx-auto max-w-6xl px-4 py-8">
      <h1 className="text-xl font-semibold">Welcome back, {user?.displayName}</h1>
      <p className="mt-1 text-sm text-neutral-500">
        Pick up a meeting, continue a chat, or jump into a group discussion.
      </p>

      <div className="mt-6 grid gap-4 sm:grid-cols-3">
        <Link
          href="/meetings"
          className="rounded-xl border border-neutral-200 bg-white p-5 shadow-sm transition hover:shadow dark:border-neutral-800 dark:bg-neutral-900"
        >
          <div className="text-2xl font-semibold">{meetings.length}</div>
          <div className="text-sm text-neutral-500">Meetings loaded</div>
        </Link>
        <Link
          href="/groups"
          className="rounded-xl border border-neutral-200 bg-white p-5 shadow-sm transition hover:shadow dark:border-neutral-800 dark:bg-neutral-900"
        >
          <div className="text-2xl font-semibold">{groups.length}</div>
          <div className="text-sm text-neutral-500">Groups you&apos;re in</div>
        </Link>
        <Link
          href="/feedback"
          className="rounded-xl border border-neutral-200 bg-white p-5 shadow-sm transition hover:shadow dark:border-neutral-800 dark:bg-neutral-900"
        >
          <div className="text-2xl font-semibold">{conversations.length}</div>
          <div className="text-sm text-neutral-500">Private conversations</div>
        </Link>
      </div>

      <div className="mt-8 grid gap-6 lg:grid-cols-2">
        <section>
          <h2 className="mb-3 text-sm font-semibold text-neutral-500">Recent meetings</h2>
          <div className="space-y-2">
            {meetings.slice(0, 5).map((m) => (
              <Link
                key={m.id}
                href={`/meetings/${m.id}`}
                className="block rounded-lg border border-neutral-200 bg-white px-4 py-3 text-sm hover:border-neutral-300 dark:border-neutral-800 dark:bg-neutral-900"
              >
                <div className="font-medium">{m.title}</div>
                <div className="text-xs text-neutral-500">
                  Meeting ID {m.ms_meeting_id} · {m.status}
                </div>
              </Link>
            ))}
            {meetings.length === 0 && (
              <p className="text-sm text-neutral-400">
                No meetings yet. <Link href="/meetings" className="underline">Load one</Link>.
              </p>
            )}
          </div>
        </section>

        <section>
          <h2 className="mb-3 text-sm font-semibold text-neutral-500">Recent conversations</h2>
          <div className="space-y-2">
            {conversations.slice(0, 5).map((c) => (
              <Link
                key={c.id}
                href={c.meeting_id ? `/meetings/${c.meeting_id}?conversation=${c.id}` : "/meetings"}
                className="block rounded-lg border border-neutral-200 bg-white px-4 py-3 text-sm hover:border-neutral-300 dark:border-neutral-800 dark:bg-neutral-900"
              >
                {c.title}
              </Link>
            ))}
            {conversations.length === 0 && (
              <p className="text-sm text-neutral-400">No conversations yet.</p>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

export default function DashboardPage() {
  return (
    <RequireAuth>
      <DashboardContent />
    </RequireAuth>
  );
}

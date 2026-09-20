"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import RequireAuth from "@/components/RequireAuth";
import { api } from "@/lib/api";
import { GroupSummary } from "@/lib/types";

function GroupsContent() {
  const [groups, setGroups] = useState<GroupSummary[]>([]);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function refresh() {
    api.get<GroupSummary[]>("/api/groups").then(setGroups).catch(() => {});
  }

  useEffect(refresh, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setError(null);
    setBusy(true);
    try {
      await api.post("/api/groups", { name });
      setName("");
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl px-4 py-8">
      <h1 className="text-xl font-semibold">Groups</h1>
      <p className="mt-1 text-sm text-neutral-500">
        Team conversations with each other and the AI — discuss shared meeting context, decide, and track action items.
      </p>

      <form onSubmit={handleCreate} className="mt-6 flex gap-2">
        <input
          className="flex-1 rounded-md border border-neutral-300 px-3 py-2 text-sm"
          aria-label="New group name…" placeholder="New group name…"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <button
          type="submit"
          disabled={busy}
          className="rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          Create
        </button>
      </form>
      {error && <p role="alert" className="mt-3 text-sm text-red-600">{error}</p>}

      <div className="mt-6 space-y-2">
        {groups.map((g) => (
          <Link
            key={g.id}
            href={`/groups/${g.id}`}
            className="flex items-center justify-between rounded-lg border border-neutral-200 bg-white px-4 py-3 hover:border-neutral-300"
          >
            <span className="text-sm font-medium">{g.name}</span>
            <span className="text-xs text-neutral-400">{g.member_count} members</span>
          </Link>
        ))}
        {groups.length === 0 && <p className="text-sm text-neutral-400">No groups yet.</p>}
      </div>
    </div>
  );
}

export default function GroupsPage() {
  return (
    <RequireAuth>
      <GroupsContent />
    </RequireAuth>
  );
}

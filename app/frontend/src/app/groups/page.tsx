"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import Icon from "@/components/Icon";
import RequireAuth from "@/components/RequireAuth";
import { api } from "@/lib/api";
import { GroupSummary } from "@/lib/types";

function GroupsContent() {
  const [groups, setGroups] = useState<GroupSummary[]>([]);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [deleting, setDeleting] = useState<string | null>(null);

  async function deleteGroup(group: GroupSummary) {
    if (!window.confirm(`Delete "${group.name}" and its group messages, discussions, decisions and action items? This cannot be undone. Imported meetings and Microsoft Teams groups are not deleted.`)) return;
    setDeleting(group.id);
    setError(null);
    try {
      await api.delete(`/api/groups/${group.id}`);
      setGroups((previous) => previous.filter((item) => item.id !== group.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete group");
    } finally { setDeleting(null); }
  }

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
          <div key={g.id} className="flex items-center gap-3 rounded-lg border border-neutral-200 bg-white px-4 py-3">
          <Link
            href={`/groups/${g.id}`}
            className="flex min-w-0 flex-1 items-center justify-between gap-3"
          >
            <span className="text-sm font-medium">{g.name}</span>
            <span className="text-xs text-neutral-400">{g.member_count} members</span>
          </Link>
          <button type="button" onClick={() => deleteGroup(g)} disabled={!!deleting}
            aria-label={deleting === g.id ? "Deleting group" : `Delete ${g.name}`} title="Delete group"
            className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-red-200 bg-red-50 text-red-700 transition-colors hover:bg-red-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-500 focus-visible:ring-offset-2 disabled:opacity-50">
            <Icon name="trash" size={18} />
          </button>
          </div>
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

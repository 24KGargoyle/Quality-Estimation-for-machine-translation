"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { GroupSummary } from "@/lib/types";

export default function ShareToGroupModal({
  messageId,
  onClose,
}: {
  messageId: string;
  onClose: () => void;
}) {
  const router = useRouter();
  const [groups, setGroups] = useState<GroupSummary[]>([]);
  const [newGroupName, setNewGroupName] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busyGroupId, setBusyGroupId] = useState<string | null>(null);

  useEffect(() => {
    api.get<GroupSummary[]>("/api/groups").then(setGroups).catch(() => {});
  }, []);

  async function share(groupId: string) {
    setBusyGroupId(groupId);
    setError(null);
    try {
      const res = await api.post<{ group_id: string; discussion_id: string }>(
        `/api/messages/${messageId}/share`,
        { group_id: groupId }
      );
      router.push(`/groups/${res.group_id}?discussion=${res.discussion_id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to share");
      setBusyGroupId(null);
    }
  }

  async function createAndShare(e: React.FormEvent) {
    e.preventDefault();
    if (!newGroupName.trim()) return;
    setCreating(true);
    setError(null);
    try {
      const group = await api.post<GroupSummary>("/api/groups", { name: newGroupName });
      await share(group.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create group");
      setCreating(false);
    }
  }

  return (
    <div className="fixed inset-0 z-20 flex items-center justify-center bg-black/40 px-4">
      <div className="w-full max-w-sm rounded-xl bg-white p-5 shadow-lg dark:bg-neutral-900">
        <h3 className="text-sm font-semibold">Discuss with Group</h3>
        <p className="mt-1 text-xs text-neutral-500">
          Select a group. Only the relevant context will be shared, with a link back to this meeting.
        </p>

        <div className="mt-3 max-h-48 space-y-1 overflow-y-auto">
          {groups.map((g) => (
            <button
              key={g.id}
              onClick={() => share(g.id)}
              disabled={busyGroupId === g.id}
              className="flex w-full items-center justify-between rounded-md border border-neutral-200 px-3 py-2 text-left text-sm hover:bg-neutral-50 disabled:opacity-50 dark:border-neutral-700 dark:hover:bg-neutral-800"
            >
              <span>{g.name}</span>
              <span className="text-xs text-neutral-400">{g.member_count} members</span>
            </button>
          ))}
          {groups.length === 0 && <p className="text-xs text-neutral-400">No groups yet.</p>}
        </div>

        <form onSubmit={createAndShare} className="mt-3 flex gap-2 border-t border-neutral-200 pt-3 dark:border-neutral-800">
          <input
            className="flex-1 rounded-md border border-neutral-300 px-2 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-950"
            placeholder="Create new group…"
            value={newGroupName}
            onChange={(e) => setNewGroupName(e.target.value)}
          />
          <button
            type="submit"
            disabled={creating}
            className="rounded-md bg-neutral-900 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50 dark:bg-white dark:text-neutral-900"
          >
            Create
          </button>
        </form>

        {error && <p className="mt-2 text-xs text-red-600">{error}</p>}

        <button onClick={onClose} className="mt-3 w-full text-center text-xs text-neutral-500 underline">
          Cancel
        </button>
      </div>
    </div>
  );
}

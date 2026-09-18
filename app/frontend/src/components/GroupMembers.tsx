"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";

type Members = {
  members: { id: string; display_name: string; email: string }[];
  can_manage: boolean;
};

export default function GroupMembers({ groupId }: { groupId: string }) {
  const [data, setData] = useState<Members | null>(null);
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    api.get<Members>(`/api/groups/${groupId}/members`)
      .then((result) => { if (active) setData(result); })
      .catch((err) => { if (active) setError(err instanceof ApiError ? err.message : "Unable to load members"); });
    return () => { active = false; };
  }, [groupId]);

  async function addMember(event: React.FormEvent) {
    event.preventDefault();
    if (!email.trim() || busy) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const alreadyMember = data?.members.some((m) => m.email.toLowerCase() === email.trim().toLowerCase());
      const result = await api.post<Members>(`/api/groups/${groupId}/members`, { email: email.trim() });
      setData(result);
      setEmail("");
      setNotice(alreadyMember ? "This person is already a member." : "Member added.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to add member");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-xl border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-900">
      <h3 className="text-sm font-semibold">Members{data ? ` (${data.members.length})` : ""}</h3>
      {!data && !error && <p className="mt-2 text-xs text-neutral-500">Loading members...</p>}
      <ul className="mt-2 max-h-64 space-y-3 overflow-auto text-sm">
        {data?.members.map((member) => (
          <li key={member.id}>
            <div>{member.display_name}</div>
            <div className="break-all text-xs text-neutral-500">{member.email}</div>
          </li>
        ))}
      </ul>
      {data?.can_manage && (
        <form onSubmit={addMember} className="mt-4 space-y-2">
          <label htmlFor="member-email" className="block text-xs font-medium">Add member by email</label>
          <input id="member-email" type="email" required maxLength={320} value={email}
            onChange={(event) => setEmail(event.target.value)} disabled={busy}
            placeholder="colleague@company.com"
            className="w-full rounded-md border border-neutral-300 bg-white p-2 text-sm dark:border-neutral-700 dark:bg-neutral-950" />
          <p className="text-xs text-neutral-500">They must have signed in to the same organization. Added members can read existing group messages.</p>
          <button disabled={busy || !email.trim()} className="w-full rounded-md bg-neutral-900 px-3 py-2 text-sm text-white disabled:opacity-50 dark:bg-white dark:text-neutral-900">
            {busy ? "Adding..." : "Add member"}
          </button>
        </form>
      )}
      {data && !data.can_manage && <p className="mt-3 text-xs text-neutral-500">Ask the group creator or an administrator to add members.</p>}
      {error && <p role="alert" className="mt-2 text-xs text-red-600">{error}</p>}
      {notice && <p role="status" className="mt-2 text-xs text-green-600">{notice}</p>}
    </section>
  );
}

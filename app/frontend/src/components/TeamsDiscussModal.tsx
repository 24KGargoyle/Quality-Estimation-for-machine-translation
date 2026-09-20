"use client";

import { useEffect, useState } from "react";
import Dialog from "./Dialog";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import {
  CreateTeamsGroupResponse,
  FindTeamsGroupResponse,
  ResolvedParticipant,
  SendTeamsDiscussionResponse,
  SourceSchema,
} from "@/lib/types";

type Step = "loading" | "unavailable" | "existing" | "create" | "confirm-create" | "sent" | "error";

export default function TeamsDiscussModal({
  meetingId,
  messageId,
  question,
  answer,
  evidence,
  onClose,
}: {
  meetingId: string;
  messageId: string;
  question: string;
  answer: string;
  evidence?: SourceSchema;
  onClose: () => void;
}) {
  const router = useRouter();
  const [step, setStep] = useState<Step>("loading");
  const [find, setFind] = useState<FindTeamsGroupResponse | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [topic, setTopic] = useState(question.length > 60 ? question.slice(0, 60) + "…" : question);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sentGroupId, setSentGroupId] = useState<string | null>(null);

  useEffect(() => {
    api
      .post<FindTeamsGroupResponse>("/api/discussions/find-teams-group", { meeting_id: meetingId })
      .then((res) => {
        setFind(res);
        if (!res.teams_available) {
          setStep("unavailable");
        } else if (res.existing_group) {
          setStep("existing");
        } else {
          setSelected(new Set(res.participants.filter((p) => p.resolved && p.user_id).map((p) => p.user_id!)));
          setStep("create");
        }
      })
      .catch((err) => {
        setError(err instanceof ApiError ? err.message : "Failed to look up Teams groups");
        setStep("error");
      });
  }, [meetingId]);

  const summary = answer.length > 220 ? answer.slice(0, 220) + "…" : answer;

  function toggleParticipant(userId: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(userId)) next.delete(userId);
      else next.add(userId);
      return next;
    });
  }

  async function sendDiscussion(groupId: string) {
    setBusy(true);
    setError(null);
    try {
      const res = await api.post<SendTeamsDiscussionResponse>("/api/discussions/send-teams-discussion", {
        meeting_id: meetingId,
        confirmed: true,
        message_id: messageId,
        group_id: groupId,
        recipient_user_ids: find?.existing_group?.member_ids ?? [],
        topic,
        summary,
        question,
        evidence_speaker: evidence?.document_type === "transcript" ? evidence.speaker : undefined,
        evidence_timestamp: evidence?.document_type === "transcript" ? evidence.start_timestamp : undefined,
        evidence_excerpt: evidence?.excerpt,
        evidence_source_file: evidence?.source_file ?? undefined,
        evidence_location: evidence
          ? evidence.page_number != null
            ? `Page ${evidence.page_number}`
            : evidence.sheet_name
              ? `Sheet: ${evidence.sheet_name}`
              : evidence.slide_number != null
                ? `Slide ${evidence.slide_number}`
                : evidence.section ?? undefined
          : undefined,
      });
      setSentGroupId(groupId);
      void res;
      setStep("sent");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to send discussion");
    } finally {
      setBusy(false);
    }
  }

  async function createAndSend() {
    setBusy(true);
    setError(null);
    try {
      const created = await api.post<CreateTeamsGroupResponse>("/api/discussions/create-teams-group", {
        meeting_id: meetingId,
        confirmed: true,
        message_id: messageId,
        participant_user_ids: Array.from(selected),
        topic,
      });
      setFind({ teams_available: true, unavailable_reason: null, participants: find?.participants ?? [], application_group_id: created.application_group_id, existing_group: { chat_id: created.teams_chat_id, topic: created.topic, member_names: created.member_names, member_ids: created.member_ids, match_kind: "created" } });
      setStep("existing");
      setBusy(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create the Teams group");
      setBusy(false);
    }
  }

  const resolvableParticipants = (find?.participants ?? []).filter((p): p is ResolvedParticipant & { user_id: string } =>
    Boolean(p.resolved && p.user_id)
  );
  const unresolvedParticipants = (find?.participants ?? []).filter((p) => !p.resolved);

  return (
    <Dialog label="Discuss in Microsoft Teams" onClose={onClose}>
      <div className="w-full max-w-md rounded-xl bg-white p-5 shadow-lg">
        <h3 className="text-sm font-semibold">Discuss with Group (Microsoft Teams)</h3>

        {step === "loading" && <p className="mt-3 text-xs text-neutral-500">Looking up meeting participants…</p>}

        {step === "unavailable" && (
          <div className="mt-3 space-y-3">
            <p className="text-xs text-amber-600">{find?.unavailable_reason}</p>
            {find && find.participants.length > 0 && (
              <div>
                <div className="text-xs font-medium text-neutral-500">Meeting participants (unresolved)</div>
                <ul className="mt-1 space-y-0.5 text-xs text-neutral-500">
                  {find.participants.map((p) => (
                    <li key={p.display_name}>• {p.display_name}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {step === "existing" && find?.existing_group && (
          <div className="mt-3 space-y-3">
            <p className="text-xs text-neutral-500">Confirm sending this answer and its references to:</p>
            <p className="max-h-40 overflow-y-auto whitespace-pre-wrap text-xs">{answer}</p>
            <p className="text-sm font-medium">{find.existing_group.topic || "Untitled Teams chat"}</p>
            <div>
              <div className="text-xs font-medium text-neutral-500">Members</div>
              <ul className="mt-1 flex flex-wrap gap-1.5">
                {find.existing_group.member_names.map((n) => (
                  <li key={n} className="rounded-full bg-neutral-100 px-2 py-0.5 text-xs">
                    {n}
                  </li>
                ))}
              </ul>
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => find.application_group_id && router.push(`/groups/${find.application_group_id}`)}
                className="flex-1 rounded-md border border-neutral-300 px-3 py-1.5 text-xs hover:bg-neutral-50"
              >
                Open Group
              </button>
              <button
                onClick={() => find.application_group_id && sendDiscussion(find.application_group_id)}
                disabled={busy || !find.application_group_id}
                className="flex-1 rounded-md bg-neutral-900 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
              >
                {busy ? "Sending…" : "Send Discussion"}
              </button>
            </div>
          </div>
        )}

        {step === "create" && (
          <div className="mt-3 space-y-3">
            <p className="text-xs text-neutral-500">No existing Teams group was found for the meeting participants.</p>
            <div>
              <label htmlFor="teams-topic" className="mb-1 block text-xs font-medium text-neutral-500">Topic</label>
              <input
                className="w-full rounded-md border border-neutral-300 px-2 py-1.5 text-sm"
                id="teams-topic"
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
              />
            </div>
            <div>
              <div className="text-xs font-medium text-neutral-500">Participants</div>
              <ul className="mt-1 max-h-40 space-y-1 overflow-y-auto">
                {resolvableParticipants.map((p) => (
                  <li key={p.user_id}>
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={selected.has(p.user_id)}
                        onChange={() => toggleParticipant(p.user_id)}
                      />
                      {p.display_name}
                    </label>
                  </li>
                ))}
              </ul>
              {unresolvedParticipants.length > 0 && (
                <p className="mt-1 text-xs text-neutral-400">
                  {unresolvedParticipants.length} participant(s) couldn&apos;t be matched to a Microsoft Teams
                  identity and are excluded: {unresolvedParticipants.map((p) => p.display_name).join(", ")}.
                </p>
              )}
            </div>
            <button
              onClick={() => setStep("confirm-create")}
              disabled={selected.size === 0}
              className="w-full rounded-md bg-neutral-900 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
            >
              Create Teams Group
            </button>
          </div>
        )}

        {step === "confirm-create" && (
          <div className="mt-3 space-y-3">
            <p className="text-xs text-neutral-500">Create Teams discussion group?</p>
            <div>
              <div className="text-xs font-medium text-neutral-500">Members</div>
              <p className="text-sm">
                {resolvableParticipants
                  .filter((p) => selected.has(p.user_id))
                  .map((p) => p.display_name)
                  .join(", ")}
              </p>
            </div>
            <div>
              <div className="text-xs font-medium text-neutral-500">Message</div>
              <pre className="mt-1 whitespace-pre-wrap rounded-md bg-neutral-50 p-2 text-xs">
                {`Topic: ${topic}\n\nSummary: ${summary}\n\nDiscussion question: ${question}`}
              </pre>
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => setStep("create")}
                className="flex-1 rounded-md border border-neutral-300 px-3 py-1.5 text-xs hover:bg-neutral-50"
              >
                Back
              </button>
              <button
                onClick={createAndSend}
                disabled={busy}
                className="flex-1 rounded-md bg-neutral-900 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
              >
                {busy ? "Creating…" : "Confirm creation"}
              </button>
            </div>
          </div>
        )}

        {step === "sent" && (
          <div className="mt-3 space-y-3">
            <p className="text-sm text-green-600">Discussion sent to Microsoft Teams.</p>
            {sentGroupId && (
              <button
                onClick={() => router.push(`/groups/${sentGroupId}`)}
                className="w-full rounded-md bg-neutral-900 px-3 py-1.5 text-xs font-medium text-white"
              >
                Open Group
              </button>
            )}
          </div>
        )}

        {step === "error" && <p className="mt-3 text-xs text-red-600">{error}</p>}
        {error && step !== "error" && <p className="mt-2 text-xs text-red-600">{error}</p>}

        <button onClick={onClose} className="mt-4 w-full text-center text-xs text-neutral-500 underline">
          Close
        </button>
      </div>
    </Dialog>
  );
}

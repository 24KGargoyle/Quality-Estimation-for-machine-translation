"use client";

import { useEffect, useRef, useState } from "react";
import RequireAuth from "@/components/RequireAuth";
import Icon from "@/components/Icon";
import { api, ApiError } from "@/lib/api";
import { ImportedFileResultSchema, ImportJobResults, ImportJobSummary } from "@/lib/types";

const SUPPORTED_EXTENSIONS = ["vtt", "txt", "docx", "doc", "xlsx", "xls", "pdf", "pptx", "csv"];
const MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024;
type ImportFormat = { extension: string; ready: boolean; note: string | null; max_bytes: number };

function skipReason(file: File, formats: ImportFormat[]): string | null {
  const format = formats.find((f) => f.extension === extOf(file.name));
  if (!format) return "Unsupported file type";
  if (file.size > format.max_bytes) return `Exceeds the ${format.max_bytes / (1024 * 1024)} MB per-file limit`;
  return null;
}

function extOf(name: string): string {
  const parts = name.split(".");
  return parts.length > 1 ? parts[parts.length - 1].toLowerCase() : "";
}

function relativePathOf(file: File): string {
  // webkitRelativePath is set by <input webkitdirectory> folder selection;
  // falls back to the plain filename for a manual multi-file selection.
  const anyFile = file as File & { webkitRelativePath?: string };
  return anyFile.webkitRelativePath || file.name;
}

function detectCounts(files: File[], formats: ImportFormat[]): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const f of files) {
    const ext = extOf(f.name);
    const key = formats.some((f) => f.extension === ext) ? ext : "unsupported";
    counts[key] = (counts[key] || 0) + 1;
  }
  return counts;
}

function importTime(value: string): string {
  // SQLite timestamps are UTC but older API responses omit the timezone.
  const utc = /(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? value : `${value.replace(" ", "T")}Z`;
  return new Date(utc).toLocaleString(undefined, { timeZoneName: "short" });
}

function statusColor(status: string): string {
  const styles: Record<string, string> = {
    success: "text-green-600",
    duplicate: "text-neutral-500",
    skipped: "text-amber-600",
    failed: "text-red-600",
  };
  return styles[status] || "text-neutral-500";
}

function jobStatusBadge(status: string): string {
  const styles: Record<string, string> = {
    completed: "bg-green-100 text-green-700",
    completed_with_warnings: "bg-amber-100 text-amber-700",
    failed: "bg-red-100 text-red-700",
    processing: "bg-blue-100 text-blue-700",
    queued: "bg-neutral-100 text-neutral-600",
  };
  return styles[status] || styles.queued;
}

function ImportContent() {
  const [formats, setFormats] = useState<ImportFormat[]>(SUPPORTED_EXTENSIONS.map((extension) => ({
    extension, ready: true, note: null, max_bytes: MAX_FILE_SIZE_BYTES,
  })));
  useEffect(() => {
    api.get<{ formats: ImportFormat[] }>("/api/historical-imports/capabilities")
      .then((data) => setFormats(data.formats))
      .catch(() => {});
  }, []);
  const folderInputRef = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [job, setJob] = useState<ImportJobSummary | null>(null);
  const [results, setResults] = useState<ImportedFileResultSchema[] | null>(null);
  const [history, setHistory] = useState<ImportJobSummary[]>([]);
  const [historyResults, setHistoryResults] = useState<Record<string, ImportedFileResultSchema[]>>({});
  const [expandedJob, setExpandedJob] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);

  async function deleteImport(item: ImportJobSummary) {
    if (!window.confirm(`Delete the import from ${importTime(item.created_at)}? Files originally imported by this batch and their search entries will be permanently removed. Duplicate-only batches remove only history. Existing meetings and chats remain. You can upload the files again afterward.`)) return;
    setDeleting(item.id);
    setError(null);
    try {
      await api.delete(`/api/historical-imports/${item.id}`);
      setHistory((previous) => previous.filter((entry) => entry.id !== item.id));
      setHistoryResults((previous) => {
        const next = { ...previous };
        delete next[item.id];
        return next;
      });
      if (expandedJob === item.id) setExpandedJob(null);
      if (job?.id === item.id) { setJob(null); setResults(null); }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to delete import");
    } finally {
      setDeleting(null);
    }
  }

  useEffect(() => {
    // webkitdirectory/directory have no typed React prop — set imperatively.
    if (folderInputRef.current) {
      folderInputRef.current.setAttribute("webkitdirectory", "");
      folderInputRef.current.setAttribute("directory", "");
    }
  }, []);

  function refreshHistory() {
    api.get<ImportJobSummary[]>("/api/historical-imports").then(setHistory).catch(() => {});
  }

  useEffect(refreshHistory, []);

  // Keep history and expanded results live, including after a page reload.
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    async function refreshProgress() {
      try {
        const latest = await api.get<ImportJobSummary[]>("/api/historical-imports");
        if (cancelled) return;
        setHistory(latest);
        setJob((current) => current ? latest.find((item) => item.id === current.id) ?? current : current);
        if (expandedJob) {
          const full = await api.get<ImportJobResults>(`/api/historical-imports/${expandedJob}/results`);
          if (!cancelled) setHistoryResults((previous) => ({ ...previous, [expandedJob]: full.results }));
        }
      } catch {
        // A temporary connection failure must not permanently stop polling.
      } finally {
        if (!cancelled) timer = setTimeout(refreshProgress, 3000);
      }
    }
    timer = setTimeout(refreshProgress, 3000);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [expandedJob]);

  function handleSelectFolder(e: React.ChangeEvent<HTMLInputElement>) {
    const selected = Array.from(e.target.files || []);
    setFiles(selected);
    setJob(null);
    setResults(null);
    setError(null);
  }

  async function pollJob(jobId: string) {
    for (;;) {
      await new Promise((r) => setTimeout(r, 1000));
      try {
        const current = await api.get<ImportJobSummary>(`/api/historical-imports/${jobId}`);
        setJob(current);
        setError(null);
        if (current.status !== "queued" && current.status !== "processing") {
          const full = await api.get<ImportJobResults>(`/api/historical-imports/${jobId}/results`);
          setResults(full.results);
          refreshHistory();
          return;
        }
      } catch (err) {
        if (err instanceof ApiError && [401, 403, 404].includes(err.status)) {
          setError(err.message);
          setJob(null);
          return;
        }
        setError("Connection interrupted. Retrying progress updates?");
        await new Promise((resolve) => setTimeout(resolve, 3000));
      }
    }
  }

  async function handleUpload() {
    if (importableFiles.length === 0) return;
    setBusy(true);
    setError(null);
    setResults(null);
    try {
      const formData = new FormData();
      for (const f of importableFiles) {
        formData.append("files", f, relativePathOf(f));
      }
      const created = await api.upload<ImportJobSummary>("/api/historical-imports", formData);
      setJob(created);
      await pollJob(created.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to start import");
    } finally {
      setBusy(false);
    }
  }

  async function toggleHistoryDetail(jobId: string) {
    if (expandedJob === jobId) {
      setExpandedJob(null);
      return;
    }
    setExpandedJob(jobId);
    if (!historyResults[jobId]) {
      try {
        const full = await api.get<ImportJobResults>(`/api/historical-imports/${jobId}/results`);
        setHistoryResults((prev) => ({ ...prev, [jobId]: full.results }));
      } catch {
        // ignore
      }
    }
  }

  const counts = detectCounts(files, formats);
  const importableFiles = files.filter((file) => !skipReason(file, formats))
    .sort((a, b) => relativePathOf(a).localeCompare(relativePathOf(b)));
  const skippedFiles = files.filter((file) => skipReason(file, formats));
  const setupNeeded = formats.filter((format) => !format.ready && files.some((file) => extOf(file.name) === format.extension));
  const inProgress = job && (job.status === "queued" || job.status === "processing");

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <h1 className="text-xl font-semibold">Historical Meeting Data</h1>
      <p className="mt-1 text-sm text-neutral-500">
        Upload a folder containing Teams transcripts and supporting meeting documents (Word, Excel,
        PDF, PowerPoint, email, audio, video, text, CSV, and ZIP archives). Files are grouped into meetings automatically —
        everything in the same folder becomes one meeting.
      </p>

      <div className="mt-6 rounded-xl border border-neutral-200 bg-white p-5">
        <input
          ref={folderInputRef}
          type="file"
          multiple
          disabled={busy || !!inProgress}
          onChange={handleSelectFolder}
          className="block w-full text-sm text-neutral-600 file:mr-4 file:rounded-md file:border-0 file:bg-neutral-900 file:px-4 file:py-2 file:text-sm file:font-medium file:text-white hover:file:bg-neutral-800"
        />

        {files.length > 0 && (
          <div className="mt-4 rounded-lg border border-neutral-200 p-3 text-sm">
            <div className="font-medium">Files detected: {files.length}</div>
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-neutral-500">
              {Object.entries(counts).map(([type, count]) => (
                <span key={type}>
                  {type === "unsupported" ? "Unsupported" : type.toUpperCase()}: {count}
                </span>
              ))}
            </div>
            <p className="mt-3">Accepted for upload: {importableFiles.length}. Skipped before upload: {skippedFiles.length}.</p>
            {setupNeeded.map((format) => <p className="mt-2 text-amber-700" key={format.extension}>
              {format.extension.toUpperCase()}: {format.note} These files cannot be searched until processing succeeds.
            </p>)}
            {skippedFiles.length > 0 && (
              <details className="mt-2 text-amber-700">
                <summary className="cursor-pointer">View skipped files</summary>
                <ul className="mt-2 max-h-48 overflow-auto space-y-1 break-all">
                  {skippedFiles.map((file, index) => (
                    <li key={`${relativePathOf(file)}-${index}`}>
                      {relativePathOf(file)}: {skipReason(file, formats)}
                    </li>
                  ))}
                </ul>
              </details>
            )}
            <p className="mt-2 text-neutral-500">Documents: up to 50 MB each. Audio/video: up to 500 MB each. Recordings are transcribed; video frames are not analyzed.</p>
          </div>
        )}

        {error && <p className="mt-3 text-xs text-red-600">{error}</p>}

        <button
          onClick={handleUpload}
          disabled={importableFiles.length === 0 || busy || !!inProgress}
          className="mt-4 ml-auto block rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white hover:bg-neutral-800 disabled:opacity-50"
        >
          {busy || inProgress ? "Processing…" : "Upload & Process"}
        </button>
      </div>

      {job && (
        <div className="mt-6 rounded-xl border border-neutral-200 bg-white p-5">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold">
              {inProgress ? "Processing" : "Import completed"}
            </h2>
            <span className={`rounded-full px-2 py-0.5 text-xs ${jobStatusBadge(job.status)}`}>{job.status}</span>
          </div>
          <div className="mt-2 text-sm text-neutral-600">
            {inProgress
              ? `Processing: ${job.processed_files} / ${job.total_files}`
              : `Total: ${job.total_files}`}
          </div>
          <div className="mt-1 flex gap-4 text-xs text-neutral-500">
            <span>Successful: {job.successful_files}</span>
            <span>Skipped: {job.skipped_files}</span>
            <span>Failed: {job.failed_files}</span>
          </div>
          {inProgress && job.current_file && (
            <div className="mt-2 text-xs text-neutral-400">Current: {job.current_file}</div>
          )}

          {results && (
            <div className="import-file-list mt-4" tabIndex={0} aria-label="Import file results">
              <table className="w-full text-left text-xs">
                <thead className="text-neutral-400">
                  <tr>
                    <th className="py-1 pr-3">File</th>
                    <th className="py-1 pr-3">Type</th>
                    <th className="py-1 pr-3">Status</th>
                    <th className="py-1 pr-3">Reason</th>
                    <th className="py-1">Recommended action</th>
                  </tr>
                </thead>
                <tbody>
                  {results.map((r, i) => (
                    <tr key={i} className="border-t border-neutral-100">
                      <td className="py-1.5 pr-3"><div title={r.relative_path}>{r.relative_path}</div></td>
                      <td className="py-1.5 pr-3">{r.file_type}</td>
                      <td className={`py-1.5 pr-3 font-medium ${statusColor(r.status)}`}>{r.status}</td>
                      <td className="py-1.5 pr-3 text-neutral-500">{r.reason || "—"}</td>
                      <td className="py-1.5 text-neutral-500">{r.recommended_action || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      <div className="mt-8">
        <h2 className="text-sm font-semibold text-neutral-500">Import History</h2>
        <div className="mt-2 space-y-2">
          {history.map((h) => (
            <div key={h.id} className="rounded-lg border border-neutral-200 bg-white">
              <div className="flex items-center gap-3 p-4">
              <button
                onClick={() => toggleHistoryDetail(h.id)}
                className="flex min-w-0 flex-1 flex-wrap items-center justify-between gap-3 rounded-md text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
              >
                <div className="text-sm">
                  <div className="font-medium">
                    {importTime(h.created_at)} · {h.created_by}
                  </div>
                  <div className="text-xs text-neutral-500">
                    Total {h.total_files} · Successful {h.successful_files} · Skipped {h.skipped_files} · Failed{" "}
                    {h.failed_files}
                  </div>
                  {["queued", "processing"].includes(h.status) && (
                    <div className="mt-1 text-xs text-blue-700" role="status">
                      Processed {h.processed_files} of {h.total_files} files ? {Math.max(0, h.total_files - h.processed_files)} remaining.
                      {" "}Audio/video transcription may take longer.
                    </div>
                  )}
                </div>
                <span className={`rounded-full px-2 py-0.5 text-xs ${jobStatusBadge(h.status)}`}>{h.status}</span>
              </button>
              <button
                type="button"
                onClick={() => deleteImport(h)}
                disabled={!!deleting || busy || history.some((entry) => ["queued", "processing"].includes(entry.status))}
                className="inline-flex min-h-10 shrink-0 items-center justify-center gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm font-semibold text-red-700 shadow-sm transition-colors hover:border-red-300 hover:bg-red-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                aria-label={`Delete import from ${importTime(h.created_at)}`}
                title="Delete import"
              ><Icon name="trash" size={18} />{deleting === h.id ? "Deleting…" : "Delete"}</button>
              </div>
              {expandedJob === h.id && historyResults[h.id] && (
                <div className="import-file-list border-t border-neutral-100" tabIndex={0} aria-label="Imported files">
                  <table className="w-full text-left text-xs">
                    <thead className="text-neutral-400">
                      <tr>
                        <th className="py-1 pr-3">File</th>
                        <th className="py-1 pr-3">Status</th>
                        <th className="py-1">Reason</th>
                      </tr>
                    </thead>
                    <tbody>
                      {historyResults[h.id].map((r, i) => (
                        <tr key={i} className="border-t border-neutral-100">
                          <td className="py-1.5 pr-3"><div title={r.relative_path}>{r.relative_path}</div></td>
                          <td className={`py-1.5 pr-3 font-medium ${statusColor(r.status)}`}>{r.status}</td>
                          <td className="py-1.5 text-neutral-500">{r.reason || "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          ))}
          {history.length === 0 && <p className="text-sm text-neutral-400">No imports yet.</p>}
        </div>
      </div>
    </div>
  );
}

export default function HistoricalImportPage() {
  return (
    <RequireAuth>
      <ImportContent />
    </RequireAuth>
  );
}

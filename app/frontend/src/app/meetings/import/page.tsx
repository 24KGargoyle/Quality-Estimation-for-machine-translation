"use client";

import { useEffect, useRef, useState } from "react";
import RequireAuth from "@/components/RequireAuth";
import { api, ApiError } from "@/lib/api";
import { ImportedFileResultSchema, ImportJobResults, ImportJobSummary } from "@/lib/types";

const SUPPORTED_EXTENSIONS = ["vtt", "txt", "docx", "doc", "xlsx", "xls", "pdf", "pptx", "csv"];

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

function detectCounts(files: File[]): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const f of files) {
    const ext = extOf(f.name);
    const key = SUPPORTED_EXTENSIONS.includes(ext) ? ext : "unsupported";
    counts[key] = (counts[key] || 0) + 1;
  }
  return counts;
}

function statusColor(status: string): string {
  const styles: Record<string, string> = {
    success: "text-green-600 dark:text-green-400",
    duplicate: "text-neutral-500",
    skipped: "text-amber-600 dark:text-amber-400",
    failed: "text-red-600 dark:text-red-400",
  };
  return styles[status] || "text-neutral-500";
}

function jobStatusBadge(status: string): string {
  const styles: Record<string, string> = {
    completed: "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300",
    completed_with_warnings: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
    failed: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300",
    processing: "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300",
    queued: "bg-neutral-100 text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300",
  };
  return styles[status] || styles.queued;
}

function ImportContent() {
  const folderInputRef = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [job, setJob] = useState<ImportJobSummary | null>(null);
  const [results, setResults] = useState<ImportedFileResultSchema[] | null>(null);
  const [history, setHistory] = useState<ImportJobSummary[]>([]);
  const [historyResults, setHistoryResults] = useState<Record<string, ImportedFileResultSchema[]>>({});
  const [expandedJob, setExpandedJob] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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
        if (current.status !== "queued" && current.status !== "processing") {
          const full = await api.get<ImportJobResults>(`/api/historical-imports/${jobId}/results`);
          setResults(full.results);
          refreshHistory();
          return;
        }
      } catch {
        return;
      }
    }
  }

  async function handleUpload() {
    if (files.length === 0) return;
    setBusy(true);
    setError(null);
    setResults(null);
    try {
      const formData = new FormData();
      for (const f of files) {
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

  const counts = detectCounts(files);
  const inProgress = job && (job.status === "queued" || job.status === "processing");

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <h1 className="text-xl font-semibold">Historical Meeting Data</h1>
      <p className="mt-1 text-sm text-neutral-500">
        Upload a folder containing Teams transcripts and supporting meeting documents (Word, Excel,
        PDF, PowerPoint, text, and CSV files). Files are grouped into meetings automatically —
        everything in the same folder becomes one meeting.
      </p>

      <div className="mt-6 rounded-xl border border-neutral-200 bg-white p-5 dark:border-neutral-800 dark:bg-neutral-900">
        <input
          ref={folderInputRef}
          type="file"
          multiple
          onChange={handleSelectFolder}
          className="block w-full text-sm text-neutral-600 file:mr-4 file:rounded-md file:border-0 file:bg-neutral-900 file:px-4 file:py-2 file:text-sm file:font-medium file:text-white hover:file:bg-neutral-800 dark:text-neutral-300 dark:file:bg-white dark:file:text-neutral-900"
        />

        {files.length > 0 && (
          <div className="mt-4 rounded-lg border border-neutral-200 p-3 text-sm dark:border-neutral-800">
            <div className="font-medium">Files detected: {files.length}</div>
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-neutral-500">
              {Object.entries(counts).map(([type, count]) => (
                <span key={type}>
                  {type === "unsupported" ? "Unsupported" : type.toUpperCase()}: {count}
                </span>
              ))}
            </div>
          </div>
        )}

        {error && <p className="mt-3 text-xs text-red-600 dark:text-red-400">{error}</p>}

        <button
          onClick={handleUpload}
          disabled={files.length === 0 || busy || !!inProgress}
          className="mt-4 rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white hover:bg-neutral-800 disabled:opacity-50 dark:bg-white dark:text-neutral-900"
        >
          {busy || inProgress ? "Processing…" : "Upload & Process"}
        </button>
      </div>

      {job && (
        <div className="mt-6 rounded-xl border border-neutral-200 bg-white p-5 dark:border-neutral-800 dark:bg-neutral-900">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold">
              {inProgress ? "Processing" : "Import completed"}
            </h2>
            <span className={`rounded-full px-2 py-0.5 text-xs ${jobStatusBadge(job.status)}`}>{job.status}</span>
          </div>
          <div className="mt-2 text-sm text-neutral-600 dark:text-neutral-300">
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
            <div className="mt-4 overflow-x-auto">
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
                    <tr key={i} className="border-t border-neutral-100 dark:border-neutral-800">
                      <td className="py-1.5 pr-3">{r.relative_path}</td>
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
            <div key={h.id} className="rounded-lg border border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900">
              <button
                onClick={() => toggleHistoryDetail(h.id)}
                className="flex w-full items-center justify-between px-4 py-3 text-left"
              >
                <div className="text-sm">
                  <div className="font-medium">
                    {new Date(h.created_at).toLocaleString()} · {h.created_by}
                  </div>
                  <div className="text-xs text-neutral-500">
                    Total {h.total_files} · Successful {h.successful_files} · Skipped {h.skipped_files} · Failed{" "}
                    {h.failed_files}
                  </div>
                </div>
                <span className={`rounded-full px-2 py-0.5 text-xs ${jobStatusBadge(h.status)}`}>{h.status}</span>
              </button>
              {expandedJob === h.id && historyResults[h.id] && (
                <div className="border-t border-neutral-100 px-4 py-3 dark:border-neutral-800">
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
                        <tr key={i} className="border-t border-neutral-100 dark:border-neutral-800">
                          <td className="py-1.5 pr-3">{r.relative_path}</td>
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

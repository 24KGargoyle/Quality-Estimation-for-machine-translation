"use client";

import { useState } from "react";
import { IntelligencePanel as IntelligencePanelData } from "@/lib/types";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border-t border-neutral-100 py-3 first:border-t-0 first:pt-0 dark:border-neutral-800">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-neutral-400">{title}</h3>
      <div className="mt-2">{children}</div>
    </div>
  );
}

export default function IntelligencePanel({ data }: { data: IntelligencePanelData | null | undefined }) {
  const [collapsed, setCollapsed] = useState(false);

  if (collapsed) {
    return (
      <button
        onClick={() => setCollapsed(false)}
        className="h-fit rounded-lg border border-neutral-200 bg-white px-2 py-3 text-xs text-neutral-500 hover:bg-neutral-50 dark:border-neutral-800 dark:bg-neutral-900 dark:hover:bg-neutral-800"
        title="Show Related Intelligence"
      >
        ◀
      </button>
    );
  }

  const hasContent =
    data &&
    (data.related_topics.length > 0 ||
      data.related_documents.length > 0 ||
      data.related_people.length > 0 ||
      data.ideas.length > 0 ||
      (data.web_research && (data.web_research.results.length > 0 || !data.web_research.configured)));

  return (
    <aside className="w-full max-w-xs shrink-0 rounded-xl border border-neutral-200 bg-white p-4 text-sm dark:border-neutral-800 dark:bg-neutral-900">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">Related Intelligence</h2>
        <button
          onClick={() => setCollapsed(true)}
          className="rounded px-1.5 py-0.5 text-xs text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800"
          title="Collapse"
        >
          ▶
        </button>
      </div>

      {!hasContent && <p className="mt-3 text-xs text-neutral-400">Ask a question to see related context here.</p>}

      {data && data.related_topics.length > 0 && (
        <Section title="Related Topics">
          <ul className="space-y-1">
            {data.related_topics.map((t) => (
              <li key={t} className="text-neutral-700 dark:text-neutral-300">
                • {t}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {data && data.related_documents.length > 0 && (
        <Section title="Related Documents">
          <ul className="space-y-1.5">
            {data.related_documents.map((d) => (
              <li key={d.source_file} className="text-neutral-700 dark:text-neutral-300">
                <div>• {d.source_file}</div>
                <div className="ml-3 text-xs text-neutral-400">
                  {d.document_type}
                  {d.location ? ` · ${d.location}` : ""}
                </div>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {data && data.related_people.length > 0 && (
        <Section title="Related People">
          <div className="flex flex-wrap gap-1.5">
            {data.related_people.map((p) => (
              <span
                key={p}
                className="rounded-full bg-neutral-100 px-2 py-0.5 text-xs text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300"
              >
                {p}
              </span>
            ))}
          </div>
        </Section>
      )}

      {data && data.web_research && (
        <Section title="Web Research">
          {!data.web_research.configured ? (
            <p className="text-xs text-neutral-400">{data.web_research.note}</p>
          ) : data.web_research.results.length === 0 ? (
            <p className="text-xs text-neutral-400">No relevant external results found.</p>
          ) : (
            <ul className="space-y-2">
              {data.web_research.results.map((r) => (
                <li key={r.url}>
                  <a
                    href={r.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs font-medium text-blue-600 hover:underline dark:text-blue-400"
                  >
                    {r.title}
                  </a>
                  <p className="text-xs text-neutral-500">{r.snippet}</p>
                </li>
              ))}
            </ul>
          )}
        </Section>
      )}

      {data && data.ideas.length > 0 && (
        <Section title="Ideas">
          <ul className="space-y-1">
            {data.ideas.map((idea) => (
              <li key={idea} className="text-neutral-700 dark:text-neutral-300">
                • {idea}
              </li>
            ))}
          </ul>
        </Section>
      )}
    </aside>
  );
}

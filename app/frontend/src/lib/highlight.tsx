import React from "react";

const STOPWORDS = new Set([
  "the", "a", "an", "is", "are", "was", "were", "did", "do", "does", "what", "who", "we",
  "when", "where", "why", "how", "to", "of", "in", "on", "for", "and", "or", "about", "that",
  "this", "with", "from", "at", "as", "be", "been", "will", "would", "should", "could", "can",
  "say", "said", "says", "think", "thinks", "mention", "mentioned", "meeting",
]);

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Highlights person names and significant question keywords inside
 * retrieved evidence text — display-only, never alters the underlying
 * source content (§1.3 of the Search Intelligence upgrade). */
export function highlightEvidence(text: string, terms: string[]): React.ReactNode {
  const unique = Array.from(
    new Set(
      terms
        .flatMap((t) => t.split(/\s+/))
        .map((t) => t.trim())
        .filter((t) => t.length > 2 && !STOPWORDS.has(t.toLowerCase()))
    )
  ).sort((a, b) => b.length - a.length);

  if (unique.length === 0) return text;

  const pattern = new RegExp(`(${unique.map(escapeRegExp).join("|")})`, "gi");
  const parts = text.split(pattern);

  return parts.map((part, i) =>
    unique.some((t) => t.toLowerCase() === part.toLowerCase()) ? (
      <mark key={i} className="rounded bg-amber-200/70 px-0.5 dark:bg-amber-500/30">
        {part}
      </mark>
    ) : (
      <React.Fragment key={i}>{part}</React.Fragment>
    )
  );
}

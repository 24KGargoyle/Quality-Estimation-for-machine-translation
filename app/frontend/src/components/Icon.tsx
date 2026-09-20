import type { CSSProperties } from "react";

const paths = {
  overview: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
  meetings: "M4 5h16v16H4z M8 3v4 M16 3v4 M4 10h16 M8 14h3 M8 17h7",
  upload: "M12 16V3 M7 8l5-5 5 5 M4 15v6h16v-6",
  groups: "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2 M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8 M17 4a4 4 0 0 1 0 8 M22 21v-2a4 4 0 0 0-3-4",
  search: "M21 21l-5-5 M10 18a8 8 0 1 0 0-16 8 8 0 0 0 0 16",
  feedback: "M21 15a2 2 0 0 1-2 2H7l-5 4V5a2 2 0 0 1 2-2h15a2 2 0 0 1 2 2z M7 8h10 M7 12h6",
  settings: "M4 7h16 M4 17h16 M8 4v6 M16 14v6",
  arrow: "M5 12h14 M13 6l6 6-6 6",
  spark: "M12 3l2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z",
  file: "M14 2H4v20h16V8z M14 2v6h6 M8 12h8 M8 16h6",
} as const;
export type IconName = keyof typeof paths;
export default function Icon({ name, size = 20, style }: { name: IconName; size?: number; style?: CSSProperties }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={style}><path d={paths[name]} /></svg>;
}

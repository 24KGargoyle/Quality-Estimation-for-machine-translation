"use client";
import { forwardRef, useCallback, useEffect, useImperativeHandle, useLayoutEffect, useRef, useState } from "react";

export interface ConversationHandle { followLatest: () => void }

const Conversation = forwardRef<ConversationHandle, { children: React.ReactNode; label: string }>(function Conversation({ children, label }, ref) {
  const viewport = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const following = useRef(true);
  const [away, setAway] = useState(false);
  const scrollLatest = useCallback((smooth = false) => {
    const node = viewport.current;
    if (!node) return;
    node.scrollTo({ top: node.scrollHeight, behavior: smooth && !window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "smooth" : "instant" });
  }, []);
  useImperativeHandle(ref, () => ({ followLatest() { following.current = true; setAway(false); scrollLatest(); } }), [scrollLatest]);
  useLayoutEffect(() => { if (following.current) scrollLatest(); }, [children, scrollLatest]);
  useEffect(() => {
    const observer = new ResizeObserver(() => { if (following.current) scrollLatest(); });
    if (content.current) observer.observe(content.current);
    if (viewport.current) observer.observe(viewport.current);
    return () => observer.disconnect();
  }, [scrollLatest]);
  return <div className="conversation-frame">
    <div ref={viewport} className="conversation-scroll" role="region" aria-label={label} tabIndex={0} onScroll={() => {
      const node = viewport.current;
      if (!node) return;
      following.current = node.scrollHeight - node.scrollTop - node.clientHeight < 80;
      setAway(!following.current);
    }}>
      <div ref={content} className="conversation-content">{children}</div>
    </div>
    {away && <button className="jump-latest" onClick={() => { following.current = true; setAway(false); scrollLatest(true); }}>↓ Jump to latest</button>}
  </div>;
});
export default Conversation;

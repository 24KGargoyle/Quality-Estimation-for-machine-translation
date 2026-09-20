"use client";
import { useEffect, useRef } from "react";

export default function Dialog({ children, label, onClose }: { children: React.ReactNode; label: string; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    const previous = document.activeElement as HTMLElement | null;
    dialog?.showModal();
    return () => { dialog?.close(); previous?.focus(); };
  }, []);
  return <dialog ref={ref} aria-label={label} className="app-dialog" onCancel={(event) => { event.preventDefault(); onClose(); }} onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    {children}
  </dialog>;
}

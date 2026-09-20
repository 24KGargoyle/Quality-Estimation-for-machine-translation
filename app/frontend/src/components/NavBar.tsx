"use client";
import Image from "next/image";
import Icon, { IconName } from "./Icon";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/auth";

const LINKS = [
  { href: "/dashboard", label: "Overview", icon: "overview" as IconName },
  { href: "/meetings", label: "Meetings", icon: "meetings" as IconName },
  { href: "/meetings/import", label: "Historical Import", icon: "upload" as IconName },
  { href: "/groups", label: "Groups", icon: "groups" as IconName },
  { href: "/search", label: "Search", icon: "search" as IconName },
  { href: "/feedback", label: "Feedback", icon: "feedback" as IconName },
  { href: "/settings", label: "Settings", icon: "settings" as IconName },
];
function Navigation() {
  const pathname = usePathname();
  const { user, logout } = useAuth();
  const [drawer, setDrawer] = useState(false);
  const [profile, setProfile] = useState(false);
  const profileRef = useRef<HTMLDivElement>(null);
  const profileButton = useRef<HTMLButtonElement>(null);
  const navButton = useRef<HTMLButtonElement>(null);
  const active = [...LINKS].reverse().find((link) => pathname.startsWith(link.href));
  useEffect(() => {
    function close(event: PointerEvent) {
      if (!profileRef.current?.contains(event.target as Node)) setProfile(false);
    }
    function escape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        if (profile) { setProfile(false); profileButton.current?.focus(); }
        if (drawer) { setDrawer(false); navButton.current?.focus(); }
      }
    }
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", escape);
    };
  }, [profile, drawer]);
  if (!user) return null;
  const initials = user.displayName.trim().split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase() || "○";
  return <>
    <a className="skip-link" href="#main-content">Skip to content</a>
    <aside className={`app-sidebar ${drawer ? "is-open" : ""}`} id="app-navigation">
      <Link href="/dashboard" className="brand" aria-label="Everforth Quinnox home"><Image src="/brand/everforth-quinnox-logo.png" alt="Everforth Quinnox" width={935} height={267} priority /><small>MEETING ASSISTANT</small></Link>
      <Link href="/meetings" className="sidebar-create"><Icon name="spark" size={17} /> Start a conversation <span>+</span></Link>
      <p className="nav-caption">WORKSPACE</p>
      <nav aria-label="Main navigation">
        {LINKS.map((link) => <Link key={link.href} href={link.href} aria-current={active?.href === link.href ? "page" : undefined} className="nav-link" onClick={() => setDrawer(false)}>
          <span aria-hidden="true" className="nav-icon"><Icon name={link.icon} size={19} /></span>{link.label}
        </Link>)}
      </nav>
    </aside>
    {drawer && <button className="drawer-backdrop" aria-label="Close navigation" onClick={() => setDrawer(false)} />}
    <header className="app-header">
      <div className="flex min-w-0 items-center gap-3">
        <button ref={navButton} className="nav-toggle" aria-label="Toggle navigation" aria-expanded={drawer} aria-controls="app-navigation" onClick={() => setDrawer(!drawer)}>☰</button>
        <span className="header-context">Meeting Assistant <span aria-hidden="true">/</span> <strong>{active?.label ?? "Meeting Assistant"}</strong></span>
      </div>
      <div ref={profileRef} className="profile-container" onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setProfile(false); }}>
        <button ref={profileButton} className="profile-trigger" aria-label={`Account: ${user.displayName}`} aria-expanded={profile} aria-controls="profile-panel" onClick={() => setProfile(!profile)}>
          <span className="profile-name">{user.displayName}</span><span className="avatar">{initials}</span>
        </button>
        {profile && <section id="profile-panel" className="profile-panel" aria-label="Your account">
          <strong>{user.displayName || "Your account"}</strong><p className="profile-role">{user.role}</p>
          <dl><dt>User ID</dt><dd>{user.userId}</dd><dt>Tenant ID</dt><dd>{user.tenantId}</dd></dl>
          <Link href="/settings">Account settings</Link>
          <button onClick={logout}>Sign out <span aria-hidden="true">↗</span></button>
        </section>}
      </div>
    </header>
  </>;
}
export default function NavBar() {
  const pathname = usePathname();
  return <Navigation key={pathname} />;
}

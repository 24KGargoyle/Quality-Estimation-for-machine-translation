"use client";

import { useEffect, useState } from "react";
import Icon from "@/components/Icon";
import Link from "next/link";
import RequireAuth from "@/components/RequireAuth";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";
import { ConversationSummary, GroupSummary, MeetingSummary } from "@/lib/types";

function DashboardContent() {
  const { user } = useAuth();
  const [meetings, setMeetings] = useState<MeetingSummary[]>([]);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [groups, setGroups] = useState<GroupSummary[]>([]);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      api.get<MeetingSummary[]>("/api/meetings").then(setMeetings),
      api.get<ConversationSummary[]>("/api/conversations").then(setConversations),
      api.get<GroupSummary[]>("/api/groups").then(setGroups),
    ]).catch(() => setError("Some workspace data could not be loaded. Refresh to try again."))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="overview-page mx-auto max-w-7xl">
      <div className="page-heading"><div><h1>Welcome back, {user?.displayName}</h1></div><Link className="text-link" href="/meetings/import"><Icon name="upload" size={16} /> Import meetings</Link></div>
      <section className="overview-hero">
        <div className="hero-copy"><h2>Good conversations.<br /><em>Great next steps.</em></h2><Link href="/meetings" className="primary-link">Explore your meetings <Icon name="arrow" size={18} /></Link></div>
        <div className="knowledge-graphic" aria-hidden="true"><div className="orbit orbit-one" /><div className="orbit orbit-two" /><div className="graphic-core"><Icon name="spark" size={34} /></div><span className="orbit-label label-one"><Icon name="meetings" size={18} /> Conversations</span><span className="orbit-label label-two"><Icon name="file" size={18} /> Knowledge</span><span className="orbit-label label-three"><Icon name="groups" size={18} /> Collaboration</span><span className="graphic-caption">A clearer picture. All connected.</span></div>
      </section>
      {error && <p role="alert" className="mt-4 text-sm text-red-600">{error}</p>}
      <div className="metric-strip" aria-busy={loading}>
        {[{href:"/meetings", label:"Meetings in your library", value:meetings.length, icon:"meetings" as const}, {href:"/groups",label:"Groups you collaborate with",value:groups.length,icon:"groups" as const}, {href:"#private-conversations",label:"Private conversations",value:conversations.length,icon:"feedback" as const}].map((metric) => <Link href={metric.href} key={metric.label}><span className="metric-icon"><Icon name={metric.icon} /></span><strong>{loading ? "..." : metric.value}</strong><span>{metric.label}</span><Icon name="arrow" size={16} /></Link>)}
      </div>
      {loading && <div role="status" className="loading-skeleton mt-6">Loading your workspace...</div>}
      <div className="overview-columns">
        <section className="library-section"><div className="section-heading"><h2>Your meeting library</h2><Link href="/meetings">View all <Icon name="arrow" size={15} /></Link></div>
          <div className="library-table">
            {meetings.slice(0,5).map((m,index) => <Link key={m.id} href={`/meetings/${m.id}`} className="library-row"><span className="row-number">{String(index+1).padStart(2,"0")}</span><span className="row-title"><strong>{m.title}</strong><small>{m.participant_count} participants ? {m.duration_seconds ? `${Math.round(m.duration_seconds/60)} min` : "Duration unavailable"}</small></span><span className="status-label">{m.status.replaceAll("_"," ")}</span><Icon name="arrow" size={17} /></Link>)}
            {!loading && meetings.length===0 && <div className="designed-empty"><Icon name="meetings" size={28} /><h3>Your knowledge starts here.</h3><p>Load your first meeting to turn its transcript into answers.</p><Link href="/meetings">Add a meeting</Link></div>}
          </div>
        </section>
        <section id="private-conversations" aria-labelledby="private-conversations-heading" tabIndex={-1} className="recent-panel"><div className="section-heading"><h2 id="private-conversations-heading">Recent meetings</h2><Icon name="feedback" size={18} /></div><p className="section-subtitle">Pick up where you left off</p>
          <div className="conversation-list">{conversations.slice(0, 5).map((c) => <Link className="conversation-row" key={c.id} href={c.meeting_id ? `/meetings/${c.meeting_id}?conversation=${c.id}` : "/meetings"}><span><Icon name="feedback" size={17} /></span><strong>{c.title}</strong><Icon name="arrow" size={15} /></Link>)}
          </div>
          {!loading && conversations.length===0 && <p className="text-sm text-neutral-500 py-6">Ask a question in a meeting. Continue the conversation here.</p>}
        </section>
      </div>
    </div>
  );
}

export default function DashboardPage() {
  return (
    <RequireAuth>
      <DashboardContent />
    </RequireAuth>
  );
}

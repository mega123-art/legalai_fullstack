"use client";

import { useEffect, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import { useClerk } from "@clerk/nextjs";
import { getSessions, createSession, deleteSession } from "@/lib/api";
import type { Session } from "@/lib/types";
import ThemeToggle from "./ThemeToggle";

function groupByDate(sessions: Session[]): Record<string, Session[]> {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today.getTime() - 86_400_000);
  const lastWeek = new Date(today.getTime() - 7 * 86_400_000);

  const groups: Record<string, Session[]> = {
    Today: [],
    Yesterday: [],
    "Last 7 Days": [],
    Older: [],
  };

  for (const s of sessions) {
    const d = new Date(s.updated_at);
    if (d >= today) groups["Today"].push(s);
    else if (d >= yesterday) groups["Yesterday"].push(s);
    else if (d >= lastWeek) groups["Last 7 Days"].push(s);
    else groups["Older"].push(s);
  }
  return groups;
}

interface SidebarProps {
  userId: string;
  userName?: string;
  isOpen: boolean;
  onClose: () => void;
}

export default function Sidebar({ userId, userName = "User", isOpen, onClose }: SidebarProps) {
  const router = useRouter();
  const params = useParams();
  const activeSessionId = params?.sessionId as string | undefined;
  const { signOut } = useClerk();

  const [sessions, setSessions] = useState<Session[]>([]);

  useEffect(() => {
    if (!userId) return;
    getSessions(userId)
      .then((r) => setSessions(r.sessions))
      .catch(console.error);
  }, [userId]);

  async function handleNewSearch() {
    const { session_id } = await createSession(userId);
    onClose();
    router.push(`/chat/${session_id}`);
  }

  function navigate(id: string) {
    onClose();
    router.push(`/chat/${id}`);
  }

  async function handleDelete(e: React.MouseEvent, id: string) {
    e.stopPropagation();
    if (!confirm("Delete this chat? This cannot be undone.")) return;
    try {
      await deleteSession(id, userId);
      setSessions((prev) => prev.filter((s) => s.id !== id));
      if (id === activeSessionId) router.push("/chat");
    } catch (err) {
      console.error(err);
      alert("Failed to delete chat.");
    }
  }

  const groups = groupByDate(sessions);

  return (
    <>
      {/* Mobile backdrop */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-40 md:hidden"
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      {/* Sidebar panel */}
      <aside
        className={`
          fixed md:relative z-50 flex flex-col h-full w-[260px] shrink-0
          bg-surface-sunken border-r border-border-subtle
          transition-transform duration-200 ease-in-out
          ${isOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"}
        `}
        aria-label="Chat history sidebar"
      >
        {/* Logo */}
        <div className="flex items-center gap-2 px-4 py-4 border-b border-border-subtle">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="text-fg-default" aria-hidden="true">
            <path d="M12 3v18"/><path d="M8 21h8"/>
            <path d="M3 9l4-4 4 4"/><path d="M3 9h8"/>
            <path d="M13 15l4-4 4 4"/><path d="M13 15h8"/>
          </svg>
          <span className="font-heading font-semibold text-[15px] text-fg-default tracking-tight">
            LegalAI
          </span>
          {/* Close on mobile */}
          <button
            onClick={onClose}
            className="ml-auto md:hidden w-7 h-7 flex items-center justify-center rounded-lg hover:bg-hover-default text-fg-muted cursor-pointer"
            aria-label="Close sidebar"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>

        {/* New Search */}
        <div className="px-3 py-2">
          <button
            onClick={handleNewSearch}
            className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-fg-default/80 hover:text-fg-default hover:bg-hover-subtle transition-colors duration-150 cursor-pointer"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M12 5v14M5 12h14"/>
            </svg>
            New Search
          </button>
        </div>

        {/* Session list */}
        <nav className="flex-1 overflow-y-auto px-3 py-1" aria-label="Chat sessions">
          {Object.entries(groups).map(([label, items]) =>
            items.length === 0 ? null : (
              <div key={label} className="mb-4">
                <p className="px-2 py-1 text-[11px] font-medium uppercase tracking-wider text-fg-muted">
                  {label}
                </p>
                {items.map((s) => (
                  <div
                    key={s.id}
                    className={`group relative rounded-lg transition-colors duration-150 ${
                      s.id === activeSessionId
                        ? "bg-hover-strong"
                        : "hover:bg-hover-subtle"
                    }`}
                  >
                    <button
                      onClick={() => navigate(s.id)}
                      className={`w-full text-left pl-3 pr-8 py-2 text-sm truncate cursor-pointer ${
                        s.id === activeSessionId
                          ? "text-fg-default"
                          : "text-fg-default/70 group-hover:text-fg-default"
                      }`}
                      title={s.title}
                    >
                      {s.title}
                    </button>
                    <button
                      onClick={(e) => handleDelete(e, s.id)}
                      className="absolute right-1 top-1/2 -translate-y-1/2 w-6 h-6 flex items-center justify-center rounded-md opacity-0 group-hover:opacity-100 hover:bg-hover-strong text-fg-subtle hover:text-red-500 dark:hover:text-red-400 transition-all duration-150 cursor-pointer"
                      aria-label={`Delete ${s.title}`}
                      title="Delete chat"
                    >
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                        <polyline points="3 6 5 6 21 6"/>
                        <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>
                        <path d="M10 11v6M14 11v6"/>
                        <path d="M9 6V4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2"/>
                      </svg>
                    </button>
                  </div>
                ))}
              </div>
            )
          )}
        </nav>

        {/* User info + theme toggle + sign out */}
        <div className="flex items-center gap-2 px-4 py-3 border-t border-border-subtle">
          <div className="w-7 h-7 rounded-full bg-brand-navy flex items-center justify-center text-white text-xs font-semibold shrink-0">
            {userName.charAt(0).toUpperCase()}
          </div>
          <span className="text-sm text-fg-default/80 truncate flex-1">{userName}</span>
          <ThemeToggle />
          <button
            onClick={() => signOut()}
            className="shrink-0 w-7 h-7 flex items-center justify-center rounded-lg hover:bg-hover-default text-fg-subtle hover:text-fg-default transition-colors duration-150 cursor-pointer"
            aria-label="Sign out"
            title="Sign out"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
              <polyline points="16 17 21 12 16 7"/>
              <line x1="21" y1="12" x2="9" y2="12"/>
            </svg>
          </button>
        </div>
      </aside>
    </>
  );
}

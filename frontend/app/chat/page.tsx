"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Sidebar from "@/components/Sidebar";
import ChatInput from "@/components/ChatInput";
import SuggestionCards from "@/components/SuggestionCards";
import { createSession, search } from "@/lib/api";
import { useCurrentUser } from "@/hooks/useCurrentUser";

export default function ChatPage() {
  const router = useRouter();
  const { user, isLoaded } = useCurrentUser();
  const [isLoading, setIsLoading] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  async function handleSubmit(query: string, filters: { yearRange?: { from?: number; to?: number }; outcome?: string; historical?: boolean }) {
    setIsLoading(true);
    try {
      const { session_id } = await createSession(user.id);
      await search({
        query,
        session_id,
        year_from: filters.yearRange?.from,
        year_to: filters.yearRange?.to,
        outcome_filter: filters.outcome,
        historical: filters.historical,
      });
      router.push(`/chat/${session_id}`);
    } catch (e) {
      console.error(e);
      setIsLoading(false);
    }
  }

  useEffect(() => {
    if (isLoaded && !user.id) {
      router.replace("/sign-in");
    }
  }, [isLoaded, user.id, router]);

  if (!isLoaded || !user.id) {
    return (
      <div className="flex items-center justify-center h-screen text-fg-subtle text-sm">
        Loading…
      </div>
    );
  }

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar
        userId={user.id}
        userName={user.name}
        isOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
      />

      <main className="flex flex-col flex-1 overflow-hidden">
        {/* Mobile hamburger */}
        <div className="md:hidden flex items-center px-4 py-3 border-b border-border-subtle">
          <button
            onClick={() => setSidebarOpen(true)}
            className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-hover-default text-fg-default cursor-pointer"
            aria-label="Open sidebar"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <line x1="3" y1="6" x2="21" y2="6"/>
              <line x1="3" y1="12" x2="21" y2="12"/>
              <line x1="3" y1="18" x2="21" y2="18"/>
            </svg>
          </button>
          <span className="ml-3 font-heading font-semibold text-[15px] text-fg-default">Lawsumm</span>
        </div>

        {/* Empty state */}
        <div className="flex-1 flex flex-col items-center justify-center px-4 gap-6">
          <div className="text-center space-y-2">
            <h1 className="font-heading text-2xl sm:text-3xl font-semibold text-fg-default tracking-tight">
              Research Indian Law
            </h1>
            <p className="text-fg-muted text-[14px] sm:text-[15px]">
              Describe your case or ask a legal question
            </p>
          </div>
          <SuggestionCards onSelect={(text) => handleSubmit(text, {})} />
        </div>

        <ChatInput onSubmit={handleSubmit} isLoading={isLoading} showFilters={false} />
      </main>
    </div>
  );
}

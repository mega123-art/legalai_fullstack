"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import Sidebar from "@/components/Sidebar";
import ChatInput from "@/components/ChatInput";
import MessageList from "@/components/MessageList";
import SuggestionCards from "@/components/SuggestionCards";
import CaseDetail from "@/components/CaseDetail";
import { getMessages, search } from "@/lib/api";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import { SavedCasesProvider } from "@/hooks/useSavedCases";
import type { ChatMessage, CaseResult } from "@/lib/types";

export default function SessionPage() {
  const params = useParams();
  const router = useRouter();
  const sessionId = params.sessionId as string;
  const { user, isLoaded } = useCurrentUser();

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [activeCase, setActiveCase] = useState<CaseResult | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => {
    if (!sessionId || !user.id) return;
    getMessages(sessionId, user.id)
      .then((r) => setMessages(r.messages))
      .catch(console.error);
  }, [sessionId, user.id]);

  const handleSubmit = useCallback(
    async (query: string, filters: { year?: number; outcome?: string; historical?: boolean }) => {
      setIsLoading(true);

      const optimisticUserMsg: ChatMessage = {
        id: `opt-${Date.now()}`,
        role: "user",
        content: { text: query },
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, optimisticUserMsg]);

      try {
        const result = await search({
          query,
          session_id: sessionId,
          filter_year: filters.year,
          outcome_filter: filters.outcome,
          historical: filters.historical,
        });

        const assistantMsg: ChatMessage = {
          id: `local-${Date.now()}`,
          role: "assistant",
          content: {
            understood_as: result.understood_as,
            cases: result.cases,
          },
          created_at: new Date().toISOString(),
        };
        setMessages((prev) => [
          ...prev.filter((m) => m.id !== optimisticUserMsg.id),
          optimisticUserMsg,
          assistantMsg,
        ]);
      } catch (e) {
        console.error(e);
        setMessages((prev) => prev.filter((m) => m.id !== optimisticUserMsg.id));
      } finally {
        setIsLoading(false);
      }
    },
    [sessionId]
  );

  // Close detail panel on mobile when sidebar opens
  useEffect(() => {
    if (sidebarOpen) setActiveCase(null);
  }, [sidebarOpen]);

  const panelOpen = activeCase !== null;

  if (!isLoaded) {
    return (
      <div className="flex items-center justify-center h-screen text-fg-subtle text-sm">
        Loading…
      </div>
    );
  }

  if (!user.id) {
    router.replace("/sign-in");
    return null;
  }

  return (
    <SavedCasesProvider userId={user.id}>
    <div className="flex h-screen overflow-hidden">
      <Sidebar
        userId={user.id}
        userName={user.name}
        isOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
      />

      {/* Chat area */}
      <div
        className={`flex flex-col flex-1 overflow-hidden transition-all duration-200 ${
          panelOpen ? "hidden md:flex md:max-w-[55%]" : "w-full"
        }`}
      >
        {/* Mobile header */}
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
          <span className="ml-3 font-heading font-semibold text-[15px] text-fg-default">LegalAI</span>
        </div>

        {messages.length === 0 ? (
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
        ) : (
          <MessageList
            messages={messages}
            onBreakdown={setActiveCase}
            isLoading={isLoading}
          />
        )}
        <ChatInput onSubmit={handleSubmit} isLoading={isLoading} showFilters />
      </div>

      {/* Case detail panel — full screen on mobile, 45% on desktop */}
      {panelOpen && (
        <div className="w-full md:w-[45%] md:shrink-0 overflow-hidden">
          <CaseDetail
            caseResult={activeCase}
            onClose={() => setActiveCase(null)}
            onCitationSearch={(citation) => {
              setActiveCase(null);
              handleSubmit(citation, {});
            }}
          />
        </div>
      )}
    </div>
    </SavedCasesProvider>
  );
}

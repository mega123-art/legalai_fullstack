"use client";

import { useEffect, useRef } from "react";
import CaseCard from "./CaseCard";
import type { ChatMessage, CaseResult, AssistantMessageContent, UserMessageContent } from "@/lib/types";

interface MessageListProps {
  messages: ChatMessage[];
  onBreakdown: (c: CaseResult) => void;
  isLoading?: boolean;
}

export default function MessageList({ messages, onBreakdown, isLoading }: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-3xl mx-auto px-4 py-6 space-y-6">
        {messages.map((msg) => {
          if (msg.role === "user") {
            const c = msg.content as UserMessageContent;
            return (
              <div key={msg.id} className="flex justify-end">
                <div className="max-w-[75%] px-4 py-2.5 rounded-2xl rounded-br-sm bg-surface-input text-fg-default text-sm leading-relaxed">
                  {c.text}
                </div>
              </div>
            );
          }

          const c = msg.content as AssistantMessageContent;
          return (
            <div key={msg.id} className="space-y-3">
              {c.understood_as && (
                <p className="text-[12px] text-fg-subtle italic leading-relaxed">
                  Understood as:{" "}
                  <span className="text-fg-muted">{c.understood_as}</span>
                </p>
              )}
              <div className="space-y-3">
                {(c.cases ?? []).map((cr, i) => (
                  <CaseCard
                    key={cr.case_id + i}
                    caseResult={cr}
                    onBreakdown={onBreakdown}
                    index={i}
                  />
                ))}
              </div>
            </div>
          );
        })}

        {isLoading && (
          <div className="flex items-center gap-2 text-fg-subtle text-sm">
            <span className="flex gap-1">
              {[0, 1, 2].map((i) => (
                <span
                  key={i}
                  className="w-1.5 h-1.5 rounded-full bg-fg-subtle animate-bounce"
                  style={{ animationDelay: `${i * 150}ms` }}
                />
              ))}
            </span>
            Searching judgments…
          </div>
        )}

        <div ref={bottomRef} />
      </div>
    </div>
  );
}

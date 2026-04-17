"use client";

import { useRef, useState, useEffect, KeyboardEvent } from "react";

interface Filters {
  year?: number;
  outcome?: string;
  historical?: boolean;
}

interface ChatInputProps {
  onSubmit: (query: string, filters: Filters) => void;
  isLoading: boolean;
  showFilters?: boolean;
}

const YEAR_OPTIONS = [
  { label: "All Years", value: undefined },
  { label: "2020–2024", value: 2022 },
  { label: "2015–2019", value: 2017 },
  { label: "2010–2014", value: 2012 },
] as const;

const OUTCOME_OPTIONS = [
  { label: "Any Outcome", value: undefined },
  { label: "Allowed", value: "allowed" },
  { label: "Dismissed", value: "dismissed" },
] as const;

export default function ChatInput({ onSubmit, isLoading, showFilters = false }: ChatInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [value, setValue] = useState("");
  const [filters, setFilters] = useState<Filters>({});

  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 200)}px`;
  }, [value]);

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  function submit() {
    const q = value.trim();
    if (!q || isLoading) return;
    setValue("");
    onSubmit(q, filters);
  }

  function setFilter<K extends keyof Filters>(key: K, val: Filters[K]) {
    setFilters((f) => ({ ...f, [key]: val }));
  }

  const pillBase = "px-3 py-1 rounded-full text-xs cursor-pointer transition-colors duration-150";
  const pillActive = "bg-hover-active text-fg-default";
  const pillIdle = "bg-hover-subtle text-fg-muted hover:bg-hover-strong hover:text-fg-default";

  return (
    <div className="sticky bottom-0 bg-gradient-to-t from-surface-base via-surface-base to-transparent pt-4 pb-4 px-4">
      {showFilters && (
        <div className="flex items-center gap-2 mb-2 flex-wrap">
          {YEAR_OPTIONS.map((opt) => (
            <button
              key={opt.label}
              onClick={() => setFilter("year", opt.value)}
              className={`${pillBase} ${filters.year === opt.value ? pillActive : pillIdle}`}
            >
              {opt.label}
            </button>
          ))}
          <span className="text-fg-faint text-xs">|</span>
          {OUTCOME_OPTIONS.map((opt) => (
            <button
              key={opt.label}
              onClick={() => setFilter("outcome", opt.value)}
              className={`${pillBase} ${filters.outcome === opt.value ? pillActive : pillIdle}`}
            >
              {opt.label}
            </button>
          ))}
          <button
            onClick={() => setFilter("historical", !filters.historical)}
            className={`${pillBase} ${filters.historical ? pillActive : pillIdle}`}
          >
            Historical first
          </button>
        </div>
      )}

      {/* Input bar */}
      <div className="relative flex items-end gap-2 bg-surface-input rounded-2xl px-4 py-3 shadow-lg border border-border-subtle">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={1}
          placeholder="Describe your case or ask a legal question…"
          className="flex-1 bg-transparent resize-none text-fg-default placeholder-fg-subtle text-sm leading-relaxed focus:outline-none max-h-[200px] overflow-y-auto"
          style={{ height: "auto" }}
          aria-label="Legal query input"
          disabled={isLoading}
        />
        <button
          onClick={submit}
          disabled={!value.trim() || isLoading}
          className="shrink-0 w-8 h-8 flex items-center justify-center rounded-lg bg-action-primary disabled:bg-action-disabled text-action-primary-fg disabled:text-action-disabled-fg transition-colors duration-150 cursor-pointer disabled:cursor-not-allowed"
          aria-label="Submit query"
        >
          {isLoading ? (
            <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3"/>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
            </svg>
          ) : (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M12 19V5M5 12l7-7 7 7"/>
            </svg>
          )}
        </button>
      </div>

      <p className="text-center text-[11px] text-fg-subtle mt-2">
        LegalAI searches 18,000+ Supreme Court judgments · Not legal advice
      </p>
    </div>
  );
}

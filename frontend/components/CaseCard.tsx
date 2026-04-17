"use client";

import { useState } from "react";
import type { CaseResult } from "@/lib/types";
import { streamSummary, pdfUrl } from "@/lib/api";
import { useSavedCases } from "@/hooks/useSavedCases";

function outcomeMeta(outcome: string) {
  const o = outcome.toLowerCase();
  if (o.includes("allow") || o.includes("grant")) {
    return {
      label: "Allowed",
      color: "text-[#3d5a3a] dark:text-[#8fa98a]",
      border: "border-l-[#6b8a5e]",
      bg: "bg-[#6b8a5e]/12",
    };
  }
  if (o.includes("dismiss") || o.includes("reject")) {
    return {
      label: "Dismissed",
      color: "text-[#6b1d2c] dark:text-[#c07683]",
      border: "border-l-[#6b1d2c]",
      bg: "bg-[#6b1d2c]/12",
    };
  }
  return {
    label: outcome || "Disposed",
    color: "text-fg-muted",
    border: "border-l-border-strong",
    bg: "bg-hover-subtle",
  };
}

interface CaseCardProps {
  caseResult: CaseResult;
  onBreakdown: (c: CaseResult) => void;
  index: number;
}

export default function CaseCard({ caseResult: c, onBreakdown, index }: CaseCardProps) {
  const om = outcomeMeta(c.outcome);
  const [summary, setSummary] = useState<string | null>(null);
  const [loadingSummary, setLoadingSummary] = useState(false);
  const { isSaved, toggle } = useSavedCases();

  const hashId = c.case_id;
  const saved = isSaved(hashId);

  function handleSummary() {
    if (loadingSummary || summary !== null) return;
    setLoadingSummary(true);
    setSummary("");
    streamSummary(
      hashId,
      c.year,
      (token) => setSummary((prev) => (prev ?? "") + token),
      () => setLoadingSummary(false),
      (err) => {
        setSummary("Summary unavailable.");
        setLoadingSummary(false);
        console.error(err);
      }
    );
  }

  return (
    <div
      className={`rounded-xl border border-border-default border-l-4 ${om.border} bg-surface-card transition-shadow duration-150 hover:shadow-md hover:shadow-black/20 dark:hover:shadow-black/40`}
      style={{ animationDelay: `${index * 80}ms` }}
    >
      <div className="p-4">
        <div className="flex items-start justify-between gap-2 mb-2">
          <span className="text-[11px] font-mono text-fg-muted bg-hover-subtle px-2 py-0.5 rounded">
            {c.citation}
          </span>
          <div className="flex items-center gap-1.5 shrink-0">
            <button
              onClick={() => toggle({ case_id: hashId, citation: c.citation, title: c.title })}
              className={`w-6 h-6 flex items-center justify-center rounded-md cursor-pointer transition-colors duration-150 ${
                saved
                  ? "text-amber-500 hover:text-amber-600 dark:text-amber-400 dark:hover:text-amber-300"
                  : "text-fg-subtle hover:text-amber-500 dark:hover:text-amber-400 hover:bg-hover-subtle"
              }`}
              aria-label={saved ? "Remove bookmark" : "Bookmark this case"}
              title={saved ? "Saved — click to remove" : "Save for later"}
            >
              <svg
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill={saved ? "currentColor" : "none"}
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
              </svg>
            </button>
            <span className={`text-[11px] px-2 py-0.5 rounded font-medium ${om.bg} ${om.color}`}>
              {om.label}
            </span>
          </div>
        </div>

        <h3 className="font-heading text-[14px] font-semibold text-fg-default leading-snug mb-1">
          {c.title}
        </h3>

        <p className="text-[12px] text-fg-subtle mb-3">
          {c.court} · {c.year}
          {c.judges ? ` · ${c.judges}` : ""}
        </p>

        {c.preview && (
          <p className="text-[12px] text-fg-muted leading-relaxed line-clamp-2 mb-3">
            {c.preview}
          </p>
        )}

        <div className="flex items-center gap-2">
          <button
            onClick={handleSummary}
            disabled={loadingSummary}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] bg-hover-subtle hover:bg-hover-strong text-fg-default transition-colors duration-150 cursor-pointer disabled:cursor-wait"
          >
            {loadingSummary ? (
              <svg className="animate-spin w-3 h-3" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3"/>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
              </svg>
            ) : (
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                <polyline points="14 2 14 8 20 8"/>
                <line x1="16" y1="13" x2="8" y2="13"/>
                <line x1="16" y1="17" x2="8" y2="17"/>
              </svg>
            )}
            Summary
          </button>
          <button
            onClick={() => onBreakdown(c)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] bg-hover-subtle hover:bg-hover-strong text-fg-default transition-colors duration-150 cursor-pointer"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
            </svg>
            Full Breakdown
          </button>
          <a
            href={pdfUrl(hashId, c.year)}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] bg-hover-subtle hover:bg-hover-strong text-fg-default transition-colors duration-150 cursor-pointer"
            title="Open original judgment PDF in new tab"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
              <polyline points="7 10 12 15 17 10"/>
              <line x1="12" y1="15" x2="12" y2="3"/>
            </svg>
            PDF
          </a>
        </div>
      </div>

      {summary !== null && (
        <div className="border-t border-border-subtle px-4 py-3">
          <p className="text-[11px] font-medium text-fg-muted uppercase tracking-wider mb-1">
            Summary
          </p>
          <p className="text-[13px] text-fg-default/90 leading-relaxed whitespace-pre-wrap">
            {summary}
            {loadingSummary && (
              <span className="inline-block w-1.5 h-3.5 bg-fg-default/60 ml-0.5 animate-pulse rounded-sm" />
            )}
          </p>
        </div>
      )}
    </div>
  );
}

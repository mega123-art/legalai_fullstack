"use client";

import { useEffect, useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { streamBreakdown, pdfUrl, exportBreakdown, downloadBlob } from "@/lib/api";
import { parse as parsePartial, Allow } from "partial-json";
import type { CaseResult, CaseBreakdown } from "@/lib/types";

function outcomeBadge(outcome: string) {
  const o = outcome.toLowerCase();
  if (o.includes("allow") || o.includes("grant")) return "bg-green-500/15 text-green-600 dark:text-green-400";
  if (o.includes("dismiss")) return "bg-red-500/15 text-red-600 dark:text-red-400";
  return "bg-gray-500/15 text-gray-600 dark:text-gray-400";
}

function BulletList({ items }: { items: string[] }) {
  if (!items || items.length === 0) return <p className="text-fg-subtle text-sm italic">None recorded.</p>;
  return (
    <ul className="space-y-2">
      {items.map((item, i) => (
        <li key={i} className="flex gap-2 text-sm text-fg-default/90 leading-relaxed">
          <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-fg-subtle shrink-0" />
          {item}
        </li>
      ))}
    </ul>
  );
}

function Prose({ text }: { text: string }) {
  if (!text) return <p className="text-fg-subtle text-sm italic">Not available.</p>;
  return <p className="text-sm text-fg-default/90 leading-relaxed whitespace-pre-wrap">{text}</p>;
}

interface CaseDetailProps {
  caseResult: CaseResult | null;
  onClose: () => void;
  onCitationSearch?: (citation: string) => void;
}

const EMPTY_BREAKDOWN: Omit<CaseBreakdown, "meta" | "_cached"> = {
  facts: "",
  issues: [],
  arguments_petitioner: [],
  arguments_respondent: [],
  judgment: "",
  ratio_decidendi: "",
  conclusion: "",
  acts_cited: [],
  cases_cited: [],
};

function extractJSONBuffer(raw: string): string {
  // Strip <think>...</think>
  let clean = raw;
  const thinkEnd = clean.lastIndexOf("</think>");
  if (thinkEnd >= 0) clean = clean.slice(thinkEnd + 8);
  // Strip markdown fences
  clean = clean.replace(/```(?:json)?\s*/g, "").replace(/```\s*$/g, "");
  // Find first {
  const i = clean.indexOf("{");
  return i >= 0 ? clean.slice(i) : "";
}

export default function CaseDetail({ caseResult, onClose, onCitationSearch }: CaseDetailProps) {
  const [breakdown, setBreakdown] = useState<CaseBreakdown | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [exporting, setExporting] = useState<null | "md" | "docx">(null);

  useEffect(() => {
    if (!caseResult) return;
    setBreakdown(null);
    setError(null);
    setStreaming(true);

    const cancel = streamBreakdown(caseResult.case_id, caseResult.year, {
      onMeta: (meta, cached) => {
        // Seed breakdown with meta + empty fields so tabs render immediately
        setBreakdown({ ...EMPTY_BREAKDOWN, meta, _cached: cached });
      },
      onToken: (_t, acc) => {
        const buf = extractJSONBuffer(acc);
        if (!buf) return;
        try {
          const partial = parsePartial(buf, Allow.ALL) as Partial<CaseBreakdown>;
          setBreakdown((prev) => {
            if (!prev) return prev;
            return {
              ...prev,
              facts: partial.facts ?? prev.facts,
              issues: partial.issues ?? prev.issues,
              arguments_petitioner: partial.arguments_petitioner ?? prev.arguments_petitioner,
              arguments_respondent: partial.arguments_respondent ?? prev.arguments_respondent,
              judgment: partial.judgment ?? prev.judgment,
              ratio_decidendi: partial.ratio_decidendi ?? prev.ratio_decidendi,
              conclusion: partial.conclusion ?? prev.conclusion,
              acts_cited: partial.acts_cited ?? prev.acts_cited,
              cases_cited: partial.cases_cited ?? prev.cases_cited,
            };
          });
        } catch {
          // Partial parse failure — wait for more tokens
        }
      },
      onFinal: (final) => {
        setBreakdown((prev) => (prev ? { ...prev, ...final } : prev));
      },
      onError: (e) => {
        setError(e.message);
        setStreaming(false);
      },
      onDone: () => setStreaming(false),
    });

    return () => cancel();
  }, [caseResult?.case_id]);

  async function handleExport(format: "md" | "docx") {
    if (!caseResult || exporting) return;
    setExporting(format);
    try {
      const blob = await exportBreakdown(caseResult.case_id, caseResult.year, format);
      const safe = (caseResult.citation || "judgment").replace(/[\s/]/g, "_");
      downloadBlob(blob, `${safe}.${format}`);
    } catch (e) {
      console.error(e);
      alert("Export failed. Try again.");
    } finally {
      setExporting(null);
    }
  }

  function copyCitation() {
    if (!caseResult) return;
    navigator.clipboard.writeText(caseResult.citation).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  if (!caseResult) return null;

  const meta = breakdown?.meta ?? caseResult;

  return (
    <div className="flex flex-col h-full bg-surface-panel border-l border-border-subtle">
      {/* Panel header */}
      <div className="flex items-start gap-3 px-5 py-4 border-b border-border-subtle shrink-0">
        <div className="flex-1 min-w-0">
          <h2 className="font-heading text-[15px] font-semibold text-fg-default leading-snug truncate">
            {meta.title ?? caseResult.title}
          </h2>
          <div className="flex items-center gap-2 mt-1 flex-wrap">
            <span className="text-[11px] font-mono text-fg-muted">{meta.citation ?? caseResult.citation}</span>
            <span className="text-fg-subtle text-[11px]">·</span>
            <span className="text-[11px] text-fg-muted">{meta.year ?? caseResult.year}</span>
            <span className={`text-[11px] px-2 py-0.5 rounded font-medium ${outcomeBadge(meta.outcome ?? caseResult.outcome)}`}>
              {meta.outcome ?? caseResult.outcome}
            </span>
            {breakdown?._cached && (
              <span
                className="text-[10px] px-1.5 py-0.5 rounded font-medium bg-brand-navy/15 text-brand-navy dark:text-blue-300"
                title="Loaded from cache — no LLM call"
              >
                ⚡ cached
              </span>
            )}
          </div>
          {breakdown?.meta.judges && (
            <p className="text-[11px] text-fg-subtle mt-0.5">
              {breakdown.meta.judges}
            </p>
          )}
        </div>
        <button
          onClick={onClose}
          className="shrink-0 w-7 h-7 flex items-center justify-center rounded-lg hover:bg-hover-default text-fg-muted hover:text-fg-default transition-colors duration-150 cursor-pointer"
          aria-label="Close panel"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>
      </div>

      {/* Streaming status strip */}
      {streaming && breakdown && (
        <div className="shrink-0 flex items-center gap-2 px-5 py-1.5 text-[11px] text-fg-muted bg-hover-subtle border-b border-border-subtle">
          <svg className="animate-spin w-3 h-3" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3"/>
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
          </svg>
          Streaming analysis — fields fill as the model writes them.
        </div>
      )}

      {/* Content */}
      <div className="flex-1 overflow-hidden">
        {!breakdown && streaming && (
          <div className="flex items-center justify-center h-40 gap-2 text-fg-muted text-sm">
            <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3"/>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
            </svg>
            Loading…
          </div>
        )}
        {error && (
          <div className="p-5 text-sm text-red-600 dark:text-red-400">{error}</div>
        )}
        {breakdown && (
          <Tabs defaultValue="facts" className="flex flex-col h-full">
            <TabsList className="shrink-0 mx-5 mt-3 mb-0 bg-hover-subtle rounded-lg h-9 gap-0.5 justify-start overflow-x-auto">
              {["facts", "issues", "arguments", "judgment", "ratio", "conclusion"].map((tab) => (
                <TabsTrigger
                  key={tab}
                  value={tab}
                  className="text-[12px] capitalize px-3 h-7 rounded data-[state=active]:bg-hover-strong data-[state=active]:text-fg-default text-fg-muted cursor-pointer"
                >
                  {tab === "ratio" ? "Ratio" : tab.charAt(0).toUpperCase() + tab.slice(1)}
                </TabsTrigger>
              ))}
            </TabsList>

            <div className="flex-1 overflow-y-auto">
              <TabsContent value="facts" className="px-5 py-4 mt-0">
                <Prose text={breakdown.facts} />
              </TabsContent>
              <TabsContent value="issues" className="px-5 py-4 mt-0">
                <BulletList items={breakdown.issues} />
              </TabsContent>
              <TabsContent value="arguments" className="px-5 py-4 mt-0 space-y-5">
                <div>
                  <h4 className="text-[11px] uppercase tracking-wider text-fg-subtle font-medium mb-2">Petitioner</h4>
                  <BulletList items={breakdown.arguments_petitioner} />
                </div>
                <div>
                  <h4 className="text-[11px] uppercase tracking-wider text-fg-subtle font-medium mb-2">Respondent</h4>
                  <BulletList items={breakdown.arguments_respondent} />
                </div>
              </TabsContent>
              <TabsContent value="judgment" className="px-5 py-4 mt-0">
                <Prose text={breakdown.judgment} />
                {breakdown.acts_cited.length > 0 && (
                  <div className="mt-4">
                    <h4 className="text-[11px] uppercase tracking-wider text-fg-subtle font-medium mb-2">Acts Cited</h4>
                    <BulletList items={breakdown.acts_cited} />
                  </div>
                )}
              </TabsContent>
              <TabsContent value="ratio" className="px-5 py-4 mt-0">
                <Prose text={breakdown.ratio_decidendi} />
                {breakdown.cases_cited.length > 0 && (
                  <div className="mt-4">
                    <h4 className="text-[11px] uppercase tracking-wider text-fg-subtle font-medium mb-2">
                      Cases Cited · Citation Network
                    </h4>
                    <p className="text-[11px] text-fg-subtle mb-2">
                      Click any citation to search its chain of law.
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {breakdown.cases_cited.map((c, i) => (
                        <button
                          key={i}
                          onClick={() => onCitationSearch?.(c)}
                          disabled={!onCitationSearch}
                          className="text-left text-[12px] px-2.5 py-1 rounded-md bg-hover-subtle hover:bg-hover-strong text-fg-default/90 hover:text-brand-navy dark:hover:text-blue-300 border border-border-subtle hover:border-border-strong transition-colors duration-150 cursor-pointer disabled:cursor-default disabled:hover:text-fg-default/90"
                          title={onCitationSearch ? `Search: ${c}` : c}
                        >
                          {c}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </TabsContent>
              <TabsContent value="conclusion" className="px-5 py-4 mt-0">
                <Prose text={breakdown.conclusion} />
                {breakdown._fallback && (
                  <p className="mt-3 text-[11px] text-fg-subtle italic">
                    Full AI breakdown unavailable — Gemini fallback used.
                  </p>
                )}
              </TabsContent>
            </div>
          </Tabs>
        )}
      </div>

      {/* Footer */}
      <div className="shrink-0 px-5 py-3 border-t border-border-subtle flex items-center gap-4 flex-wrap">
        <a
          href={pdfUrl(caseResult.case_id, caseResult.year)}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1.5 text-[12px] text-fg-muted hover:text-fg-default cursor-pointer transition-colors duration-150"
          title="Open judgment PDF in new tab"
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M15 3h6v6M10 14 21 3M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>
          </svg>
          Open PDF
        </a>
        <a
          href={pdfUrl(caseResult.case_id, caseResult.year, true)}
          className="flex items-center gap-1.5 text-[12px] text-fg-muted hover:text-fg-default cursor-pointer transition-colors duration-150"
          title="Download PDF to disk"
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
            <polyline points="7 10 12 15 17 10"/>
            <line x1="12" y1="15" x2="12" y2="3"/>
          </svg>
          Save
        </a>
        <button
          onClick={() => handleExport("md")}
          disabled={!breakdown || streaming || !!exporting}
          className="flex items-center gap-1.5 text-[12px] text-fg-muted hover:text-fg-default cursor-pointer transition-colors duration-150 disabled:opacity-50 disabled:cursor-wait"
          title="Export breakdown as Markdown"
        >
          {exporting === "md" ? (
            <svg className="animate-spin w-3 h-3" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3"/>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
            </svg>
          ) : (
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
              <polyline points="14 2 14 8 20 8"/>
              <line x1="9" y1="13" x2="15" y2="13"/>
              <line x1="9" y1="17" x2="15" y2="17"/>
            </svg>
          )}
          Markdown
        </button>
        <button
          onClick={() => handleExport("docx")}
          disabled={!breakdown || streaming || !!exporting}
          className="flex items-center gap-1.5 text-[12px] text-fg-muted hover:text-fg-default cursor-pointer transition-colors duration-150 disabled:opacity-50 disabled:cursor-wait"
          title="Export breakdown as Word .docx"
        >
          {exporting === "docx" ? (
            <svg className="animate-spin w-3 h-3" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3"/>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
            </svg>
          ) : (
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
              <polyline points="14 2 14 8 20 8"/>
              <path d="M10 13l-1 4 2-1 2 1-1-4"/>
            </svg>
          )}
          DOCX
        </button>
        <button
          onClick={copyCitation}
          className="flex items-center gap-2 text-[12px] text-fg-muted hover:text-fg-default cursor-pointer transition-colors duration-150"
        >
          {copied ? (
            <>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="text-green-600 dark:text-green-400" aria-hidden="true"><polyline points="20 6 9 17 4 12"/></svg>
              <span className="text-green-600 dark:text-green-400">Copied!</span>
            </>
          ) : (
            <>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
              Copy Citation
            </>
          )}
        </button>
      </div>
    </div>
  );
}

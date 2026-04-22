import type { SearchResponse, CaseBreakdown, Session, ChatMessage } from "./types";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "API error");
  }
  return res.json() as Promise<T>;
}

// ── Search ────────────────────────────────────────────────────

export async function search(params: {
  query: string;
  session_id?: string;
  filter_year?: number;
  outcome_filter?: string;
  historical?: boolean;
}): Promise<SearchResponse> {
  return apiFetch("/api/search", {
    method: "POST",
    body: JSON.stringify(params),
  });
}

// ── Breakdown ─────────────────────────────────────────────────

export async function getBreakdown(case_id: string, year: number): Promise<CaseBreakdown> {
  return apiFetch("/api/breakdown", {
    method: "POST",
    body: JSON.stringify({ case_id, year }),
  });
}

// SSE streaming breakdown. Emits meta → tokens → final → DONE.
export interface BreakdownStreamHandlers {
  onMeta: (meta: CaseBreakdown["meta"], cached: boolean) => void;
  onToken: (token: string, accumulated: string) => void;
  onFinal: (breakdown: Omit<CaseBreakdown, "meta" | "_cached">) => void;
  onError: (err: Error) => void;
  onDone: () => void;
}

export function streamBreakdown(
  case_id: string,
  year: number,
  handlers: BreakdownStreamHandlers
): () => void {
  const controller = new AbortController();

  (async () => {
    try {
      const res = await fetch(`${BASE}/api/breakdown/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ case_id, year }),
        signal: controller.signal,
      });
      if (!res.ok) throw new Error(`Breakdown stream failed: ${res.statusText}`);
      if (!res.body) throw new Error("No response body");

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let acc = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // SSE events separated by blank line
        const parts = buffer.split("\n\n");
        buffer = parts.pop() ?? "";

        for (const raw of parts) {
          if (!raw.trim()) continue;
          let event: string | null = null;
          let data = "";
          for (const line of raw.split("\n")) {
            if (line.startsWith("event: ")) event = line.slice(7);
            else if (line.startsWith("data: ")) data += line.slice(6);
          }
          const payload = data.replace(/\\n/g, "\n");

          if (payload === "[DONE]") {
            handlers.onDone();
            return;
          }
          if (event === "meta") {
            try {
              const p = JSON.parse(payload);
              handlers.onMeta(p.meta, !!p.cached);
            } catch {}
          } else if (event === "token") {
            acc += payload;
            handlers.onToken(payload, acc);
          } else if (event === "final") {
            try {
              handlers.onFinal(JSON.parse(payload));
            } catch (e) {
              handlers.onError(e as Error);
            }
          } else if (event === "error") {
            try {
              const p = JSON.parse(payload);
              handlers.onError(new Error(p.message || "Stream error"));
            } catch {
              handlers.onError(new Error("Stream error"));
            }
          }
        }
      }
      handlers.onDone();
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        handlers.onError(err as Error);
      }
    }
  })();

  return () => controller.abort();
}

// ── Summary (SSE streaming) ───────────────────────────────────

export function streamSummary(
  case_id: string,
  year: number,
  onToken: (token: string) => void,
  onDone: () => void,
  onError: (err: Error) => void
): () => void {
  const controller = new AbortController();

  fetch(`${BASE}/api/summary`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ case_id, year }),
    signal: controller.signal,
  })
    .then(async (res) => {
      if (!res.ok) throw new Error(`Summary failed: ${res.statusText}`);
      if (!res.body) throw new Error("No response body");

      const reader = res.body.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        for (const line of chunk.split("\n")) {
          if (line.startsWith("data: ")) {
            const data = line.slice(6);
            if (data === "[DONE]") {
              onDone();
              return;
            }
            // Unescape newlines encoded by the server
            onToken(data.replace(/\\n/g, "\n"));
          }
        }
      }
      onDone();
    })
    .catch((err) => {
      if (err.name !== "AbortError") onError(err);
    });

  // Return cancel function
  return () => controller.abort();
}

// ── PDF ──────────────────────────────────────────────────────

export function pdfUrl(case_id: string, year: number, download = false): string {
  const q = download ? "?download=1" : "";
  return `${BASE}/api/pdf/${year}/${encodeURIComponent(case_id)}${q}`;
}

// ── Saved cases / bookmarks ──────────────────────────────────

export interface SavedCase {
  id: string;
  citation: string;
  case_id: string;
  title: string;
  saved_at: string;
}

export async function getSavedCases(user_id: string): Promise<{ cases: SavedCase[] }> {
  return apiFetch(`/api/saved-cases/${user_id}`);
}

export async function saveCase(params: {
  user_id: string;
  citation: string;
  case_id: string;
  title: string;
}): Promise<{ id: string }> {
  return apiFetch("/api/saved-cases", {
    method: "POST",
    body: JSON.stringify(params),
  });
}

export async function unsaveCase(user_id: string, case_id: string): Promise<{ deleted: boolean }> {
  return apiFetch("/api/saved-cases", {
    method: "DELETE",
    body: JSON.stringify({ user_id, case_id }),
  });
}

// ── Export breakdown ─────────────────────────────────────────

export async function exportBreakdown(
  case_id: string,
  year: number,
  format: "md" | "docx"
): Promise<Blob> {
  const res = await fetch(`${BASE}/api/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ case_id, year, format }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Export failed");
  }
  return res.blob();
}

export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// ── Sessions ──────────────────────────────────────────────────

export async function createSession(user_id: string): Promise<{ session_id: string }> {
  return apiFetch("/api/sessions", {
    method: "POST",
    body: JSON.stringify({ user_id }),
  });
}

export async function getSessions(user_id: string): Promise<{ sessions: Session[] }> {
  return apiFetch(`/api/sessions/${user_id}`);
}

export async function getMessages(session_id: string, user_id: string): Promise<{ messages: ChatMessage[] }> {
  return apiFetch(`/api/sessions/${session_id}/messages?user_id=${encodeURIComponent(user_id)}`);
}

export async function deleteSession(session_id: string, user_id: string): Promise<{ deleted: boolean }> {
  return apiFetch(`/api/sessions/${session_id}`, {
    method: "DELETE",
    body: JSON.stringify({ user_id }),
  });
}

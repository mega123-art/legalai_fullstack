// Matches the case dict returned by /api/search
export interface CaseResult {
  case_id: string;          // INSC citation e.g. "2022 INSC 1212"
  id?: string;              // hash id e.g. "4f98f1ef122b" — used for breakdown/summary
  citation: string;         // "[2022] 10 S.C.R. 102"
  title: string;
  petitioner: string;
  respondent: string;
  court: string;
  year: number;
  date: string;
  outcome: string;          // "Dismissed" | "Allowed" | "Disposed Of" etc.
  judges?: string;
  relevance_score: number;
  preview: string;
  chunk_type: string;       // "headnote" | "judgment"
}

export interface SearchResponse {
  understood_as: string;
  cases: CaseResult[];
}

// Matches /api/breakdown response
export interface CaseBreakdown {
  facts: string;
  issues: string[];
  arguments_petitioner: string[];
  arguments_respondent: string[];
  judgment: string;
  ratio_decidendi: string;
  conclusion: string;
  acts_cited: string[];
  cases_cited: string[];
  meta: {
    case_id: string;
    id: string;
    citation: string;
    title: string;
    petitioner: string;
    respondent: string;
    judges: string;
    date: string;
    year: number;
    outcome: string;
    court: string;
  };
  _fallback?: boolean;
  _cached?: boolean;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: UserMessageContent | AssistantMessageContent;
  created_at: string;
}

export interface UserMessageContent {
  text: string;
}

export interface AssistantMessageContent {
  understood_as: string;
  cases: CaseResult[];
}

export interface Session {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  last_message: string;
}

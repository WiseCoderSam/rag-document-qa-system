import type { Session } from "@supabase/supabase-js"

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000"

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = "ApiError"
    this.status = status
  }
}

/**
 * Wraps the authenticated-fetch pattern used across the app (see the
 * original inline version in Home.tsx): builds the request against
 * VITE_API_URL, attaches the Supabase session's bearer token, throws on a
 * non-2xx response, and JSON-decodes the body otherwise.
 */
export async function apiFetch<T>(path: string, session: Session, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${session.access_token}`,
      ...init?.headers,
    },
  })

  if (!res.ok) {
    throw new ApiError(res.status, `Request to ${path} failed with status ${res.status}`)
  }

  return res.json() as Promise<T>
}

// ---------------------------------------------------------------------------
// Response models — mirror backend/app/main.py's Pydantic response_models.
// ---------------------------------------------------------------------------

/**
 * Matches IncidentOut in backend/app/main.py (lines 181-196).
 * Note: there is no hostname field on incidents.
 */
export interface IncidentOut {
  id: number
  title: string
  rule_name: string
  severity: string
  description: string
  mitre_technique: string | null
  mitre_tactic: string | null
  status: string
  summary: string | null
  affected_user: string | null
  affected_ip: string | null
  log_file_id: number | null
  created_at: string
}

/**
 * Matches LogEntryOut in backend/app/main.py (lines 323-334).
 * Note: there is no parsed_json field on this response model.
 */
export interface LogEntryOut {
  id: number
  file_id: number
  timestamp: string | null
  severity: string
  ip_address: string | null
  user_name: string | null
  hostname: string | null
  event_id: string | null
  message: string
}

/** Matches ChatRequest in backend/app/main.py (lines 266-269). */
export interface ChatRequest {
  question: string
  file_id?: number
  incident_id?: number
}

/** Matches ChatResponse in backend/app/main.py (lines 272-274). */
export interface ChatResponse {
  answer: string
  sources: number[]
}

/**
 * The literal string POST /api/v1/chat returns instead of calling the LLM
 * when nothing matches (backend/app/main.py, NO_MATCH_ANSWER at lines
 * 277-280). The backend has no separate flag for this — callers detect it
 * by exact string match, so this constant must stay in sync with the
 * backend copy if that message is ever changed.
 */
export const NO_MATCH_ANSWER =
  "No matching log data found for this question. Try rephrasing, or upload a log file first if you haven't yet."

/** Matches IncidentSummaryResponse in backend/app/main.py (lines 199-201). */
export interface IncidentSummaryResponse {
  incident_id: number
  summary: string
}

/**
 * Resolves chat/query citation ids back into full log content via GET
 * /api/v1/logs/entries?ids=... (backend/app/main.py). Returns [] without a
 * network call when *ids* is empty.
 */
export async function getLogEntries(ids: number[], session: Session): Promise<LogEntryOut[]> {
  if (ids.length === 0) return []
  return apiFetch<LogEntryOut[]>(`/api/v1/logs/entries?ids=${ids.join(",")}`, session)
}

/** Matches LogFileOut in backend/app/main.py. */
export interface LogFileOut {
  id: number
  filename: string
  file_url: string
  status: string
  uploaded_by: string
  uploaded_at: string
}

/** Matches DocumentOut in backend/app/main.py. */
export interface DocumentOut {
  id: number
  filename: string
  file_url: string
  page_count: number | null
  status: string
  uploaded_by: string
  uploaded_at: string
}

/** Matches DocumentChunkOut in backend/app/main.py. */
export interface DocumentChunkOut {
  id: number
  document_id: number
  chunk_index: number
  text: string
}

/**
 * Resolves document-mode chat citation ids back into full chunk text via
 * GET /api/v1/documents/chunks?ids=... (backend/app/main.py). Returns []
 * without a network call when *ids* is empty.
 */
export async function getDocumentChunks(ids: number[], session: Session): Promise<DocumentChunkOut[]> {
  if (ids.length === 0) return []
  return apiFetch<DocumentChunkOut[]>(`/api/v1/documents/chunks?ids=${ids.join(",")}`, session)
}

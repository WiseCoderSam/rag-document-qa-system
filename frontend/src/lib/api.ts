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
 * Wraps the authenticated-fetch pattern used across the app: builds the
 * request against VITE_API_URL, attaches the Supabase session's bearer
 * token, throws on a non-2xx response, and JSON-decodes the body otherwise.
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
    let message = `Request to ${path} failed with status ${res.status}`
    try {
      const error = (await res.json()) as { detail?: string }
      if (error.detail) {
        message = error.detail
      }
    } catch {
      // Response is not JSON, use the default message
    }
    throw new ApiError(res.status, message)
  }

  // 204 No Content (e.g. DELETE endpoints) has no body to parse.
  if (res.status === 204) {
    return undefined as T
  }

  return res.json() as Promise<T>
}

// ---------------------------------------------------------------------------
// Response models — mirror backend/app/main.py's Pydantic response_models.
// ---------------------------------------------------------------------------

/** Matches ChatRequest in backend/app/main.py. */
export interface ChatRequest {
  question: string
  document_id?: number
}

/** Matches ChatResponse in backend/app/main.py. */
export interface ChatResponse {
  answer: string
  sources: number[]
}

/**
 * The literal string POST /api/v1/chat returns instead of calling the LLM
 * when nothing matches (backend/app/main.py, NO_MATCH_ANSWER). The backend
 * has no separate flag for this — callers detect it by exact string match,
 * so this constant must stay in sync with the backend copy if that message
 * is ever changed.
 */
export const NO_MATCH_ANSWER =
  "No matching document content found for this question. Try rephrasing, or upload a document first if you haven't yet."

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

/** DELETE /api/v1/documents/{id} — restricted to documents owned by the caller. */
export function deleteDocument(id: number, session: Session): Promise<void> {
  return apiFetch<void>(`/api/v1/documents/${id}`, session, { method: "DELETE" })
}

/** POST /api/v1/documents/{id}/retry — only valid while status === "failed". */
export function retryDocument(id: number, session: Session): Promise<DocumentOut> {
  return apiFetch<DocumentOut>(`/api/v1/documents/${id}/retry`, session, { method: "POST" })
}

/** Matches DocumentChunkOut in backend/app/main.py. */
export interface DocumentChunkOut {
  id: number
  document_id: number
  chunk_index: number
  text: string
}

/**
 * Resolves chat citation ids back into full chunk text via
 * GET /api/v1/documents/chunks?ids=... (backend/app/main.py). Returns []
 * without a network call when *ids* is empty.
 */
export async function getDocumentChunks(ids: number[], session: Session): Promise<DocumentChunkOut[]> {
  if (ids.length === 0) return []
  return apiFetch<DocumentChunkOut[]>(`/api/v1/documents/chunks?ids=${ids.join(",")}`, session)
}

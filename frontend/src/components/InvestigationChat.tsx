import { useState, type FormEvent } from "react"
import type { Session } from "@supabase/supabase-js"
import Markdown from "react-markdown"
import { Loader2, SendIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import {
  apiFetch,
  getDocumentChunks,
  getLogEntries,
  NO_MATCH_ANSWER,
  type ChatRequest,
  type ChatResponse,
  type DocumentChunkOut,
  type LogEntryOut,
} from "@/lib/api"

// DocumentChunkOut has no log-specific fields (timestamp, severity, etc.) —
// this adapts one into the LogEntryOut shape CitationBadge already renders,
// so document-mode citations don't need a second badge/popover component.
function chunkToLogEntry(chunk: DocumentChunkOut): LogEntryOut {
  return {
    id: chunk.id,
    message: chunk.text,
    timestamp: null,
    severity: "INFO",
    ip_address: null,
    user_name: null,
    hostname: null,
    event_id: null,
    file_id: chunk.document_id,
  }
}

interface ChatTurn {
  id: number
  role: "user" | "assistant" | "notice"
  content: string
  sources?: number[]
}

interface InvestigationChatProps {
  session: Session
  /** Scope the chat to one incident's log file. Both props are optional; pass at most one. */
  incidentId?: number
  /** Scope the chat to one uploaded file. Ignored if incidentId is also set. */
  fileId?: number
  onClearScope?: () => void
}

let turnCounter = 0

export function InvestigationChat({ session, incidentId, fileId, onClearScope }: InvestigationChatProps) {
  const [turns, setTurns] = useState<ChatTurn[]>([])
  const [question, setQuestion] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [entries, setEntries] = useState<Map<number, LogEntryOut>>(new Map())

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    const trimmed = question.trim()
    if (!trimmed || loading) return

    setTurns((prev) => [...prev, { id: turnCounter++, role: "user", content: trimmed }])
    setQuestion("")
    setLoading(true)
    setError(null)

    try {
      const body: ChatRequest = { question: trimmed }
      // Only send whichever scope this component actually has — both are optional
      // on ChatRequest (backend/app/main.py:266-269).
      if (incidentId !== undefined) {
        body.incident_id = incidentId
      } else if (fileId !== undefined) {
        body.file_id = fileId
      }

      const response = await apiFetch<ChatResponse>("/api/v1/chat", session, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })

      const isNoMatch = response.answer === NO_MATCH_ANSWER
      setTurns((prev) => [
        ...prev,
        {
          id: turnCounter++,
          role: isNoMatch ? "notice" : "assistant",
          content: response.answer,
          sources: response.sources,
        },
      ])

      if (response.sources.length > 0) {
        let resolved: LogEntryOut[]
        if (fileId !== undefined) {
          // Document mode: sources are DocumentChunk ids, not LogEntry ids.
          resolved = (await getDocumentChunks(response.sources, session)).map(chunkToLogEntry)
        } else if (incidentId !== undefined) {
          resolved = await getLogEntries(response.sources, session)
        } else {
          // General mode: the backend can now legitimately return a mix of
          // log entry ids and document chunk ids in one response (see
          // rag.py's kind-aware retrieve_context), so both must be
          // resolved rather than trying one and falling back to the other.
          const [logEntries, docChunks] = await Promise.all([
            getLogEntries(response.sources, session),
            getDocumentChunks(response.sources, session),
          ])
          resolved = [...logEntries, ...docChunks.map(chunkToLogEntry)]
        }
        setEntries((prev) => {
          const next = new Map(prev)
          for (const entry of resolved) next.set(entry.id, entry)
          return next
        })
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Chat request failed.")
    } finally {
      setLoading(false)
    }
  }

  return (
    <Card className="flex h-[32rem] flex-col">
      <CardHeader>
        <div className="flex items-center justify-between gap-4">
          <div>
            <CardTitle>Investigation Chat</CardTitle>
            <CardDescription>
              Ask questions about your ingested logs
              {incidentId !== undefined ? ` for Incident #${incidentId}` : fileId !== undefined ? ` for File #${fileId}` : ""}.
            </CardDescription>
          </div>
          {(incidentId !== undefined || fileId !== undefined) && onClearScope && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={onClearScope}
              className="text-xs"
            >
              Clear Scope
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-3 overflow-hidden">
        <div className="flex flex-1 flex-col gap-3 overflow-y-auto pr-1">
          {turns.length === 0 && !loading && (
            <p className="text-sm text-muted-foreground">Ask a question to get started.</p>
          )}
          {turns.map((turn) => (
            <ChatBubble key={turn.id} turn={turn} entries={entries} />
          ))}
          {loading && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
              <Loader2 className="size-4 animate-spin" />
              Thinking…
            </div>
          )}
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}

        <form onSubmit={handleSubmit} className="flex gap-2">
          <Input
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="Ask about your logs…"
            disabled={loading}
          />
          <Button type="submit" disabled={loading || !question.trim()} size="icon" aria-label="Send">
            <SendIcon />
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}

function ChatBubble({ turn, entries }: { turn: ChatTurn; entries: Map<number, LogEntryOut> }) {
  if (turn.role === "notice") {
    return (
      <p className="rounded-md border border-border bg-muted/30 px-3 py-2 text-sm text-muted-foreground">
        {turn.content}
      </p>
    )
  }

  const isUser = turn.role === "user"

  return (
    <div className={"flex flex-col gap-1.5 " + (isUser ? "items-end" : "items-start")}>
      <div
        className={
          "max-w-[85%] rounded-lg px-3 py-2 text-sm " +
          (isUser ? "bg-primary text-primary-foreground" : "bg-muted text-foreground")
        }
      >
        {isUser ? (
          turn.content
        ) : (
          // react-markdown does not render raw HTML by default (no rehype-raw
          // plugin here), so a literal <script> tag quoted from an attacker's
          // log payload (see rules.py's XSS signature detection) renders as
          // inert text instead of executing — unlike dangerouslySetInnerHTML.
          <div className="prose-sm max-w-none [&_ol]:my-1 [&_p]:my-1 [&_ul]:my-1">
            <Markdown>{turn.content}</Markdown>
          </div>
        )}
      </div>
      {turn.sources && turn.sources.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {turn.sources.map((sourceId, index) => (
            <CitationBadge key={sourceId} index={index + 1} entryId={sourceId} entry={entries.get(sourceId)} />
          ))}
        </div>
      )}
    </div>
  )
}

function CitationBadge({
  index,
  entryId,
  entry,
}: {
  index: number
  entryId: number
  entry: LogEntryOut | undefined
}) {
  return (
    <Popover>
      <PopoverTrigger className="cursor-pointer rounded-full">
        <Badge className="bg-secondary font-mono text-secondary-foreground hover:bg-secondary/80">
          [{index}] Log Entry #{entryId}
        </Badge>
      </PopoverTrigger>
      <PopoverContent>
        {!entry ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : (
          <div className="flex flex-col gap-1.5">
            <p className="font-mono text-xs font-medium text-muted-foreground">
              {entry.timestamp ? new Date(entry.timestamp).toLocaleString() : "N/A"}
            </p>
            <p className="font-mono text-xs whitespace-pre-wrap">{entry.message}</p>
          </div>
        )}
      </PopoverContent>
    </Popover>
  )
}

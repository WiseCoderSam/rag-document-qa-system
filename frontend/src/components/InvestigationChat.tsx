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
  NO_MATCH_ANSWER,
  type ChatRequest,
  type ChatResponse,
  type DocumentChunkOut,
} from "@/lib/api"

interface ChatTurn {
  id: number
  role: "user" | "assistant" | "notice"
  content: string
  sources?: number[]
}

interface InvestigationChatProps {
  session: Session
  /** Scope the chat to one uploaded document. */
  documentId?: number
  /** Human-readable name for the scoped document, shown in the header. */
  documentName?: string
  onClearScope?: () => void
}

let turnCounter = 0

export function InvestigationChat({ session, documentId, documentName, onClearScope }: InvestigationChatProps) {
  const [turns, setTurns] = useState<ChatTurn[]>([])
  const [question, setQuestion] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [chunks, setChunks] = useState<Map<number, DocumentChunkOut>>(new Map())

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
      if (documentId !== undefined) {
        body.document_id = documentId
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
        const resolved = await getDocumentChunks(response.sources, session)
        setChunks((prev) => {
          const next = new Map(prev)
          for (const chunk of resolved) next.set(chunk.id, chunk)
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
            <CardTitle>Ask Your Documents</CardTitle>
            <CardDescription>
              {documentId !== undefined
                ? `Answers come only from ${documentName ?? "the selected document"}.`
                : "Answers come from all documents you've uploaded."}
            </CardDescription>
          </div>
          {documentId !== undefined && onClearScope && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={onClearScope}
              className="text-xs"
            >
              Ask all documents
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-3 overflow-hidden">
        <div className="flex flex-1 flex-col gap-3 overflow-y-auto pr-1">
          {turns.length === 0 && !loading && (
            <p className="text-sm text-muted-foreground">
              Ask a question about your uploaded documents — e.g. &ldquo;What is this document
              about?&rdquo; If you haven&apos;t uploaded anything yet, add a document in the
              Documents tab first.
            </p>
          )}
          {turns.map((turn) => (
            <ChatBubble key={turn.id} turn={turn} chunks={chunks} />
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
            placeholder="Ask about your documents…"
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

function ChatBubble({ turn, chunks }: { turn: ChatTurn; chunks: Map<number, DocumentChunkOut> }) {
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
          // plugin here), so a literal <script> tag quoted from an uploaded
          // document renders as inert text instead of executing — unlike
          // dangerouslySetInnerHTML.
          <div className="prose-sm max-w-none [&_ol]:my-1 [&_p]:my-1 [&_ul]:my-1">
            <Markdown>{turn.content}</Markdown>
          </div>
        )}
      </div>
      {turn.sources && turn.sources.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {turn.sources.map((sourceId, index) => (
            <CitationBadge key={sourceId} index={index + 1} chunk={chunks.get(sourceId)} />
          ))}
        </div>
      )}
    </div>
  )
}

function CitationBadge({ index, chunk }: { index: number; chunk: DocumentChunkOut | undefined }) {
  return (
    <Popover>
      <PopoverTrigger className="cursor-pointer rounded-full">
        <Badge className="bg-secondary font-mono text-secondary-foreground hover:bg-secondary/80">
          Source [{index}]
        </Badge>
      </PopoverTrigger>
      <PopoverContent>
        {!chunk ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : (
          <div className="flex flex-col gap-1.5">
            <p className="font-mono text-xs font-medium text-muted-foreground">
              Excerpt #{chunk.chunk_index + 1} from document #{chunk.document_id}
            </p>
            <p className="max-h-48 overflow-y-auto font-mono text-xs whitespace-pre-wrap">{chunk.text}</p>
          </div>
        )}
      </PopoverContent>
    </Popover>
  )
}

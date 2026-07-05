import { useState } from "react"
import type { Session } from "@supabase/supabase-js"
import Markdown from "react-markdown"
import { Loader2, RotateCwIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { apiFetch, type IncidentOut, type IncidentSummaryResponse } from "@/lib/api"

interface IncidentSummarizerProps {
  session: Session
  incident: IncidentOut
  /** Called after a successful regenerate, so a parent list can update its own copy too. */
  onSummaryUpdated?: (summary: string) => void
}

export function IncidentSummarizer({ session, incident, onSummaryUpdated }: IncidentSummarizerProps) {
  const [summary, setSummary] = useState<string | null>(incident.summary)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleRegenerate = async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await apiFetch<IncidentSummaryResponse>(
        `/api/v1/incidents/${incident.id}/resummarize`,
        session,
        { method: "POST" }
      )
      // Update local state directly from the response rather than re-fetching
      // the whole incident.
      setSummary(response.summary)
      onSummaryUpdated?.(response.summary)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to regenerate summary.")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-muted-foreground">AI Summary</span>
        <Button type="button" variant="outline" size="sm" onClick={handleRegenerate} disabled={loading}>
          {loading ? <Loader2 className="size-3.5 animate-spin" /> : <RotateCwIcon className="size-3.5" />}
          {loading ? "Regenerating…" : "Regenerate Summary"}
        </Button>
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
          <Loader2 className="size-4 animate-spin" />
          Generating summary…
        </div>
      )}

      {!loading && error && <p className="text-sm text-destructive">{error}</p>}

      {!loading && !error && (
        summary ? (
          // No rehype-raw plugin, so raw HTML (e.g. a literal <script> tag
          // quoted from an attacker's log payload — see rules.py's XSS
          // signature detection) renders as inert text, not executable markup.
          <div className="prose-sm max-w-none text-sm [&_ol]:my-1 [&_p]:my-1 [&_ul]:my-1">
            <Markdown>{summary}</Markdown>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">No summary yet.</p>
        )
      )}
    </div>
  )
}

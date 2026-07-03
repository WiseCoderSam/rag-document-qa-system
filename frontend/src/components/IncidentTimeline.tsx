import { useEffect, useMemo, useState } from "react"
import type { Session } from "@supabase/supabase-js"
import Markdown from "react-markdown"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { apiFetch, type IncidentOut } from "@/lib/api"

const SEVERITY_LEVELS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"] as const
type SeverityLevel = (typeof SEVERITY_LEVELS)[number]

function isSeverityLevel(value: string): value is SeverityLevel {
  return (SEVERITY_LEVELS as readonly string[]).includes(value)
}

// Node and badge colors come from the theme's severity ramp (--sev-* in
// src/index.css) — the same scale used by the Dashboard chart/badges and
// LogSearch's log-level badges, so severity reads identically everywhere.
// backend/app/rules.py only ever emits HIGH or CRITICAL today (LOW is just
// the column default per models.py:51); MEDIUM is kept anyway since the
// schema allows it.
const SEVERITY_NODE_CLASS: Record<SeverityLevel, string> = {
  CRITICAL: "bg-sev-critical",
  HIGH: "bg-sev-high",
  MEDIUM: "bg-sev-medium",
  LOW: "bg-sev-low",
}

const SEVERITY_BADGE_CLASS: Record<SeverityLevel, string> = {
  CRITICAL: "bg-sev-critical/20 text-sev-critical",
  HIGH: "bg-sev-high/15 text-sev-high",
  MEDIUM: "bg-sev-medium/15 text-sev-medium",
  LOW: "bg-sev-low/15 text-sev-low",
}

function severityNodeClass(severity: string): string {
  const level = severity.toUpperCase()
  return isSeverityLevel(level) ? SEVERITY_NODE_CLASS[level] : "bg-muted-foreground"
}

function severityBadgeClass(severity: string): string {
  const level = severity.toUpperCase()
  return isSeverityLevel(level) ? SEVERITY_BADGE_CLASS[level] : "bg-muted text-muted-foreground"
}

interface IncidentTimelineProps {
  session: Session
  /**
   * Scopes the Investigation Chat tab to this incident and switches to it.
   * Lifted up to Home.tsx (Task 5.4's ask) so InvestigationChat (Task 5.3)
   * doesn't need its own incident-fetch logic — see Home.tsx's
   * selectedIncidentId/handleLaunchChatForIncident.
   */
  onLaunchChat: (incidentId: number) => void
}

export function IncidentTimeline({ session, onLaunchChat }: IncidentTimelineProps) {
  const [incidents, setIncidents] = useState<IncidentOut[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [expandedIncidentId, setExpandedIncidentId] = useState<number | null>(null)

  useEffect(() => {
    let cancelled = false

    apiFetch<IncidentOut[]>("/api/v1/incidents", session)
      .then((data) => {
        if (!cancelled) setIncidents(data)
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message)
      })

    return () => {
      cancelled = true
    }
  }, [session])

  // GET /api/v1/incidents returns created_at desc (main.py:213-223, newest
  // first) for the Dashboard's "recent incidents" reading. A timeline reads
  // chronologically instead — oldest at top, newest at bottom — so reverse it.
  const chronological = useMemo(() => (incidents ? [...incidents].reverse() : null), [incidents])

  return (
    <Card>
      <CardHeader>
        <CardTitle>Incident Timeline</CardTitle>
        <CardDescription>Detected incidents in chronological order.</CardDescription>
      </CardHeader>
      <CardContent>
        {error && <p className="text-sm text-destructive">Failed to load incidents: {error}</p>}

        {chronological === null ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : chronological.length === 0 ? (
          <p className="text-sm text-muted-foreground">No incidents detected yet.</p>
        ) : (
          <ol className="flex flex-col gap-6 border-l-2 border-border pl-6">
            {chronological.map((incident) => {
              const isExpanded = expandedIncidentId === incident.id

              return (
                <li key={incident.id} className="relative">
                  <span
                    className={
                      "absolute top-1 -left-[1.6rem] size-3 rounded-full ring-4 ring-background " +
                      severityNodeClass(incident.severity)
                    }
                    aria-hidden="true"
                  />

                  <button
                    type="button"
                    className="flex w-full flex-col gap-1 text-left"
                    onClick={() => setExpandedIncidentId(isExpanded ? null : incident.id)}
                    aria-expanded={isExpanded}
                    aria-controls={`timeline-details-${incident.id}`}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium">{incident.rule_name}</span>
                      <Badge className={severityBadgeClass(incident.severity) + " font-mono"}>{incident.severity}</Badge>
                      <span className="font-mono text-xs text-muted-foreground">
                        {new Date(incident.created_at).toLocaleString()}
                      </span>
                    </div>
                    {/* Incident has no hostname column (see IncidentOut) — only affected_ip/affected_user. */}
                    <p className="font-mono text-xs text-muted-foreground">
                      {incident.affected_ip && <>IP: {incident.affected_ip} </>}
                      {incident.affected_user && <>User: {incident.affected_user}</>}
                      {!incident.affected_ip && !incident.affected_user && "No affected entities recorded."}
                    </p>
                  </button>

                  {isExpanded && (
                    <div id={`timeline-details-${incident.id}`} className="mt-3 flex flex-col gap-3 rounded-md border border-border p-3">
                      <div>
                        <span className="text-xs font-medium text-muted-foreground">Description</span>
                        <p className="text-sm">{incident.description}</p>
                      </div>

                      <div>
                        <span className="text-xs font-medium text-muted-foreground">AI Summary</span>
                        {incident.summary ? (
                          // Summary is Gemini-generated from log content that may
                          // legitimately contain a literal <script> tag (rules.py's
                          // XSS signature detection) — react-markdown renders it
                          // as inert text rather than raw HTML (no rehype-raw here).
                          <div className="prose-sm max-w-none text-sm [&_ol]:my-1 [&_p]:my-1 [&_ul]:my-1">
                            <Markdown>{incident.summary}</Markdown>
                          </div>
                        ) : (
                          // Don't assume IncidentSummarizer (Task 5.3) has already
                          // populated this — auto-summarization can also fail
                          // silently at ingestion time (see processor.py).
                          <p className="text-sm text-muted-foreground">No summary yet.</p>
                        )}
                      </div>

                      <Button type="button" size="sm" onClick={() => onLaunchChat(incident.id)}>
                        Launch RAG Investigation Chat
                      </Button>
                    </div>
                  )}
                </li>
              )
            })}
          </ol>
        )}
      </CardContent>
    </Card>
  )
}

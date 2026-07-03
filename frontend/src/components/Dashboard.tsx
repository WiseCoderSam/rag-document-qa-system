import { useEffect, useMemo, useState } from "react"
import type { Session } from "@supabase/supabase-js"
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { IncidentSummarizer } from "@/components/IncidentSummarizer"
import { apiFetch, type IncidentOut } from "@/lib/api"
import { exportToCSV, exportToPDF } from "@/lib/export"

// The schema allows LOW/MEDIUM/HIGH/CRITICAL (models.py: Incident.severity),
// but backend/app/rules.py's current rules only ever emit HIGH (brute force)
// or CRITICAL (SQL/XSS injection); LOW is just the column default and
// MEDIUM is unused today. All four are still rendered since the schema
// permits them.
const SEVERITY_LEVELS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"] as const
type SeverityLevel = (typeof SEVERITY_LEVELS)[number]

// Colors come from the theme's severity ramp (--sev-* in src/index.css) —
// the same four variables that drive the timeline nodes, log-level badges,
// and the header hairline, so severity reads identically everywhere.
const SEVERITY_BAR_STYLE: Record<SeverityLevel, { fill: string; fillOpacity: number }> = {
  LOW: { fill: "var(--sev-low)", fillOpacity: 0.9 },
  MEDIUM: { fill: "var(--sev-medium)", fillOpacity: 0.9 },
  HIGH: { fill: "var(--sev-high)", fillOpacity: 0.9 },
  CRITICAL: { fill: "var(--sev-critical)", fillOpacity: 0.9 },
}

const SEVERITY_BADGE_CLASS: Record<SeverityLevel, string> = {
  LOW: "bg-sev-low/15 text-sev-low",
  MEDIUM: "bg-sev-medium/15 text-sev-medium",
  HIGH: "bg-sev-high/15 text-sev-high",
  CRITICAL: "bg-sev-critical/20 text-sev-critical",
}

function isSeverityLevel(value: string): value is SeverityLevel {
  return (SEVERITY_LEVELS as readonly string[]).includes(value)
}

// Trimmed to the fields actually visible in the Recent Incidents list below,
// rather than dumping every IncidentOut field (id, log_file_id, status,
// etc.) — the export should match what's currently rendered on screen.
function buildIncidentExportRows(incidents: IncidentOut[]): Record<string, unknown>[] {
  return incidents.map((incident) => ({
    rule_name: incident.rule_name,
    severity: incident.severity,
    affected_ip: incident.affected_ip ?? "",
    affected_user: incident.affected_user ?? "",
    mitre_technique: incident.mitre_technique ?? "",
    created_at: incident.created_at,
  }))
}

const RECENT_PAGE_SIZE = 10

interface DashboardProps {
  session: Session
}

export function Dashboard({ session }: DashboardProps) {
  // Full incident set (unpaginated) — needed for the "Total incidents" stat
  // tile and the severity-breakdown chart below, both of which must reflect
  // every incident rather than one page of them.
  const [incidents, setIncidents] = useState<IncidentOut[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Separately paginated "Recent Incidents" list (its own state/offset), so
  // paging through it doesn't affect the totals/chart above.
  const [recentIncidents, setRecentIncidents] = useState<IncidentOut[] | null>(null)
  const [recentError, setRecentError] = useState<string | null>(null)
  const [recentLoading, setRecentLoading] = useState(false)
  const [recentOffset, setRecentOffset] = useState(0)

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

  const loadRecent = async (offset: number) => {
    setRecentLoading(true)
    try {
      const data = await apiFetch<IncidentOut[]>(
        `/api/v1/incidents?limit=${RECENT_PAGE_SIZE}&offset=${offset}`,
        session
      )
      setRecentIncidents(data)
      setRecentOffset(offset)
      setRecentError(null)
    } catch (err) {
      setRecentError(err instanceof Error ? err.message : "Failed to load incidents.")
    } finally {
      setRecentLoading(false)
    }
  }

  useEffect(() => {
    void loadRecent(0)
    // Only re-run when the session changes — loadRecent is intentionally
    // omitted since it's re-created every render but its identity isn't
    // what should trigger a re-fetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session])

  const severityCounts = useMemo(() => {
    const counts = new Map<SeverityLevel, number>(SEVERITY_LEVELS.map((level) => [level, 0]))
    for (const incident of incidents ?? []) {
      const level = incident.severity.toUpperCase()
      if (isSeverityLevel(level)) {
        counts.set(level, (counts.get(level) ?? 0) + 1)
      }
    }
    return SEVERITY_LEVELS.map((level) => ({ severity: level, count: counts.get(level) ?? 0 }))
  }, [incidents])

  const mayHaveMore = (recentIncidents?.length ?? 0) === RECENT_PAGE_SIZE

  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-4 sm:grid-cols-3">
        <Card>
          <CardHeader>
            <CardDescription className="font-mono text-xs tracking-widest uppercase">
              Total incidents
            </CardDescription>
            <CardTitle className="font-mono text-3xl font-medium tabular-nums">
              {incidents ? incidents.length : "…"}
            </CardTitle>
          </CardHeader>
        </Card>

        {/*
          Placeholder cards: the backend has no GET /api/v1/logs or
          /api/v1/files endpoint (only POST /api/v1/logs/upload exists), so
          there's no way to derive a real ingested-log-count or
          files-processed count. These are NOT backed by live data — the
          dimmed styling and "Not tracked yet" label are intentional, not a
          loading state.
        */}
        <Card className="opacity-50">
          <CardHeader>
            <CardDescription className="font-mono text-xs tracking-widest uppercase">
              Logs ingested · not tracked yet
            </CardDescription>
            <CardTitle className="font-mono text-3xl font-medium">—</CardTitle>
          </CardHeader>
        </Card>
        <Card className="opacity-50">
          <CardHeader>
            <CardDescription className="font-mono text-xs tracking-widest uppercase">
              Files processed · not tracked yet
            </CardDescription>
            <CardTitle className="font-mono text-3xl font-medium">—</CardTitle>
          </CardHeader>
        </Card>
      </div>

      {error && <p className="text-sm text-destructive">Failed to load incidents: {error}</p>}

      <Card>
        <CardHeader>
          <CardTitle>Incidents by Severity</CardTitle>
          <CardDescription>Breakdown of all incidents detected across your uploaded log files.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={severityCounts}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="severity" stroke="var(--muted-foreground)" fontSize={12} />
                <YAxis allowDecimals={false} stroke="var(--muted-foreground)" fontSize={12} />
                <Tooltip
                  cursor={{ fill: "var(--muted)" }}
                  contentStyle={{
                    backgroundColor: "var(--popover)",
                    color: "var(--popover-foreground)",
                    border: "1px solid var(--border)",
                    borderRadius: "var(--radius-md)",
                  }}
                />
                <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                  {severityCounts.map((entry) => (
                    <Cell
                      key={entry.severity}
                      fill={SEVERITY_BAR_STYLE[entry.severity].fill}
                      fillOpacity={SEVERITY_BAR_STYLE[entry.severity].fillOpacity}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Recent Incidents</CardTitle>
          <CardDescription>Most recently detected incidents, newest first.</CardDescription>
          {recentIncidents && recentIncidents.length > 0 && (
            <CardAction>
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => exportToCSV(buildIncidentExportRows(recentIncidents), "recent-incidents.csv")}
                >
                  Export CSV
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => exportToPDF("Recent Incidents Report", buildIncidentExportRows(recentIncidents))}
                >
                  Export PDF
                </Button>
              </div>
            </CardAction>
          )}
        </CardHeader>
        <CardContent>
          {recentError && <p className="mb-3 text-sm text-destructive">Failed to load incidents: {recentError}</p>}

          {recentIncidents === null ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : recentIncidents.length === 0 ? (
            <p className="text-sm text-muted-foreground">No incidents detected yet.</p>
          ) : (
            <>
              <ul className="flex flex-col gap-3">
                {recentIncidents.map((incident) => {
                  const severityLevel = incident.severity.toUpperCase()
                  const badgeClass = isSeverityLevel(severityLevel)
                    ? SEVERITY_BADGE_CLASS[severityLevel]
                    : "bg-muted text-muted-foreground"

                  const isExpanded = expandedIncidentId === incident.id

                  return (
                    <li key={incident.id} className="border-b border-border pb-3 last:border-b-0 last:pb-0">
                      <button
                        type="button"
                        className="flex w-full flex-wrap items-center justify-between gap-2 text-left"
                        onClick={() => setExpandedIncidentId(isExpanded ? null : incident.id)}
                        aria-expanded={isExpanded}
                        aria-controls={`incident-details-${incident.id}`}
                      >
                        <div className="flex flex-col gap-1">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-medium">{incident.rule_name}</span>
                            <Badge className={badgeClass + " font-mono"}>{incident.severity}</Badge>
                          </div>
                          <p className="font-mono text-xs text-muted-foreground">
                            {incident.affected_ip && <>IP: {incident.affected_ip} </>}
                            {incident.affected_user && <>User: {incident.affected_user} </>}
                            {incident.mitre_technique && <>· MITRE {incident.mitre_technique}</>}
                          </p>
                        </div>
                        <span className="font-mono text-xs whitespace-nowrap text-muted-foreground">
                          {new Date(incident.created_at).toLocaleString()}
                        </span>
                      </button>
                      {isExpanded && (
                        <div id={`incident-details-${incident.id}`} className="mt-3 rounded-md border border-border p-3">
                          <IncidentSummarizer
                            session={session}
                            incident={incident}
                            onSummaryUpdated={(summary) => {
                              setRecentIncidents((prev) =>
                                (prev ?? []).map((i) => (i.id === incident.id ? { ...i, summary } : i))
                              )
                            }}
                          />
                        </div>
                      )}
                    </li>
                  )
                })}
              </ul>

              <div className="mt-3 flex items-center justify-between gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => void loadRecent(Math.max(0, recentOffset - RECENT_PAGE_SIZE))}
                  disabled={recentOffset === 0 || recentLoading}
                >
                  Previous
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => void loadRecent(recentOffset + RECENT_PAGE_SIZE)}
                  disabled={!mayHaveMore || recentLoading}
                >
                  Next
                </Button>
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

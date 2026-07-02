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

// Colors are drawn from the theme's existing CSS variables (src/index.css)
// rather than invented hex values. This palette has no yellow/orange
// "warning" hue, so LOW/MEDIUM reuse the neutral --muted-foreground and
// HIGH/CRITICAL reuse --destructive, differentiated by opacity — the same
// "soft vs solid" treatment the destructive Button/Badge variants already use.
const SEVERITY_BAR_STYLE: Record<SeverityLevel, { fill: string; fillOpacity: number }> = {
  LOW: { fill: "var(--muted-foreground)", fillOpacity: 0.5 },
  MEDIUM: { fill: "var(--muted-foreground)", fillOpacity: 1 },
  HIGH: { fill: "var(--destructive)", fillOpacity: 0.5 },
  CRITICAL: { fill: "var(--destructive)", fillOpacity: 1 },
}

const SEVERITY_BADGE_CLASS: Record<SeverityLevel, string> = {
  LOW: "bg-muted text-muted-foreground",
  MEDIUM: "bg-muted text-foreground",
  HIGH: "bg-destructive/10 text-destructive",
  CRITICAL: "bg-destructive/25 text-destructive",
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

interface DashboardProps {
  session: Session
}

export function Dashboard({ session }: DashboardProps) {
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

  const recentIncidents = useMemo(() => (incidents ?? []).slice(0, 10), [incidents])

  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-4 sm:grid-cols-3">
        <Card>
          <CardHeader>
            <CardDescription>Total Incidents</CardDescription>
            <CardTitle className="text-2xl">{incidents ? incidents.length : "…"}</CardTitle>
          </CardHeader>
        </Card>

        {/*
          Placeholder cards: the backend has no GET /api/v1/logs or
          /api/v1/files endpoint (only POST /api/v1/logs/upload exists), so
          there's no way to derive a real ingested-log-count or
          files-processed count. These are NOT backed by live data — the
          dimmed styling and "(placeholder)" label are intentional, not a
          loading state.
        */}
        <Card className="opacity-60">
          <CardHeader>
            <CardDescription>Logs Ingested (placeholder)</CardDescription>
            <CardTitle className="text-2xl">—</CardTitle>
          </CardHeader>
        </Card>
        <Card className="opacity-60">
          <CardHeader>
            <CardDescription>Files Processed (placeholder)</CardDescription>
            <CardTitle className="text-2xl">—</CardTitle>
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
          {recentIncidents.length > 0 && (
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
          {incidents === null ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : recentIncidents.length === 0 ? (
            <p className="text-sm text-muted-foreground">No incidents detected yet.</p>
          ) : (
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
                          <Badge className={badgeClass}>{incident.severity}</Badge>
                        </div>
                        <p className="text-xs text-muted-foreground">
                          {incident.affected_ip && <>IP: {incident.affected_ip} </>}
                          {incident.affected_user && <>User: {incident.affected_user} </>}
                          {incident.mitre_technique && <>· MITRE {incident.mitre_technique}</>}
                        </p>
                      </div>
                      <span className="text-xs whitespace-nowrap text-muted-foreground">
                        {new Date(incident.created_at).toLocaleString()}
                      </span>
                    </button>
                    {isExpanded && (
                      <div id={`incident-details-${incident.id}`} className="mt-3 rounded-md border border-border p-3">
                        <IncidentSummarizer
                          session={session}
                          incident={incident}
                          onSummaryUpdated={(summary) => {
                            setIncidents((prev) =>
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
          )}
        </CardContent>
      </Card>
    </div>
  )
}

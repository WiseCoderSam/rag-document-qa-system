import { useState, type FormEvent, type ReactNode } from "react"
import type { Session } from "@supabase/supabase-js"
import { Loader2 } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { apiFetch, type LogEntryOut } from "@/lib/api"
import { exportToCSV, exportToPDF } from "@/lib/export"

// Matches backend/app/main.py:337-391's query params exactly (ip, user,
// hostname, event_id, severity, file_id, limit, offset).
interface FilterState {
  ip: string
  user: string
  hostname: string
  eventId: string
  severity: string
  fileId: string
}

const EMPTY_FILTERS: FilterState = {
  ip: "",
  user: "",
  hostname: "",
  eventId: "",
  severity: "",
  fileId: "",
}

const PAGE_SIZE = 25

// LogEntry.severity values come from backend/app/parser.py (INFO / WARNING /
// ERROR / CRITICAL) — a different vocabulary from Incident.severity's
// LOW/MEDIUM/HIGH/CRITICAL used in Dashboard.tsx, so this is its own small
// map rather than a shared one. Same "soft muted vs soft/solid destructive"
// treatment though, built only from existing CSS variables — no invented colors.
const SEVERITY_BADGE_CLASS: Record<string, string> = {
  INFO: "bg-muted text-muted-foreground",
  WARNING: "bg-muted text-foreground",
  ERROR: "bg-destructive/10 text-destructive",
  CRITICAL: "bg-destructive/25 text-destructive",
}

function severityBadgeClass(severity: string): string {
  return SEVERITY_BADGE_CLASS[severity.toUpperCase()] ?? "bg-muted text-muted-foreground"
}

function hasAnyFilter(filters: FilterState): boolean {
  return Object.values(filters).some((value) => value.trim() !== "")
}

// Trimmed to the columns actually shown in the results table below, rather
// than dumping every LogEntryOut field — the export should match what's
// currently rendered/filtered on screen.
function buildLogExportRows(entries: LogEntryOut[]): Record<string, unknown>[] {
  return entries.map((entry) => ({
    timestamp: entry.timestamp ?? "",
    severity: entry.severity,
    ip: entry.ip_address ?? "",
    user: entry.user_name ?? "",
    hostname: entry.hostname ?? "",
    message: entry.message,
  }))
}

function buildSearchParams(filters: FilterState, offset: number): URLSearchParams {
  const params = new URLSearchParams()
  if (filters.ip.trim()) params.set("ip", filters.ip.trim())
  if (filters.user.trim()) params.set("user", filters.user.trim())
  if (filters.hostname.trim()) params.set("hostname", filters.hostname.trim())
  if (filters.eventId.trim()) params.set("event_id", filters.eventId.trim())
  if (filters.severity.trim()) params.set("severity", filters.severity.trim())
  if (filters.fileId.trim()) params.set("file_id", filters.fileId.trim())
  params.set("limit", String(PAGE_SIZE))
  params.set("offset", String(offset))
  return params
}

interface LogSearchProps {
  session: Session
}

export function LogSearch({ session }: LogSearchProps) {
  const [filters, setFilters] = useState<FilterState>(EMPTY_FILTERS)
  const [appliedFilters, setAppliedFilters] = useState<FilterState | null>(null)
  const [offset, setOffset] = useState(0)
  const [results, setResults] = useState<LogEntryOut[]>([])
  const [hasSearched, setHasSearched] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [validationError, setValidationError] = useState<string | null>(null)
  const [selectedEntry, setSelectedEntry] = useState<LogEntryOut | null>(null)

  const runSearch = async (searchFilters: FilterState, searchOffset: number) => {
    setLoading(true)
    setError(null)
    try {
      const params = buildSearchParams(searchFilters, searchOffset)
      const data = await apiFetch<LogEntryOut[]>(`/api/v1/logs/search?${params.toString()}`, session)
      setResults(data)
      setOffset(searchOffset)
      setAppliedFilters(searchFilters)
      setHasSearched(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search failed.")
    } finally {
      setLoading(false)
    }
  }

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault()

    // Enforce the same "at least one filter" rule the backend enforces
    // (main.py:358-362) before firing the request, so a filterless search
    // shows an inline message instead of surfacing the 400 as a generic error.
    if (!hasAnyFilter(filters)) {
      setValidationError("Enter at least one of IP, User, Hostname, Event ID, Severity, or File ID to search.")
      return
    }

    setValidationError(null)
    void runSearch(filters, 0)
  }

  const handlePrevious = () => {
    if (!appliedFilters) return
    void runSearch(appliedFilters, Math.max(0, offset - PAGE_SIZE))
  }

  const handleNext = () => {
    if (!appliedFilters) return
    void runSearch(appliedFilters, offset + PAGE_SIZE)
  }

  const updateFilter = (key: keyof FilterState) => (event: React.ChangeEvent<HTMLInputElement>) => {
    setFilters((prev) => ({ ...prev, [key]: event.target.value }))
  }

  // results.length === PAGE_SIZE is a heuristic, not a real total count —
  // the backend response has no total, so this is the best available signal
  // that a next page might exist.
  const mayHaveMore = results.length === PAGE_SIZE

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle>Search Logs</CardTitle>
          <CardDescription>Search by IP, user, hostname, event ID, severity, or file ID.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="flex flex-col gap-3">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              <FilterField id="filter-ip" label="IP Address" value={filters.ip} onChange={updateFilter("ip")} disabled={loading} placeholder="e.g. 10.0.0.5" />
              <FilterField id="filter-user" label="User" value={filters.user} onChange={updateFilter("user")} disabled={loading} placeholder="e.g. admin" />
              <FilterField id="filter-hostname" label="Hostname" value={filters.hostname} onChange={updateFilter("hostname")} disabled={loading} placeholder="e.g. webserver01" />
              <FilterField id="filter-event-id" label="Event ID" value={filters.eventId} onChange={updateFilter("eventId")} disabled={loading} placeholder="e.g. AUTH_FAILURE" />
              <FilterField id="filter-severity" label="Severity" value={filters.severity} onChange={updateFilter("severity")} disabled={loading} placeholder="e.g. CRITICAL" />
              <FilterField id="filter-file-id" label="File ID" value={filters.fileId} onChange={updateFilter("fileId")} disabled={loading} placeholder="e.g. 3" />
            </div>

            {validationError && <p className="text-sm text-destructive">{validationError}</p>}

            <div className="flex items-center gap-2">
              <Button type="submit" disabled={loading}>
                Search
              </Button>
              {loading && <Loader2 className="size-4 animate-spin text-muted-foreground" />}
            </div>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Results</CardTitle>
          {hasSearched && (
            <CardDescription>
              {results.length} result{results.length === 1 ? "" : "s"} on this page.
            </CardDescription>
          )}
          {results.length > 0 && (
            <CardAction>
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => exportToCSV(buildLogExportRows(results), "log-search-results.csv")}
                >
                  Export CSV
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => exportToPDF("Log Search Results", buildLogExportRows(results))}
                >
                  Export PDF
                </Button>
              </div>
            </CardAction>
          )}
        </CardHeader>
        <CardContent>
          {error && <p className="mb-3 text-sm text-destructive">Search failed: {error}</p>}

          {!hasSearched ? (
            <p className="text-sm text-muted-foreground">Enter a filter above and click Search.</p>
          ) : results.length === 0 ? (
            <p className="text-sm text-muted-foreground">No matching log entries found.</p>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Timestamp</TableHead>
                    <TableHead>Severity</TableHead>
                    <TableHead>IP</TableHead>
                    <TableHead>User</TableHead>
                    <TableHead>Hostname</TableHead>
                    <TableHead>Message</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {results.map((entry) => (
                    <TableRow key={entry.id} className="cursor-pointer" onClick={() => setSelectedEntry(entry)}>
                      <TableCell className="text-muted-foreground">
                        {entry.timestamp ? new Date(entry.timestamp).toLocaleString() : "N/A"}
                      </TableCell>
                      <TableCell>
                        <Badge className={severityBadgeClass(entry.severity)}>{entry.severity}</Badge>
                      </TableCell>
                      <TableCell>{entry.ip_address ?? "—"}</TableCell>
                      <TableCell>{entry.user_name ?? "—"}</TableCell>
                      <TableCell>{entry.hostname ?? "—"}</TableCell>
                      <TableCell className="max-w-xs truncate whitespace-nowrap">{entry.message}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>

              <div className="mt-3 flex items-center justify-between gap-2">
                <Button type="button" variant="outline" size="sm" onClick={handlePrevious} disabled={offset === 0 || loading}>
                  Previous
                </Button>
                <Button type="button" variant="outline" size="sm" onClick={handleNext} disabled={!mayHaveMore || loading}>
                  Next
                </Button>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      <Sheet
        open={selectedEntry !== null}
        onOpenChange={(open) => {
          if (!open) setSelectedEntry(null)
        }}
      >
        <SheetContent>
          <SheetHeader>
            <SheetTitle>Log Entry #{selectedEntry?.id}</SheetTitle>
            <SheetDescription>Full details for this log entry.</SheetDescription>
          </SheetHeader>
          {selectedEntry && (
            <div className="flex flex-col gap-3 overflow-y-auto px-4 pb-4">
              <DetailRow label="Timestamp" value={selectedEntry.timestamp ? new Date(selectedEntry.timestamp).toLocaleString() : "N/A"} />
              <DetailRow label="Severity" value={<Badge className={severityBadgeClass(selectedEntry.severity)}>{selectedEntry.severity}</Badge>} />
              <DetailRow label="IP Address" value={selectedEntry.ip_address ?? "—"} />
              <DetailRow label="User" value={selectedEntry.user_name ?? "—"} />
              <DetailRow label="Hostname" value={selectedEntry.hostname ?? "—"} />
              <DetailRow label="Event ID" value={selectedEntry.event_id ?? "—"} />
              <DetailRow label="File ID" value={String(selectedEntry.file_id)} />
              <div className="flex flex-col gap-1">
                <span className="text-xs font-medium text-muted-foreground">Message</span>
                <p className="rounded-md border border-border bg-muted/30 p-2 text-sm whitespace-pre-wrap">
                  {selectedEntry.message}
                </p>
              </div>
            </div>
          )}
        </SheetContent>
      </Sheet>
    </div>
  )
}

function FilterField({
  id,
  label,
  value,
  onChange,
  disabled,
  placeholder,
}: {
  id: string
  label: string
  value: string
  onChange: (event: React.ChangeEvent<HTMLInputElement>) => void
  disabled: boolean
  placeholder: string
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} value={value} onChange={onChange} disabled={disabled} placeholder={placeholder} />
    </div>
  )
}

function DetailRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <span className="text-sm">{value}</span>
    </div>
  )
}

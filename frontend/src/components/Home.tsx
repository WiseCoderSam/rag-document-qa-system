import { useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { Dashboard } from "@/components/Dashboard"
import { Documents } from "@/components/Documents"
import { IncidentTimeline } from "@/components/IncidentTimeline"
import { InvestigationChat } from "@/components/InvestigationChat"
import { LogSearch } from "@/components/LogSearch"
import { LogUpload } from "@/components/LogUpload"
import { useAuth } from "@/context/AuthContext"
import { apiFetch } from "@/lib/api"

interface UserProfile {
  id: string
  email: string
}

// Shared tab shell for Tasks 5.2-5.4 (search / chat / timeline panels).
// Kept generic on purpose: this file just switches over the active tab and
// renders whichever panel is wired up, rather than encoding any
// panel-specific logic here.
type Tab = "dashboard" | "search" | "chat" | "timeline" | "documents" | "logs"

const TABS: { id: Tab; label: string }[] = [
  { id: "dashboard", label: "Dashboard" },
  { id: "logs", label: "Upload Logs" },
  { id: "search", label: "Search" },
  { id: "chat", label: "Chat" },
  { id: "timeline", label: "Timeline" },
  { id: "documents", label: "Documents" },
]

export function Home() {
  const { session, signOut } = useAuth()
  const [profile, setProfile] = useState<UserProfile | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<Tab>("dashboard")
  // Lifted state (Task 5.4): IncidentTimeline's "Launch RAG Investigation
  // Chat" button sets this and switches to the chat tab, so
  // InvestigationChat (Task 5.3) gets scoped to a specific incident without
  // needing its own incident-fetch logic. Do not remove this when touching
  // Task 5.3's code — it depends on this state existing here.
  const [selectedIncidentId, setSelectedIncidentId] = useState<number | null>(null)
  const [chatDocumentId, setChatDocumentId] = useState<number | null>(null)

  const handleLaunchChatForIncident = (incidentId: number) => {
    setSelectedIncidentId(incidentId)
    setActiveTab("chat")
  }

  const handleChatWithDocument = (documentId: number) => {
    setChatDocumentId(documentId)
    setSelectedIncidentId(null)
    setActiveTab("chat")
  }

  useEffect(() => {
    if (!session) return

    apiFetch<UserProfile>("/api/v1/users/me", session)
      .then(setProfile)
      .catch((err: Error) => setError(err.message))
  }, [session])

  return (
    <div className="flex min-h-svh flex-col">
      <div className="severity-spectrum h-0.5 shrink-0" aria-hidden="true" />

      <div className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-5 px-4 pt-5 pb-6">
        <header className="flex flex-wrap items-end justify-between gap-3">
          <div className="flex flex-col gap-1">
            <p className="font-mono text-[11px] tracking-[0.25em] text-primary uppercase">
              Security operations console
            </p>
            <h1 className="font-display text-xl font-semibold tracking-tight">
              Log Monitoring &amp; Threat Detection
            </h1>
            {profile && (
              <p className="font-mono text-xs text-muted-foreground">{profile.email}</p>
            )}
            {error && <p className="text-sm text-destructive">Failed to load profile: {error}</p>}
          </div>
          <Button variant="outline" size="sm" onClick={signOut}>
            Sign out
          </Button>
        </header>

        <nav className="flex gap-1 overflow-x-auto border-b border-border" aria-label="Console sections">
          {TABS.map((tab) => {
            const isActive = activeTab === tab.id
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id)}
                aria-current={isActive ? "page" : undefined}
                className={
                  "-mb-px border-b-2 px-3 py-2 font-mono text-xs tracking-widest whitespace-nowrap uppercase transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring/50 " +
                  (isActive
                    ? "border-primary text-foreground"
                    : "border-transparent text-muted-foreground hover:border-border hover:text-foreground")
                }
              >
                {tab.label}
              </button>
            )
          })}
        </nav>

        <main key={activeTab} className="panel-enter flex-1">
          {activeTab === "dashboard" && session && <Dashboard session={session} />}
          {activeTab === "logs" && session && <LogUpload session={session} />}
          {activeTab === "search" && session && <LogSearch session={session} />}
          {activeTab === "chat" && session && (
            // key remounts (resets conversation state) whenever the scope
            // changes, e.g. general chat -> a specific incident's chat.
            <InvestigationChat
              key={selectedIncidentId ?? chatDocumentId ?? "general"}
              session={session}
              incidentId={selectedIncidentId ?? undefined}
              fileId={chatDocumentId ?? undefined}
              onClearScope={() => {
                setSelectedIncidentId(null)
                setChatDocumentId(null)
              }}
            />
          )}
          {activeTab === "timeline" && session && (
            <IncidentTimeline session={session} onLaunchChat={handleLaunchChatForIncident} />
          )}
          {activeTab === "documents" && session && (
            <Documents session={session} onChatWithDocument={handleChatWithDocument} />
          )}
        </main>
      </div>
    </div>
  )
}

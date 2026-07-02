import { useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { Dashboard } from "@/components/Dashboard"
import { IncidentTimeline } from "@/components/IncidentTimeline"
import { InvestigationChat } from "@/components/InvestigationChat"
import { LogSearch } from "@/components/LogSearch"
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
type Tab = "dashboard" | "search" | "chat" | "timeline"

const TABS: { id: Tab; label: string }[] = [
  { id: "dashboard", label: "Dashboard" },
  { id: "search", label: "Search" },
  { id: "chat", label: "Chat" },
  { id: "timeline", label: "Timeline" },
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

  const handleLaunchChatForIncident = (incidentId: number) => {
    setSelectedIncidentId(incidentId)
    setActiveTab("chat")
  }

  useEffect(() => {
    if (!session) return

    apiFetch<UserProfile>("/api/v1/users/me", session)
      .then(setProfile)
      .catch((err: Error) => setError(err.message))
  }, [session])

  return (
    <div className="mx-auto flex min-h-svh max-w-6xl flex-col gap-4 p-4">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold">Log Monitoring & Threat Detection Platform</h1>
          {profile && (
            <p className="text-sm text-muted-foreground">
              Signed in as {profile.email} ({profile.id})
            </p>
          )}
          {error && <p className="text-sm text-destructive">Failed to load profile: {error}</p>}
        </div>
        <Button variant="outline" onClick={signOut}>
          Sign out
        </Button>
      </header>

      <nav className="flex gap-2 border-b border-border pb-2">
        {TABS.map((tab) => (
          <Button
            key={tab.id}
            type="button"
            variant={activeTab === tab.id ? "secondary" : "ghost"}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </Button>
        ))}
      </nav>

      <main className="flex-1">
        {activeTab === "dashboard" && session && <Dashboard session={session} />}
        {activeTab === "search" && session && <LogSearch session={session} />}
        {activeTab === "chat" && session && (
          // key remounts (resets conversation state) whenever the scope
          // changes, e.g. general chat -> a specific incident's chat.
          <InvestigationChat
            key={selectedIncidentId ?? "general"}
            session={session}
            incidentId={selectedIncidentId ?? undefined}
            onClearScope={() => setSelectedIncidentId(null)}
          />
        )}
        {activeTab === "timeline" && session && (
          <IncidentTimeline session={session} onLaunchChat={handleLaunchChatForIncident} />
        )}
      </main>
    </div>
  )
}

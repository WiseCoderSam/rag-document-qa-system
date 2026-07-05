import { useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { Documents } from "@/components/Documents"
import { ErrorBoundary } from "@/components/ErrorBoundary"
import { InvestigationChat } from "@/components/InvestigationChat"
import { useAuth } from "@/context/AuthContext"
import { apiFetch, type DocumentOut } from "@/lib/api"

interface UserProfile {
  id: string
  email: string
}

type Tab = "documents" | "chat"

const TABS: { id: Tab; label: string }[] = [
  { id: "documents", label: "Documents" },
  { id: "chat", label: "Chat" },
]

export function Home() {
  const { session, signOut } = useAuth()
  const [profile, setProfile] = useState<UserProfile | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<Tab>("documents")
  // Set by Documents' "Chat with this document" button: scopes the chat tab
  // to one document and switches to it. Kept here (not in InvestigationChat)
  // so the scope survives tab switches.
  const [chatDocument, setChatDocument] = useState<DocumentOut | null>(null)

  const handleChatWithDocument = (document: DocumentOut) => {
    setChatDocument(document)
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
              AI document assistant
            </p>
            <h1 className="font-display text-xl font-semibold tracking-tight">
              Document Q&amp;A
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

        <nav className="flex gap-1 overflow-x-auto border-b border-border" aria-label="Sections">
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

        {/* Both panels stay mounted; the inactive one is hidden with CSS.
            This preserves in-progress state — most importantly the chat
            conversation, which used to be wiped by a tab switch. */}
        <main className="flex-1">
          <div className={activeTab === "documents" ? "panel-enter" : "hidden"}>
            <ErrorBoundary>
              {session && <Documents session={session} onChatWithDocument={handleChatWithDocument} />}
            </ErrorBoundary>
          </div>
          <div className={activeTab === "chat" ? "panel-enter" : "hidden"}>
            <ErrorBoundary>
              {session && (
                // key remounts (resets conversation state) whenever the scope
                // changes, e.g. all-documents chat -> a specific document's chat.
                <InvestigationChat
                  key={chatDocument?.id ?? "general"}
                  session={session}
                  documentId={chatDocument?.id}
                  documentName={chatDocument?.filename}
                  onClearScope={() => setChatDocument(null)}
                />
              )}
            </ErrorBoundary>
          </div>
        </main>
      </div>
    </div>
  )
}

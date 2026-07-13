import { useEffect, useRef, useState, type ReactNode } from "react"

import { Home } from "@/components/Home"
import { Toaster } from "@/components/ui/toast"
import { WakeScreen } from "@/components/WakeScreen"
import { AuthProvider, useAuth } from "@/context/AuthContext"
import { checkHealth } from "@/lib/api"
import { Auth } from "@/pages/Auth"

const SHOW_LOADER_AFTER_MS = 1500 // warm backends answer well under this — no flash
const ONLINE_FLASH_MS = 750

type Phase = "checking" | "waking" | "online" | "ready"

/**
 * Gates the authenticated app behind a backend health check so a free-tier
 * cold start (server asleep after inactivity) shows the WakeScreen instead of
 * a broken-looking console making failing requests. Warm backends resolve
 * before SHOW_LOADER_AFTER_MS, so nothing flashes in the common case.
 */
function WakeGate({ children }: { children: ReactNode }) {
  const [phase, setPhase] = useState<Phase>("checking")
  const phaseRef = useRef(phase)
  phaseRef.current = phase

  useEffect(() => {
    let cancelled = false
    const showTimer = setTimeout(() => {
      if (!cancelled) setPhase((p) => (p === "checking" ? "waking" : p))
    }, SHOW_LOADER_AFTER_MS)

    ;(async () => {
      // Poll until healthy. On a cold start the fetch itself hangs until the
      // instance wakes; if the host returns an early 5xx we retry.
      while (!cancelled && !(await checkHealth())) {
        await new Promise((r) => setTimeout(r, 2000))
      }
      if (cancelled) return
      clearTimeout(showTimer)
      // Flash "online" only if we actually showed the waking screen.
      setPhase(phaseRef.current === "waking" ? "online" : "ready")
    })()

    return () => {
      cancelled = true
      clearTimeout(showTimer)
    }
  }, [])

  useEffect(() => {
    if (phase !== "online") return
    const t = setTimeout(() => setPhase("ready"), ONLINE_FLASH_MS)
    return () => clearTimeout(t)
  }, [phase])

  if (phase === "ready") return <>{children}</>
  if (phase === "waking" || phase === "online") return <WakeScreen online={phase === "online"} />
  return null // "checking": brief blank; the warm path resolves here in <300ms
}

function AppContent() {
  const { user, loading } = useAuth()

  if (loading) {
    return <div className="flex min-h-svh items-center justify-center">Loading...</div>
  }

  return user ? (
    <WakeGate>
      <Home />
    </WakeGate>
  ) : (
    <Auth />
  )
}

function App() {
  return (
    <AuthProvider>
      <AppContent />
      <Toaster />
    </AuthProvider>
  )
}

export default App

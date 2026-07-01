import { useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { useAuth } from "@/context/AuthContext"

interface UserProfile {
  id: string
  email: string
}

export function Home() {
  const { session, signOut } = useAuth()
  const [profile, setProfile] = useState<UserProfile | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!session) return

    const apiUrl = import.meta.env.VITE_API_URL ?? "http://localhost:8000"

    fetch(`${apiUrl}/api/v1/users/me`, {
      headers: { Authorization: `Bearer ${session.access_token}` },
    })
      .then(async (res) => {
        if (!res.ok) throw new Error(`Request failed with status ${res.status}`)
        return res.json() as Promise<UserProfile>
      })
      .then(setProfile)
      .catch((err: Error) => setError(err.message))
  }, [session])

  return (
    <div className="flex min-h-svh flex-col items-center justify-center gap-4">
      <h1 className="text-2xl font-semibold">Log Monitoring & Threat Detection Platform</h1>
      {profile && (
        <p className="text-sm text-muted-foreground">
          Signed in as {profile.email} ({profile.id})
        </p>
      )}
      {error && <p className="text-sm text-destructive">Failed to load profile: {error}</p>}
      <Button variant="outline" onClick={signOut}>
        Sign out
      </Button>
    </div>
  )
}

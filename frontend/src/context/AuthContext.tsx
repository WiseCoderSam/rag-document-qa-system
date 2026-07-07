import type { Session, User } from "@supabase/supabase-js"
import { createContext, useContext, useEffect, useState, type ReactNode } from "react"

import { supabase } from "@/lib/supabase"

interface AuthContextValue {
  user: User | null
  session: Session | null
  loading: boolean
  signIn: (email: string, password: string) => Promise<{ error: string | null }>
  signUp: (email: string, password: string) => Promise<{ error: string | null }>
  signInWithGoogle: () => Promise<{ error: string | null }>
  resendConfirmation: (email: string) => Promise<{ error: string | null }>
  signOut: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined)

// GoTrue returns an empty body (message "{}") when it can't reach the SMTP
// provider, so map blank/unparseable messages to something actionable.
function normalizeAuthError(error: { message?: string } | null): string | null {
  if (!error) return null
  const message = error.message?.trim()
  if (!message || message === "{}" || message === "[object Object]") {
    return "The server couldn't send the email. Please try again in a few minutes."
  }
  return message
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session)
      setLoading(false)
    })

    const { data: subscription } = supabase.auth.onAuthStateChange((_event, newSession) => {
      setSession(newSession)
    })

    return () => subscription.subscription.unsubscribe()
  }, [])

  const signIn: AuthContextValue["signIn"] = async (email, password) => {
    const { error } = await supabase.auth.signInWithPassword({ email, password })
    return { error: normalizeAuthError(error) }
  }

  const signUp: AuthContextValue["signUp"] = async (email, password) => {
    const { error } = await supabase.auth.signUp({
      email,
      password,
      options: { emailRedirectTo: window.location.origin },
    })
    return { error: normalizeAuthError(error) }
  }

  const signInWithGoogle: AuthContextValue["signInWithGoogle"] = async () => {
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: window.location.origin },
    })
    return { error: normalizeAuthError(error) }
  }

  const resendConfirmation: AuthContextValue["resendConfirmation"] = async (email) => {
    const { error } = await supabase.auth.resend({
      type: "signup",
      email,
      options: { emailRedirectTo: window.location.origin },
    })
    return { error: normalizeAuthError(error) }
  }

  const signOut = async () => {
    await supabase.auth.signOut()
  }

  return (
    <AuthContext.Provider
      value={{
        user: session?.user ?? null,
        session,
        loading,
        signIn,
        signUp,
        signInWithGoogle,
        resendConfirmation,
        signOut,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider")
  }
  return context
}

import { useState, type FormEvent } from "react"

import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useAuth } from "@/context/AuthContext"

function GoogleIcon() {
  return (
    <svg viewBox="0 0 18 18" aria-hidden="true" className="size-4">
      <path
        fill="#4285F4"
        d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844a4.14 4.14 0 0 1-1.796 2.716v2.259h2.908c1.702-1.567 2.684-3.875 2.684-6.615Z"
      />
      <path
        fill="#34A853"
        d="M9 18c2.43 0 4.467-.806 5.956-2.184l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 0 0 9 18Z"
      />
      <path
        fill="#FBBC05"
        d="M3.964 10.706A5.41 5.41 0 0 1 3.682 9c0-.593.102-1.17.282-1.706V4.962H.957A8.997 8.997 0 0 0 0 9c0 1.452.348 2.827.957 4.038l3.007-2.332Z"
      />
      <path
        fill="#EA4335"
        d="M9 3.583c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 0 0 .957 4.962L3.964 7.294C4.672 5.167 6.656 3.583 9 3.583Z"
      />
    </svg>
  )
}

function MailIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className="size-6"
    >
      <rect x="2" y="4" width="20" height="16" rx="2" />
      <path d="m2 7 10 6 10-6" />
    </svg>
  )
}

export function Auth() {
  const { signIn, signUp, signInWithGoogle, resendConfirmation } = useAuth()
  const [mode, setMode] = useState<"login" | "signup">("login")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [googleSubmitting, setGoogleSubmitting] = useState(false)
  // When set, a confirmation email was just sent — show the "check your inbox" screen.
  const [pendingEmail, setPendingEmail] = useState<string | null>(null)
  const [resending, setResending] = useState(false)

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    setError(null)
    setInfo(null)
    setSubmitting(true)

    const { error: authError } =
      mode === "login" ? await signIn(email, password) : await signUp(email, password)

    if (authError) {
      setError(authError)
    } else if (mode === "signup") {
      setPendingEmail(email)
    }

    setSubmitting(false)
  }

  const handleGoogle = async () => {
    setError(null)
    setInfo(null)
    setGoogleSubmitting(true)
    const { error: authError } = await signInWithGoogle()
    if (authError) {
      setError(authError)
      setGoogleSubmitting(false)
    }
    // On success the browser is redirected to Google, so no need to reset state.
  }

  const handleResend = async () => {
    if (!pendingEmail) return
    setError(null)
    setInfo(null)
    setResending(true)
    const { error: resendError } = await resendConfirmation(pendingEmail)
    if (resendError) {
      setError(resendError)
    } else {
      setInfo("Confirmation email sent again.")
    }
    setResending(false)
  }

  const toggleMode = () => {
    setMode(mode === "login" ? "signup" : "login")
    setError(null)
    setInfo(null)
  }

  return (
    <div className="flex min-h-svh flex-col">
      <div className="severity-spectrum h-0.5 shrink-0" aria-hidden="true" />
      <div className="flex flex-1 flex-col items-center justify-center gap-6 p-4">
        <div className="flex flex-col items-center gap-1 text-center">
          <p className="font-mono text-[11px] tracking-[0.25em] text-primary uppercase">
            Security operations console
          </p>
          <h1 className="font-display text-2xl font-semibold tracking-tight">
            Log Monitoring &amp; Threat Detection
          </h1>
        </div>

        {pendingEmail ? (
          <Card className="w-full max-w-sm">
            <CardHeader className="items-center text-center">
              <div className="mb-2 flex size-12 items-center justify-center rounded-full bg-primary/10 text-primary">
                <MailIcon />
              </div>
              <CardTitle className="font-display text-xl">Confirm your email</CardTitle>
              <CardDescription>
                We sent a confirmation link to{" "}
                <span className="font-medium text-foreground">{pendingEmail}</span>. Click it to
                activate your account, then sign in.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              {error && <p className="text-sm text-destructive">{error}</p>}
              {info && <p className="text-sm text-muted-foreground">{info}</p>}
              <Button
                type="button"
                variant="outline"
                className="w-full"
                onClick={handleResend}
                disabled={resending}
              >
                {resending ? "Sending..." : "Resend confirmation email"}
              </Button>
              <p className="text-center text-xs text-muted-foreground">
                Wrong address or didn&apos;t get it? Check your spam folder or resend.
              </p>
            </CardContent>
            <CardFooter>
              <button
                type="button"
                className="w-full text-center text-sm text-muted-foreground underline-offset-4 hover:underline"
                onClick={() => {
                  setPendingEmail(null)
                  setMode("login")
                  setError(null)
                  setInfo(null)
                }}
              >
                Back to sign in
              </button>
            </CardFooter>
          </Card>
        ) : (
          <Card className="w-full max-w-sm">
            <CardHeader>
              <CardTitle className="font-display text-xl">
                {mode === "login" ? "Sign in" : "Create an account"}
              </CardTitle>
              <CardDescription>
                {mode === "login"
                  ? "Sign in to investigate incidents and review logs."
                  : "Set up access to the log monitoring platform."}
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <Button
                type="button"
                variant="outline"
                className="w-full"
                onClick={handleGoogle}
                disabled={googleSubmitting || submitting}
              >
                <GoogleIcon />
                {googleSubmitting ? "Redirecting..." : "Continue with Google"}
              </Button>

              <div className="flex items-center gap-3">
                <div className="h-px flex-1 bg-border" />
                <span className="text-xs text-muted-foreground uppercase">or</span>
                <div className="h-px flex-1 bg-border" />
              </div>

              <form onSubmit={handleSubmit} className="flex flex-col gap-4">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="email">Email</Label>
                  <Input
                    id="email"
                    type="email"
                    placeholder="you@example.com"
                    autoComplete="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="password">Password</Label>
                  <Input
                    id="password"
                    type="password"
                    placeholder="••••••••"
                    autoComplete={mode === "login" ? "current-password" : "new-password"}
                    minLength={6}
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                  />
                </div>
                {error && <p className="text-sm text-destructive">{error}</p>}
                {info && <p className="text-sm text-muted-foreground">{info}</p>}
                <Button type="submit" className="w-full" disabled={submitting || googleSubmitting}>
                  {submitting
                    ? "Please wait..."
                    : mode === "login"
                      ? "Sign in"
                      : "Sign up"}
                </Button>
              </form>
            </CardContent>
            <CardFooter>
              <button
                type="button"
                className="w-full text-center text-sm text-muted-foreground underline-offset-4 hover:underline"
                onClick={toggleMode}
              >
                {mode === "login"
                  ? "Don't have an account? Sign up"
                  : "Already have an account? Sign in"}
              </button>
            </CardFooter>
          </Card>
        )}
      </div>
    </div>
  )
}

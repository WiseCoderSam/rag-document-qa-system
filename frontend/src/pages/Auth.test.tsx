import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { AuthProvider } from "@/context/AuthContext"
import { Auth } from "@/pages/Auth"

const { signInWithPassword, signUp, getSession, onAuthStateChange } = vi.hoisted(() => ({
  signInWithPassword: vi.fn(),
  signUp: vi.fn(),
  getSession: vi.fn(),
  onAuthStateChange: vi.fn(),
}))

vi.mock("@/lib/supabase", () => ({
  supabase: {
    auth: {
      getSession,
      onAuthStateChange,
      signInWithPassword,
      signUp,
    },
  },
}))

function renderAuth() {
  return render(
    <AuthProvider>
      <Auth />
    </AuthProvider>
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  getSession.mockResolvedValue({ data: { session: null } })
  onAuthStateChange.mockReturnValue({ data: { subscription: { unsubscribe: vi.fn() } } })
})

describe("Auth", () => {
  it("submits sign-in credentials to Supabase", async () => {
    signInWithPassword.mockResolvedValue({ error: null })
    const user = userEvent.setup()
    renderAuth()

    await waitFor(() => expect(getSession).toHaveBeenCalled())

    await user.type(screen.getByLabelText("Email"), "analyst@example.com")
    await user.type(screen.getByLabelText("Password"), "hunter2pass")
    await user.click(screen.getByRole("button", { name: "Sign in" }))

    await waitFor(() =>
      expect(signInWithPassword).toHaveBeenCalledWith({
        email: "analyst@example.com",
        password: "hunter2pass",
      })
    )
    expect(signUp).not.toHaveBeenCalled()
  })

  it("shows the error message returned by Supabase on failed sign-in", async () => {
    signInWithPassword.mockResolvedValue({ error: { message: "Invalid login credentials" } })
    const user = userEvent.setup()
    renderAuth()
    await waitFor(() => expect(getSession).toHaveBeenCalled())

    await user.type(screen.getByLabelText("Email"), "analyst@example.com")
    await user.type(screen.getByLabelText("Password"), "wrongpass")
    await user.click(screen.getByRole("button", { name: "Sign in" }))

    expect(await screen.findByText("Invalid login credentials")).toBeInTheDocument()
  })

  it("switches to sign-up mode and calls signUp instead of signInWithPassword", async () => {
    signUp.mockResolvedValue({ error: null })
    const user = userEvent.setup()
    renderAuth()
    await waitFor(() => expect(getSession).toHaveBeenCalled())

    await user.click(screen.getByText("Don't have an account? Sign up"))
    expect(screen.getByRole("button", { name: "Sign up" })).toBeInTheDocument()

    await user.type(screen.getByLabelText("Email"), "newuser@example.com")
    await user.type(screen.getByLabelText("Password"), "brandnewpass")
    await user.click(screen.getByRole("button", { name: "Sign up" }))

    await waitFor(() =>
      expect(signUp).toHaveBeenCalledWith({
        email: "newuser@example.com",
        password: "brandnewpass",
      })
    )
    expect(signInWithPassword).not.toHaveBeenCalled()
    expect(await screen.findByText(/check your inbox/i)).toBeInTheDocument()
  })
})

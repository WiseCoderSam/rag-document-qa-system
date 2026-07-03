import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import type { Session } from "@supabase/supabase-js"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { InvestigationChat } from "@/components/InvestigationChat"
import * as api from "@/lib/api"

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>()
  return {
    ...actual,
    apiFetch: vi.fn(),
    getLogEntries: vi.fn(),
    getDocumentChunks: vi.fn(),
  }
})

const fakeSession = {} as Session

async function askQuestion(question: string) {
  const user = userEvent.setup()
  await user.type(screen.getByPlaceholderText("Ask about your logs…"), question)
  await user.click(screen.getByRole("button", { name: "Send" }))
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.getLogEntries).mockResolvedValue([])
  vi.mocked(api.getDocumentChunks).mockResolvedValue([])
})

describe("InvestigationChat citation resolution", () => {
  it("unscoped: sends no incident_id/file_id and resolves sources against BOTH log entries and document chunks", async () => {
    vi.mocked(api.apiFetch).mockResolvedValue({
      answer: "Mixed-source answer.",
      sources: [1, 2],
    } as api.ChatResponse)

    render(<InvestigationChat session={fakeSession} />)
    await askQuestion("What happened around 10pm?")

    await waitFor(() => expect(api.apiFetch).toHaveBeenCalled())
    const [, , init] = vi.mocked(api.apiFetch).mock.calls[0]
    const body = JSON.parse((init as RequestInit).body as string)
    expect(body).toEqual({ question: "What happened around 10pm?" })

    await waitFor(() => {
      expect(api.getLogEntries).toHaveBeenCalledWith([1, 2], fakeSession)
      expect(api.getDocumentChunks).toHaveBeenCalledWith([1, 2], fakeSession)
    })
  })

  it("scoped to an incident: sends incident_id and resolves sources via getLogEntries only", async () => {
    vi.mocked(api.apiFetch).mockResolvedValue({
      answer: "Incident-scoped answer.",
      sources: [5],
    } as api.ChatResponse)

    render(<InvestigationChat session={fakeSession} incidentId={42} />)
    await askQuestion("Summarize this incident.")

    await waitFor(() => expect(api.apiFetch).toHaveBeenCalled())
    const [, , init] = vi.mocked(api.apiFetch).mock.calls[0]
    const body = JSON.parse((init as RequestInit).body as string)
    expect(body).toEqual({ question: "Summarize this incident.", incident_id: 42 })

    await waitFor(() => expect(api.getLogEntries).toHaveBeenCalledWith([5], fakeSession))
    expect(api.getDocumentChunks).not.toHaveBeenCalled()
  })

  it("scoped to a document file: sends file_id and resolves sources via getDocumentChunks only", async () => {
    vi.mocked(api.apiFetch).mockResolvedValue({
      answer: "Document-scoped answer.",
      sources: [7],
    } as api.ChatResponse)
    vi.mocked(api.getDocumentChunks).mockResolvedValue([
      { id: 7, document_id: 3, chunk_index: 0, text: "relevant document excerpt" },
    ])

    render(<InvestigationChat session={fakeSession} fileId={3} />)
    await askQuestion("What does this document say?")

    await waitFor(() => expect(api.apiFetch).toHaveBeenCalled())
    const [, , init] = vi.mocked(api.apiFetch).mock.calls[0]
    const body = JSON.parse((init as RequestInit).body as string)
    expect(body).toEqual({ question: "What does this document say?", file_id: 3 })

    await waitFor(() => expect(api.getDocumentChunks).toHaveBeenCalledWith([7], fakeSession))
    expect(api.getLogEntries).not.toHaveBeenCalled()
    expect(await screen.findByText("[1] Log Entry #7")).toBeInTheDocument()
  })

  it("shows the no-match notice without resolving any citations when sources is empty", async () => {
    vi.mocked(api.apiFetch).mockResolvedValue({
      answer: api.NO_MATCH_ANSWER,
      sources: [],
    } as api.ChatResponse)

    render(<InvestigationChat session={fakeSession} />)
    await askQuestion("Anything about zebras?")

    expect(await screen.findByText(api.NO_MATCH_ANSWER)).toBeInTheDocument()
    expect(api.getLogEntries).not.toHaveBeenCalled()
    expect(api.getDocumentChunks).not.toHaveBeenCalled()
  })
})

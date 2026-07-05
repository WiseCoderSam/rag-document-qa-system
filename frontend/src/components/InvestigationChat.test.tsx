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
    getDocumentChunks: vi.fn(),
  }
})

const fakeSession = {} as Session

async function askQuestion(question: string) {
  const user = userEvent.setup()
  await user.type(screen.getByPlaceholderText("Ask about your documents…"), question)
  await user.click(screen.getByRole("button", { name: "Send" }))
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.getDocumentChunks).mockResolvedValue([])
})

describe("InvestigationChat", () => {
  it("unscoped: sends no document_id and resolves sources via getDocumentChunks", async () => {
    vi.mocked(api.apiFetch).mockResolvedValue({
      answer: "An answer.",
      sources: [1, 2],
    } as api.ChatResponse)

    render(<InvestigationChat session={fakeSession} />)
    await askQuestion("What is this document about?")

    await waitFor(() => expect(api.apiFetch).toHaveBeenCalled())
    const [, , init] = vi.mocked(api.apiFetch).mock.calls[0]
    const body = JSON.parse((init as RequestInit).body as string)
    expect(body).toEqual({ question: "What is this document about?" })

    await waitFor(() => expect(api.getDocumentChunks).toHaveBeenCalledWith([1, 2], fakeSession))
  })

  it("scoped to a document: sends document_id and shows the document name in the header", async () => {
    vi.mocked(api.apiFetch).mockResolvedValue({
      answer: "Scoped answer.",
      sources: [7],
    } as api.ChatResponse)
    vi.mocked(api.getDocumentChunks).mockResolvedValue([
      { id: 7, document_id: 3, chunk_index: 0, text: "relevant document excerpt" },
    ])

    render(<InvestigationChat session={fakeSession} documentId={3} documentName="report.pdf" />)
    expect(screen.getByText(/report\.pdf/)).toBeInTheDocument()

    await askQuestion("Summarize this document.")

    await waitFor(() => expect(api.apiFetch).toHaveBeenCalled())
    const [, , init] = vi.mocked(api.apiFetch).mock.calls[0]
    const body = JSON.parse((init as RequestInit).body as string)
    expect(body).toEqual({ question: "Summarize this document.", document_id: 3 })

    await waitFor(() => expect(api.getDocumentChunks).toHaveBeenCalledWith([7], fakeSession))
    expect(await screen.findByText("Source [1]")).toBeInTheDocument()
  })

  it("renders the no-match answer as a notice without citation badges", async () => {
    vi.mocked(api.apiFetch).mockResolvedValue({
      answer: api.NO_MATCH_ANSWER,
      sources: [],
    } as api.ChatResponse)

    render(<InvestigationChat session={fakeSession} />)
    await askQuestion("Anything in there?")

    expect(await screen.findByText(api.NO_MATCH_ANSWER)).toBeInTheDocument()
    expect(api.getDocumentChunks).not.toHaveBeenCalled()
    expect(screen.queryByText(/^Source \[/)).not.toBeInTheDocument()
  })

  it("shows the error message when the chat request fails", async () => {
    vi.mocked(api.apiFetch).mockRejectedValue(new Error("Rate limit exceeded"))

    render(<InvestigationChat session={fakeSession} />)
    await askQuestion("Will this fail?")

    expect(await screen.findByText("Rate limit exceeded")).toBeInTheDocument()
  })
})

import { afterEach, describe, expect, it, vi } from "vitest"
import type { Session } from "@supabase/supabase-js"

import { apiFetch, ApiError, getDocumentChunks } from "@/lib/api"

const fakeSession = { access_token: "test-token" } as Session

describe("apiFetch", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("attaches the bearer token and decodes a successful JSON response", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ hello: "world" }),
    })
    vi.stubGlobal("fetch", fetchMock)

    const result = await apiFetch<{ hello: string }>("/api/v1/thing", fakeSession)

    expect(result).toEqual({ hello: "world" })
    const [, init] = fetchMock.mock.calls[0]
    expect(init.headers.Authorization).toBe("Bearer test-token")
  })

  it("throws an ApiError carrying the status code on a non-2xx response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({}) })
    )

    await expect(apiFetch("/api/v1/missing", fakeSession)).rejects.toMatchObject({
      name: "ApiError",
      status: 404,
    })
    await expect(apiFetch("/api/v1/missing", fakeSession)).rejects.toBeInstanceOf(ApiError)
  })
})

describe("citation-id resolution helpers", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("getDocumentChunks skips the network call entirely for an empty id list", async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal("fetch", fetchMock)

    const result = await getDocumentChunks([], fakeSession)

    expect(result).toEqual([])
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("getDocumentChunks requests a comma-separated ids query param", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => [] })
    vi.stubGlobal("fetch", fetchMock)

    await getDocumentChunks([3, 1, 2], fakeSession)

    const [url] = fetchMock.mock.calls[0]
    expect(url).toContain("/api/v1/documents/chunks?ids=3,1,2")
  })
})

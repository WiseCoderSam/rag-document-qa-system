import { afterEach, describe, expect, it, vi } from "vitest"

import { exportToCSV } from "@/lib/export"

/**
 * exportToCSV builds the CSV client-side and triggers a Blob download rather
 * than returning a string, so these tests intercept the Blob passed to
 * URL.createObjectURL and read its text back out to assert on the actual
 * CSV content.
 */
function captureCsvBlob(data: Record<string, unknown>[]): Blob {
  let capturedBlob: Blob | null = null
  vi.stubGlobal("URL", {
    createObjectURL: (blob: Blob) => {
      capturedBlob = blob
      return "blob:mock-url"
    },
    revokeObjectURL: vi.fn(),
  })

  exportToCSV(data, "test.csv")

  expect(capturedBlob).not.toBeNull()
  return capturedBlob!
}

// Blob.text() decodes as UTF-8 and, per the TextDecoder spec, strips a
// leading BOM on the way back to a JS string — so it's the right way to
// assert on ordinary cell content, but the BOM-presence test below reads
// raw bytes instead, since that's what Excel actually looks at.
async function captureCsv(data: Record<string, unknown>[]): Promise<string> {
  return await captureCsvBlob(data).text()
}

describe("exportToCSV", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("prefixes a leading '=' with a quote to defuse spreadsheet formula injection", async () => {
    const csv = await captureCsv([{ message: "=cmd|'/c calc'!A1" }])
    expect(csv).toContain("'=cmd|'/c calc'!A1")
  })

  it("also defuses leading +, -, and @ (all spreadsheet formula triggers)", async () => {
    const csv = await captureCsv([
      { a: "+1+1", b: "-1+1", c: "@SUM(1,1)" },
    ])
    const dataLine = csv.split("\r\n")[1]
    expect(dataLine).toContain("'+1+1")
    expect(dataLine).toContain("'-1+1")
    expect(dataLine).toContain("'@SUM(1,1)")
  })

  it("does not alter ordinary values", async () => {
    const csv = await captureCsv([{ message: "user logged in" }])
    expect(csv).toContain("user logged in")
    expect(csv).not.toContain("'user logged in")
  })

  it("quotes values containing commas or quotes per CSV rules", async () => {
    const csv = await captureCsv([{ message: 'value, with "quotes"' }])
    expect(csv).toContain('"value, with ""quotes"""')
  })

  it("writes a UTF-8 BOM (EF BB BF) as the first three bytes so Excel doesn't garble non-ASCII text", async () => {
    const blob = captureCsvBlob([{ message: "café" }])
    const bytes = new Uint8Array(await blob.arrayBuffer())
    expect([...bytes.slice(0, 3)]).toEqual([0xef, 0xbb, 0xbf])
  })
})

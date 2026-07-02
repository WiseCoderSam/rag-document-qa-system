/**
 * CSV/PDF report export, deliberately with no new dependencies:
 *   - CSV: build a string, trigger a download via a Blob URL.
 *   - PDF: open a new window, write a print-styled report, let the browser's
 *     native "Print > Save as PDF" do the actual PDF generation.
 */

// ---------------------------------------------------------------------------
// CSV export
// ---------------------------------------------------------------------------

/**
 * Guards against CSV formula injection: Excel/Sheets treats a cell starting
 * with =, +, -, or @ as a formula when the file is opened, which lets a
 * value that originated from untrusted data (e.g. a log message or incident
 * description) execute arbitrary formulas/macros on whoever opens the
 * export. Prefixing with a leading `'` forces spreadsheet apps to treat it
 * as literal text instead.
 */
function sanitizeFormulaInjection(value: string): string {
  return /^[=+\-@]/.test(value) ? `'${value}` : value
}

function csvQuoteIfNeeded(value: string): string {
  return /[",\r\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value
}

function formatCsvCell(raw: unknown): string {
  const str = raw === null || raw === undefined ? "" : String(raw)
  return csvQuoteIfNeeded(sanitizeFormulaInjection(str))
}

function triggerBlobDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

export function exportToCSV(data: Record<string, unknown>[], filename: string): void {
  const headers = data.length > 0 ? Object.keys(data[0]) : []

  const lines = [
    headers.map(formatCsvCell).join(","),
    ...data.map((row) => headers.map((key) => formatCsvCell(row[key])).join(",")),
  ]

  // Leading BOM (U+FEFF) so Excel recognizes the file as UTF-8 instead of
  // garbling non-ASCII characters (e.g. accented usernames, non-Latin
  // hostnames). Written via fromCharCode rather than a literal escape to
  // keep the source free of invisible characters.
  const BOM = String.fromCharCode(0xfeff)
  const csvContent = BOM + lines.join("\r\n")

  const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" })
  triggerBlobDownload(blob, filename)
}

// ---------------------------------------------------------------------------
// PDF export (print-to-PDF)
// ---------------------------------------------------------------------------

/**
 * Escapes the handful of caller-supplied strings that get interpolated
 * directly into the report's static HTML shell (currently just
 * *reportTitle*, used in <title>). Every actual data cell below is instead
 * assigned via `textContent`, which is inherently safe regardless of
 * content — this escape function exists only for the shell interpolation,
 * not as the primary defense.
 */
function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;")
}

export function exportToPDF(reportTitle: string, data: Record<string, unknown>[]): void {
  const reportWindow = window.open("", "_blank")
  if (!reportWindow) {
    window.alert("Please allow pop-ups for this site to export a PDF report.")
    return
  }

  // Prevent reverse tabnabbing (security hardening)
  reportWindow.opener = null

  const doc = reportWindow.document
  const headers = data.length > 0 ? Object.keys(data[0]) : []

  // Static shell only — no data values are concatenated into this string.
  // reportTitle is the one caller-supplied string interpolated here, so it
  // goes through escapeHtml(); every log/incident value below is assigned
  // via textContent instead (see the loop further down), which never
  // interprets its input as markup — e.g. a literal <script> tag quoted
  // from an attacker's log payload (rules.py's XSS signature detection)
  // renders as plain visible text, not executable HTML.
  doc.open()
  doc.write(`<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<title>${escapeHtml(reportTitle)}</title>
<style>
  body { font-family: system-ui, sans-serif; color: #111; padding: 24px; }
  h1 { font-size: 1.25rem; margin: 0 0 0.25rem; }
  .report-date { color: #555; font-size: 0.875rem; margin: 0 0 1.5rem; }
  table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
  th, td { border: 1px solid #ccc; padding: 6px 8px; text-align: left; vertical-align: top; word-break: break-word; }
  th { background: #f2f2f2; }
  .print-actions { margin-bottom: 1.5rem; }
  .print-actions button { font-size: 0.875rem; padding: 6px 12px; cursor: pointer; }
  .empty-state { color: #555; }
  @media print {
    .print-actions { display: none; }
  }
</style>
</head>
<body>
  <div class="print-actions">
    <button type="button" id="print-btn">Print / Save as PDF</button>
  </div>
  <h1></h1>
  <p class="report-date"></p>
  <div id="report-body"></div>
</body>
</html>`)
  doc.close()

  const titleEl = doc.querySelector("h1")
  if (titleEl) titleEl.textContent = reportTitle

  const dateEl = doc.querySelector(".report-date")
  if (dateEl) dateEl.textContent = `Generated ${new Date().toLocaleString()}`

  const reportBody = doc.getElementById("report-body")
  if (reportBody) {
    if (data.length === 0) {
      const emptyState = doc.createElement("p")
      emptyState.className = "empty-state"
      emptyState.textContent = "No data to export."
      reportBody.appendChild(emptyState)
    } else {
      const table = doc.createElement("table")

      const thead = doc.createElement("thead")
      const headerRow = doc.createElement("tr")
      for (const header of headers) {
        const th = doc.createElement("th")
        th.textContent = header
        headerRow.appendChild(th)
      }
      thead.appendChild(headerRow)
      table.appendChild(thead)

      const tbody = doc.createElement("tbody")
      for (const row of data) {
        const tr = doc.createElement("tr")
        for (const header of headers) {
          const td = doc.createElement("td")
          const value = row[header]
          // textContent, not innerHTML — see the top-of-function note.
          td.textContent = value === null || value === undefined ? "" : String(value)
          tr.appendChild(td)
        }
        tbody.appendChild(tr)
      }
      table.appendChild(tbody)

      reportBody.appendChild(table)
    }
  }

  doc.getElementById("print-btn")?.addEventListener("click", () => reportWindow.print())
}

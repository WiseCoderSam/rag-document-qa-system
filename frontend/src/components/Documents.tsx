import { useEffect, useRef, useState } from "react"
import type { Session } from "@supabase/supabase-js"
import { Loader2 } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { apiFetch, type DocumentOut } from "@/lib/api"

interface DocumentsProps {
  session: Session
  onChatWithDocument: (documentId: number) => void
}

function statusBadgeClass(status: string): string {
  if (status === "completed") return "bg-ok/15 text-ok"
  if (status === "failed") return "bg-destructive/15 text-destructive"
  return "bg-muted text-muted-foreground"
}

export function Documents({ session, onChatWithDocument }: DocumentsProps) {
  const [documents, setDocuments] = useState<DocumentOut[]>([])
  const [loadingList, setLoadingList] = useState(true)
  const [listError, setListError] = useState<string | null>(null)

  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    apiFetch<DocumentOut[]>("/api/v1/documents", session)
      .then(setDocuments)
      .catch((err: Error) => setListError(err.message))
      .finally(() => setLoadingList(false))
  }, [session])

  const handleUpload = async () => {
    if (!selectedFile || uploading) return
    setUploading(true)
    setUploadError(null)
    try {
      const formData = new FormData()
      formData.append("file", selectedFile)
      // No Content-Type header here — the browser sets the multipart
      // boundary automatically when body is a FormData instance.
      const doc = await apiFetch<DocumentOut>("/api/v1/documents/upload", session, {
        method: "POST",
        body: formData,
      })
      setDocuments((prev) => [doc, ...prev])
      setSelectedFile(null)
      if (fileInputRef.current) fileInputRef.current.value = ""
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Upload failed.")
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle>Upload a Document</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap items-center gap-3">
            <Label className="cursor-pointer rounded-lg border border-border bg-background px-2.5 py-1.5 hover:bg-muted">
              Choose File
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,.txt"
                className="hidden"
                onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
              />
            </Label>
            <span className="text-sm text-muted-foreground">
              {selectedFile ? selectedFile.name : "No file selected."}
            </span>
            <Button type="button" onClick={() => void handleUpload()} disabled={uploading || !selectedFile}>
              {uploading && <Loader2 className="size-4 animate-spin" />}
              Upload
            </Button>
          </div>
          {uploadError && <p className="mt-2 text-sm text-destructive">{uploadError}</p>}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Your Documents</CardTitle>
        </CardHeader>
        <CardContent>
          {loadingList ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
              <Loader2 className="size-4 animate-spin" />
              Loading…
            </div>
          ) : listError ? (
            <p className="text-sm text-destructive">Failed to load documents: {listError}</p>
          ) : documents.length === 0 ? (
            <p className="text-sm text-muted-foreground">No documents uploaded yet.</p>
          ) : (
            <ul className="flex flex-col gap-3">
              {documents.map((doc) => (
                <li
                  key={doc.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border p-3"
                >
                  <div className="flex flex-col gap-1">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-sm font-medium">{doc.filename}</span>
                      <Badge className={statusBadgeClass(doc.status) + " font-mono"}>{doc.status}</Badge>
                    </div>
                    <div className="font-mono text-xs text-muted-foreground">
                      {doc.page_count !== null && <span>{doc.page_count} pages · </span>}
                      {new Date(doc.uploaded_at).toLocaleString()}
                    </div>
                  </div>
                  {doc.status === "completed" && (
                    <Button type="button" variant="outline" size="sm" onClick={() => onChatWithDocument(doc.id)}>
                      Chat with this document
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

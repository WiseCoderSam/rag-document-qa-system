import { useEffect, useRef, useState } from "react"
import type { Session } from "@supabase/supabase-js"
import { Loader2 } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { toast } from "@/components/ui/toast"
import { apiFetch, deleteDocument, retryDocument, type DocumentOut } from "@/lib/api"

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

  // Tracks which row currently has a delete/retry request in flight, so only
  // that row's buttons disable rather than the whole list.
  const [pendingId, setPendingId] = useState<number | null>(null)

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
      toast.add({ title: "Upload started", description: `${doc.filename} is processing.`, type: "success" })
    } catch (err) {
      const message = err instanceof Error ? err.message : "Upload failed."
      setUploadError(message)
      toast.add({ title: "Upload failed", description: message, type: "error" })
    } finally {
      setUploading(false)
    }
  }

  const handleDelete = async (document: DocumentOut) => {
    if (pendingId !== null) return
    setPendingId(document.id)
    try {
      await deleteDocument(document.id, session)
      setDocuments((prev) => prev.filter((d) => d.id !== document.id))
      toast.add({ title: "Deleted", description: `${document.filename} was removed.`, type: "success" })
    } catch (err) {
      toast.add({
        title: "Delete failed",
        description: err instanceof Error ? err.message : "Could not delete this document.",
        type: "error",
      })
    } finally {
      setPendingId(null)
    }
  }

  const handleRetry = async (document: DocumentOut) => {
    if (pendingId !== null) return
    setPendingId(document.id)
    try {
      const updated = await retryDocument(document.id, session)
      setDocuments((prev) => prev.map((d) => (d.id === updated.id ? updated : d)))
      toast.add({ title: "Retrying", description: `${document.filename} is processing again.`, type: "success" })
    } catch (err) {
      toast.add({
        title: "Retry failed",
        description: err instanceof Error ? err.message : "Could not retry this document.",
        type: "error",
      })
    } finally {
      setPendingId(null)
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
                  <div className="flex gap-2">
                    {doc.status === "completed" && (
                      <Button type="button" variant="outline" size="sm" onClick={() => onChatWithDocument(doc.id)}>
                        Chat with this document
                      </Button>
                    )}
                    {doc.status === "failed" && (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        disabled={pendingId === doc.id}
                        onClick={() => void handleRetry(doc)}
                      >
                        {pendingId === doc.id && <Loader2 className="size-3.5 animate-spin" />}
                        Retry
                      </Button>
                    )}
                    <Button
                      type="button"
                      variant="destructive"
                      size="sm"
                      disabled={pendingId === doc.id}
                      onClick={() => void handleDelete(doc)}
                    >
                      Delete
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

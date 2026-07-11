import type { Session } from "@supabase/supabase-js"
import { Loader2 } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { deleteDocument, retryDocument, type DocumentOut } from "@/lib/api"
import { statusBadgeClass, useUploadList } from "@/lib/useUploadList"

interface DocumentsProps {
  session: Session
  onChatWithDocument: (documentId: number) => void
}

export function Documents({ session, onChatWithDocument }: DocumentsProps) {
  const {
    items: documents,
    loadingList,
    listError,
    selectedFile,
    setSelectedFile,
    uploading,
    uploadError,
    fileInputRef,
    pendingId,
    handleUpload,
    handleDelete,
    handleRetry,
  } = useUploadList<DocumentOut>({
    session,
    listPath: "/api/v1/documents",
    uploadPath: "/api/v1/documents/upload",
    deleteFn: deleteDocument,
    retryFn: retryDocument,
    noun: "document",
  })

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

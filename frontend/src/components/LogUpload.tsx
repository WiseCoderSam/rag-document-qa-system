import type { Session } from "@supabase/supabase-js"
import { Loader2 } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { deleteLogFile, retryLogFile, type LogFileOut } from "@/lib/api"
import { statusBadgeClass, useUploadList } from "@/lib/useUploadList"

interface LogUploadProps {
  session: Session
}

export function LogUpload({ session }: LogUploadProps) {
  const {
    items: logFiles,
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
  } = useUploadList<LogFileOut>({
    session,
    listPath: "/api/v1/logs",
    uploadPath: "/api/v1/logs/upload",
    deleteFn: deleteLogFile,
    retryFn: retryLogFile,
    noun: "file",
  })

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle>Upload a Log File</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap items-center gap-3">
            <Label className="cursor-pointer rounded-lg border border-border bg-background px-2.5 py-1.5 hover:bg-muted">
              Choose File
              <input
                ref={fileInputRef}
                type="file"
                accept=".log,.txt"
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
          <CardTitle>Your Log Files</CardTitle>
        </CardHeader>
        <CardContent>
          {loadingList ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
              <Loader2 className="size-4 animate-spin" />
              Loading…
            </div>
          ) : listError ? (
            <p className="text-sm text-destructive">Failed to load log files: {listError}</p>
          ) : logFiles.length === 0 ? (
            <p className="text-sm text-muted-foreground">No log files uploaded yet.</p>
          ) : (
            <ul className="flex flex-col gap-3">
              {logFiles.map((logFile) => (
                <li
                  key={logFile.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border p-3"
                >
                  <div className="flex flex-col gap-1">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-sm font-medium">{logFile.filename}</span>
                      <Badge className={statusBadgeClass(logFile.status) + " font-mono"}>{logFile.status}</Badge>
                    </div>
                    <div className="font-mono text-xs text-muted-foreground">
                      {new Date(logFile.uploaded_at).toLocaleString()}
                    </div>
                  </div>
                  <div className="flex gap-2">
                    {logFile.status === "failed" && (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        disabled={pendingId === logFile.id}
                        onClick={() => void handleRetry(logFile)}
                      >
                        {pendingId === logFile.id && <Loader2 className="size-3.5 animate-spin" />}
                        Retry
                      </Button>
                    )}
                    <Button
                      type="button"
                      variant="destructive"
                      size="sm"
                      disabled={pendingId === logFile.id}
                      onClick={() => void handleDelete(logFile)}
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

import { useEffect, useRef, useState } from "react"
import type { Session } from "@supabase/supabase-js"
import { Loader2 } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { apiFetch, type LogFileOut } from "@/lib/api"

interface LogUploadProps {
  session: Session
}

function statusBadgeClass(status: string): string {
  if (status === "completed") return "bg-green-500/15 text-green-700 dark:text-green-400"
  if (status === "failed") return "bg-destructive/10 text-destructive"
  return "bg-muted text-muted-foreground"
}

export function LogUpload({ session }: LogUploadProps) {
  const [logFiles, setLogFiles] = useState<LogFileOut[]>([])
  const [loadingList, setLoadingList] = useState(true)
  const [listError, setListError] = useState<string | null>(null)

  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    apiFetch<LogFileOut[]>("/api/v1/logs", session)
      .then(setLogFiles)
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
      const logFile = await apiFetch<LogFileOut>("/api/v1/logs/upload", session, {
        method: "POST",
        body: formData,
      })
      setLogFiles((prev) => [logFile, ...prev])
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
                      <span className="font-bold">{logFile.filename}</span>
                      <Badge className={statusBadgeClass(logFile.status)}>{logFile.status}</Badge>
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {new Date(logFile.uploaded_at).toLocaleString()}
                    </div>
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

import { useEffect, useRef, useState } from "react"
import type { Session } from "@supabase/supabase-js"

import { toast } from "@/components/ui/toast"
import { apiFetch } from "@/lib/api"

/** Shared status → badge classes for the upload lists (logs & documents). */
export function statusBadgeClass(status: string): string {
  if (status === "completed") return "bg-ok/15 text-ok"
  if (status === "failed") return "bg-destructive/15 text-destructive"
  return "bg-muted text-muted-foreground"
}

interface UploadListItem {
  id: number
  filename: string
  status: string
}

interface UploadListConfig<T extends UploadListItem> {
  session: Session
  /** GET path returning the current list, most-recent first. */
  listPath: string
  /** POST path accepting a multipart "file" field. */
  uploadPath: string
  deleteFn: (id: number, session: Session) => Promise<void>
  retryFn: (id: number, session: Session) => Promise<T>
  /** Noun used in delete/retry failure toasts, e.g. "file" or "document". */
  noun: string
}

/**
 * The upload-form + list + delete/retry state machine shared verbatim by
 * LogUpload and Documents — the two only differ in their endpoints, accepted
 * file types, and per-row rendering, which stay in the components. `pendingId`
 * tracks the single row with a delete/retry in flight so only its buttons
 * disable, not the whole list.
 */
export function useUploadList<T extends UploadListItem>({
  session,
  listPath,
  uploadPath,
  deleteFn,
  retryFn,
  noun,
}: UploadListConfig<T>) {
  const [items, setItems] = useState<T[]>([])
  const [loadingList, setLoadingList] = useState(true)
  const [listError, setListError] = useState<string | null>(null)

  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [pendingId, setPendingId] = useState<number | null>(null)

  useEffect(() => {
    apiFetch<T[]>(listPath, session)
      .then(setItems)
      .catch((err: Error) => setListError(err.message))
      .finally(() => setLoadingList(false))
  }, [session, listPath])

  const handleUpload = async () => {
    if (!selectedFile || uploading) return
    setUploading(true)
    setUploadError(null)
    try {
      const formData = new FormData()
      formData.append("file", selectedFile)
      // No Content-Type header here — the browser sets the multipart
      // boundary automatically when body is a FormData instance.
      const item = await apiFetch<T>(uploadPath, session, { method: "POST", body: formData })
      setItems((prev) => [item, ...prev])
      setSelectedFile(null)
      if (fileInputRef.current) fileInputRef.current.value = ""
      toast.add({ title: "Upload started", description: `${item.filename} is processing.`, type: "success" })
    } catch (err) {
      const message = err instanceof Error ? err.message : "Upload failed."
      setUploadError(message)
      toast.add({ title: "Upload failed", description: message, type: "error" })
    } finally {
      setUploading(false)
    }
  }

  const handleDelete = async (item: T) => {
    if (pendingId !== null) return
    setPendingId(item.id)
    try {
      await deleteFn(item.id, session)
      setItems((prev) => prev.filter((i) => i.id !== item.id))
      toast.add({ title: "Deleted", description: `${item.filename} was removed.`, type: "success" })
    } catch (err) {
      toast.add({
        title: "Delete failed",
        description: err instanceof Error ? err.message : `Could not delete this ${noun}.`,
        type: "error",
      })
    } finally {
      setPendingId(null)
    }
  }

  const handleRetry = async (item: T) => {
    if (pendingId !== null) return
    setPendingId(item.id)
    try {
      const updated = await retryFn(item.id, session)
      setItems((prev) => prev.map((i) => (i.id === updated.id ? updated : i)))
      toast.add({ title: "Retrying", description: `${item.filename} is processing again.`, type: "success" })
    } catch (err) {
      toast.add({
        title: "Retry failed",
        description: err instanceof Error ? err.message : `Could not retry this ${noun}.`,
        type: "error",
      })
    } finally {
      setPendingId(null)
    }
  }

  return {
    items,
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
  }
}

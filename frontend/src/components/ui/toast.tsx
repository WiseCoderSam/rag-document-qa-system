import { Toast as ToastPrimitive } from "@base-ui/react/toast"
import { XIcon } from "lucide-react"

import { cn } from "@/lib/utils"

/**
 * Module-level toast manager (base-ui's escape hatch for firing toasts
 * outside a React component/hook) — this is what LogUpload/Documents/etc.
 * call directly (`toast.add(...)`) instead of needing useToastManager() and
 * prop-drilling a toast function through every component that wants to
 * report success/failure.
 */
export const toast = ToastPrimitive.createToastManager()

const TOAST_TYPE_CLASS: Record<string, string> = {
  success: "border-ok/30",
  error: "border-destructive/40",
}

function ToastList() {
  const { toasts } = ToastPrimitive.useToastManager()

  return toasts.map((t) => (
    <ToastPrimitive.Root
      key={t.id}
      toast={t}
      className={cn(
        // bottom-0 (not top-0): the viewport is anchored at the page's
        // bottom edge with zero height, so toasts must extend upward from
        // it — top-0 would render them below the visible page.
        "absolute right-0 bottom-0 z-50 w-full rounded-lg border border-border bg-popover bg-clip-padding p-3 text-popover-foreground shadow-lg transition-all duration-200",
        "data-[starting-style]:translate-y-2 data-[starting-style]:opacity-0",
        "data-[ending-style]:opacity-0",
        "data-[expanded]:translate-y-[calc(var(--toast-offset-y)*-1)]",
        "data-[expanded=false]:translate-y-[calc(var(--toast-index)*10px)] data-[expanded=false]:scale-[calc(1-var(--toast-index)*0.05)]",
        t.type ? TOAST_TYPE_CLASS[t.type] : undefined
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-col gap-0.5">
          {t.title && <ToastPrimitive.Title className="text-sm font-medium">{t.title}</ToastPrimitive.Title>}
          {t.description && (
            <ToastPrimitive.Description className="text-sm text-muted-foreground">
              {t.description}
            </ToastPrimitive.Description>
          )}
        </div>
        <ToastPrimitive.Close
          className="shrink-0 rounded-md p-1 text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50"
          aria-label="Dismiss"
        >
          <XIcon className="size-3.5" />
        </ToastPrimitive.Close>
      </div>
    </ToastPrimitive.Root>
  ))
}

/** Mount once near the app root — provides the toast context and renders whatever `toast.add(...)` queues up. */
export function Toaster() {
  return (
    <ToastPrimitive.Provider toastManager={toast}>
      <ToastPrimitive.Portal>
        <ToastPrimitive.Viewport className="fixed right-4 bottom-4 z-50 mx-auto flex w-full max-w-sm flex-col-reverse">
          <ToastList />
        </ToastPrimitive.Viewport>
      </ToastPrimitive.Portal>
    </ToastPrimitive.Provider>
  )
}

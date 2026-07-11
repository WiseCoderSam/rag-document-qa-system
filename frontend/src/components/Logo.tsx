/**
 * QueryHub brand mark. A scanning "query ring" with a central hub node,
 * closed into a Q by a tail rendered as the app's signature severity
 * spectrum (low → critical). Reads equally as a threat-targeting reticle:
 * Query + Hub + severity, in one mark. Colors come from the theme tokens so
 * it tracks light/dark automatically.
 */
export function LogoMark({ className }: { className?: string }) {
  // Colors are set via inline `style` (not presentation attributes) so the
  // CSS custom properties reliably resolve in every browser.
  return (
    <svg viewBox="0 0 32 32" fill="none" aria-hidden="true" className={className}>
      <defs>
        <linearGradient id="qh-severity" x1="17" y1="17.5" x2="26.5" y2="27" gradientUnits="userSpaceOnUse">
          <stop offset="0" style={{ stopColor: "var(--sev-low)" }} />
          <stop offset="0.4" style={{ stopColor: "var(--sev-medium)" }} />
          <stop offset="0.72" style={{ stopColor: "var(--sev-high)" }} />
          <stop offset="1" style={{ stopColor: "var(--sev-critical)" }} />
        </linearGradient>
      </defs>
      {/* query ring / scanning lens */}
      <circle cx="14" cy="14.5" r="9" strokeWidth="2.75" style={{ stroke: "var(--primary)" }} />
      {/* hub node */}
      <circle cx="14" cy="14.5" r="2.4" style={{ fill: "var(--primary)" }} />
      {/* Q tail == severity spectrum */}
      <path d="M19.4 20 L26 26.6" stroke="url(#qh-severity)" strokeWidth="3.25" strokeLinecap="round" />
    </svg>
  )
}

/**
 * Full lockup: mark + "QueryHub" wordmark. Pass markClassName to size the
 * mark (the wordmark scales alongside via the parent font size).
 */
export function Logo({
  className,
  markClassName = "size-7",
}: {
  className?: string
  markClassName?: string
}) {
  return (
    <span className={"inline-flex items-center gap-2 " + (className ?? "")}>
      <LogoMark className={markClassName} />
      <span className="font-display text-lg leading-none font-semibold tracking-tight">
        Query<span className="text-primary">Hub</span>
      </span>
    </span>
  )
}

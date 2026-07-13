import { useEffect, useRef, useState } from "react"

import { Logo } from "@/components/Logo"

// Boot-log steps, revealed by real elapsed seconds. Timings are spread to
// match a real cold start (~30-50s); the last line simply keeps its cursor
// until the backend answers and the parent unmounts this screen.
const STEPS: { at: number; text: string; ok?: boolean }[] = [
  { at: 0.5, text: "contacting log-threat-detection-api" },
  { at: 3, text: "instance cold — provisioning container" },
  { at: 8, text: "mounting FAISS vector index" },
  { at: 14, text: "loading detection rules · 5 active" },
  { at: 21, text: "connecting datastore", ok: true },
  { at: 30, text: "warming inference engine" },
  { at: 41, text: "finalizing — almost online" },
]

const fmt = (s: number) =>
  `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`

// --- snake colours ---
const HEAD: [number, number, number] = [255, 219, 146]
const TAIL: [number, number, number] = [197, 106, 42]

/**
 * Full-screen loader shown while the backend cold-starts. An amber snake
 * slithers around the screen perimeter over a boot-log stream. `online`
 * flips the border to a green flash just before the parent swaps in the app.
 */
export function WakeScreen({ online = false }: { online?: boolean }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const onlineRef = useRef(online)
  onlineRef.current = online
  const [elapsed, setElapsed] = useState(0)

  // Boot-log + count-up timer (light 250ms tick, independent of the canvas).
  useEffect(() => {
    const start = performance.now()
    const id = setInterval(() => setElapsed((performance.now() - start) / 1000), 250)
    return () => clearInterval(id)
  }, [])

  // Canvas snake animation.
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext("2d")
    if (!ctx) return
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches

    // Perimeter path over a rounded rect inset from the viewport.
    let path: { total: number; point: (d: number) => [number, number] }
    const build = () => {
      const dpr = Math.min(devicePixelRatio || 1, 2)
      const W = innerWidth
      const H = innerHeight
      canvas.width = W * dpr
      canvas.height = H * dpr
      canvas.style.width = `${W}px`
      canvas.style.height = `${H}px`
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      const m = Math.max(18, Math.min(W, H) * 0.045)
      const r = Math.min(70, Math.min(W, H) * 0.09)
      const x = m
      const y = m
      const w = W - 2 * m
      const h = H - 2 * m
      const top = w - 2 * r
      const side = h - 2 * r
      const arc = (Math.PI / 2) * r
      const segs: { len: number; at: (t: number) => [number, number] }[] = [
        { len: top, at: (t) => [x + r + t, y] },
        { len: arc, at: (t) => { const a = -Math.PI / 2 + t / r; return [x + w - r + r * Math.cos(a), y + r + r * Math.sin(a)] } },
        { len: side, at: (t) => [x + w, y + r + t] },
        { len: arc, at: (t) => { const a = t / r; return [x + w - r + r * Math.cos(a), y + h - r + r * Math.sin(a)] } },
        { len: top, at: (t) => [x + w - r - t, y + h] },
        { len: arc, at: (t) => { const a = Math.PI / 2 + t / r; return [x + r + r * Math.cos(a), y + h - r + r * Math.sin(a)] } },
        { len: side, at: (t) => [x, y + h - r - t] },
        { len: arc, at: (t) => { const a = Math.PI + t / r; return [x + r + r * Math.cos(a), y + r + r * Math.sin(a)] } },
      ]
      const total = segs.reduce((s, g) => s + g.len, 0)
      path = {
        total,
        point(d) {
          let dd = ((d % total) + total) % total
          for (const g of segs) {
            if (dd <= g.len) return g.at(dd)
            dd -= g.len
          }
          return segs[0].at(0)
        },
      }
    }
    build()
    addEventListener("resize", build)

    const tangent = (d: number): [number, number] => {
      const [x1, y1] = path.point(d - 1.5)
      const [x2, y2] = path.point(d + 1.5)
      const dx = x2 - x1
      const dy = y2 - y1
      const L = Math.hypot(dx, dy) || 1
      return [dx / L, dy / L]
    }

    const SEG = 44
    const GAP = 6.5
    const SPEED = 330 // px/s travel
    const halfWidth = (f: number) => {
      const taper = f < 0.72 ? 1 : Math.max(0, 1 - (f - 0.72) / 0.28)
      return 4.6 * Math.pow(taper, 0.85)
    }

    const drawTrack = (color: string) => {
      ctx.lineWidth = 1
      ctx.strokeStyle = color
      ctx.beginPath()
      for (let d = 0; d <= path.total; d += 6) {
        const [px, py] = path.point(d)
        if (d === 0) ctx.moveTo(px, py)
        else ctx.lineTo(px, py)
      }
      ctx.closePath()
      ctx.stroke()
    }

    const drawSnake = (headD: number, time: number) => {
      ctx.clearRect(0, 0, innerWidth, innerHeight)
      drawTrack("rgba(120,130,155,.05)")

      // Spine points with a travelling slither wave (head steady, body wiggles).
      const pts: { x: number; y: number; nx: number; ny: number; f: number }[] = []
      for (let i = 0; i < SEG; i++) {
        const d = headD - i * GAP
        const [px, py] = path.point(d)
        const [tx, ty] = tangent(d)
        const nx = -ty
        const ny = tx
        const f = i / (SEG - 1)
        const ampScale = Math.min(1, f / 0.15)
        const wave = 6.5 * ampScale * Math.sin(time * 6.5 - i * 0.55)
        pts.push({ x: px + nx * wave, y: py + ny * wave, nx, ny, f })
      }

      // Tapered ribbon body.
      ctx.beginPath()
      for (let i = 0; i < pts.length; i++) {
        const wdt = halfWidth(pts[i].f)
        const X = pts[i].x + pts[i].nx * wdt
        const Y = pts[i].y + pts[i].ny * wdt
        if (i === 0) ctx.moveTo(X, Y)
        else ctx.lineTo(X, Y)
      }
      for (let i = pts.length - 1; i >= 0; i--) {
        const wdt = halfWidth(pts[i].f)
        ctx.lineTo(pts[i].x - pts[i].nx * wdt, pts[i].y - pts[i].ny * wdt)
      }
      ctx.closePath()
      const last = pts[pts.length - 1]
      const g = ctx.createLinearGradient(pts[0].x, pts[0].y, last.x, last.y)
      g.addColorStop(0, `rgb(${HEAD[0]},${HEAD[1]},${HEAD[2]})`)
      g.addColorStop(0.35, "#e6ad3f")
      g.addColorStop(1, `rgba(${TAIL[0]},${TAIL[1]},${TAIL[2]},0)`)
      ctx.fillStyle = g
      ctx.shadowColor = "rgba(230,173,63,.45)"
      ctx.shadowBlur = 12
      ctx.fill()
      ctx.shadowBlur = 0

      // Head + eyes.
      const head = pts[0]
      const fdx = head.x - pts[1].x
      const fdy = head.y - pts[1].y
      const fL = Math.hypot(fdx, fdy) || 1
      const fx = fdx / fL
      const fy = fdy / fL
      ctx.fillStyle = `rgb(${HEAD[0]},${HEAD[1]},${HEAD[2]})`
      ctx.shadowColor = "rgba(230,173,63,.6)"
      ctx.shadowBlur = 14
      ctx.beginPath()
      ctx.arc(head.x, head.y, 6.6, 0, Math.PI * 2)
      ctx.fill()
      ctx.shadowBlur = 0
      ctx.fillStyle = "#0b0d13"
      for (const s of [1, -1]) {
        const ex = head.x + fx * 1.3 + head.nx * 2.4 * s
        const ey = head.y + fy * 1.3 + head.ny * 2.4 * s
        ctx.beginPath()
        ctx.arc(ex, ey, 1.15, 0, Math.PI * 2)
        ctx.fill()
      }
    }

    let raf = 0
    const t0 = performance.now()
    if (reduce) {
      ctx.setLineDash([2, 7])
      drawTrack("rgba(230,173,63,.5)")
      ctx.setLineDash([])
    } else {
      const loop = (now: number) => {
        const t = (now - t0) / 1000
        if (onlineRef.current) {
          ctx.clearRect(0, 0, innerWidth, innerHeight)
          ctx.shadowColor = "rgba(90,208,140,.8)"
          ctx.shadowBlur = 22
          drawTrack("rgba(90,208,140,.9)")
          ctx.shadowBlur = 0
        } else {
          drawSnake(t * SPEED, t)
        }
        raf = requestAnimationFrame(loop)
      }
      raf = requestAnimationFrame(loop)
    }

    return () => {
      cancelAnimationFrame(raf)
      removeEventListener("resize", build)
    }
  }, [])

  const shown = STEPS.filter((s) => elapsed >= s.at)
  const lastIdx = shown.length - 1

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center overflow-hidden bg-background"
      role="status"
      aria-live="polite"
    >
      <div className="severity-spectrum absolute inset-x-0 top-0 h-0.5" aria-hidden="true" />
      <canvas ref={canvasRef} className="pointer-events-none absolute inset-0" aria-hidden="true" />

      <div className="relative w-[min(92vw,560px)] px-6">
        <div className="mb-6">
          <Logo markClassName="size-9" wordmarkClassName="text-2xl" />
        </div>

        <p className="mb-2 font-mono text-[10.5px] tracking-[0.32em] text-primary uppercase">
          {online ? "Console online" : "Security operations console"}
        </p>
        <h1 className="mb-2.5 font-display text-2xl font-semibold tracking-tight">
          {online ? "Entering console" : "Waking the console"}
        </h1>
        <p className="mb-6 max-w-[46ch] text-sm leading-relaxed text-muted-foreground">
          The console was idle, so its server spun down to save resources.
          Bringing it back online — this only happens after inactivity, and
          takes a moment the first time.
        </p>

        <div className="flex min-h-[150px] flex-col gap-[7px] border-l-2 border-border pl-4">
          {shown.map((s, i) => (
            <div key={s.at} className="grid grid-cols-[52px_1fr] items-baseline gap-3 font-mono text-[12.5px]">
              <span className="text-[#59617a] tabular-nums">[{fmt(s.at)}]</span>
              <span className="text-[#c3c9d6]">
                ▸ {s.text}
                {s.ok && <span className="text-[#5ad08c]"> ✓</span>}
                {i === lastIdx && !online && (
                  <span className="ml-0.5 animate-pulse text-primary">▋</span>
                )}
              </span>
            </div>
          ))}
        </div>

        <div className="mt-6 flex items-center gap-4 font-mono text-[11px] tracking-[0.14em] text-muted-foreground uppercase">
          {online ? (
            <span className="flex items-center gap-2 text-[#5ad08c]">
              <span className="size-2 rounded-full bg-[#5ad08c] shadow-[0_0_10px_#5ad08c]" />
              Online — entering
            </span>
          ) : (
            <span>
              <span className="tabular-nums text-foreground">{fmt(elapsed)}</span> elapsed
            </span>
          )}
        </div>
      </div>
    </div>
  )
}

import { useEffect, useRef, useState } from 'react'
import { FALLBACK_BANDS, INFINITE_HF, TONE_HEX, fmtHF, hfTone } from '../lib/format'

/**
 * The signature element: Health Factor as a radial shield arc.
 *
 * Not a progress bar. The arc is a shield cross-section sweeping 240 degrees,
 * with hard tick marks at the two numbers that actually matter -- the
 * liquidation threshold at 1.0 and the user's safety target. The needle sweeps
 * as the price moves and the arc colour transitions teal -> amber -> red.
 *
 * Everything around this component is kept deliberately quiet. One signature
 * element, not scattered decoration.
 */

const START_ANGLE = -210 // degrees; 0 is 3 o'clock, negative is counter-clockwise
const SWEEP = 240
const HF_MIN = 0.5
const HF_MAX = 2.5

const polar = (cx, cy, r, angleDeg) => {
  const rad = (angleDeg * Math.PI) / 180
  return [cx + r * Math.cos(rad), cy + r * Math.sin(rad)]
}

/** Map a Health Factor onto its angle on the arc. */
function hfToAngle(hf) {
  const clamped = Math.min(Math.max(hf, HF_MIN), HF_MAX)
  const t = (clamped - HF_MIN) / (HF_MAX - HF_MIN)
  return START_ANGLE + t * SWEEP
}

function arcPath(cx, cy, r, fromDeg, toDeg) {
  const [x1, y1] = polar(cx, cy, r, fromDeg)
  const [x2, y2] = polar(cx, cy, r, toDeg)
  const large = Math.abs(toDeg - fromDeg) > 180 ? 1 : 0
  const sweep = toDeg > fromDeg ? 1 : 0
  return `M ${x1} ${y1} A ${r} ${r} 0 ${large} ${sweep} ${x2} ${y2}`
}

/** Smoothly walk `target` so the needle sweeps instead of snapping. */
function useSweep(target, duration = 900) {
  const [value, setValue] = useState(target)
  const frame = useRef()
  const from = useRef(target)
  const start = useRef(0)

  useEffect(() => {
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    if (reduced) {
      setValue(target)
      return undefined
    }
    from.current = value
    start.current = performance.now()

    const tick = (now) => {
      const t = Math.min((now - start.current) / duration, 1)
      // ease-in-out cubic: the needle settles rather than stopping dead
      const eased = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2
      setValue(from.current + (target - from.current) * eased)
      if (t < 1) frame.current = requestAnimationFrame(tick)
    }
    frame.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame.current)
    // `value` is intentionally excluded: including it restarts the tween on
    // every frame and the needle never arrives.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target, duration])

  return value
}

export default function HealthFactorGauge({
  healthFactor,
  target = 1.5,
  bands = FALLBACK_BANDS,   // callers pass the bands /api/defaults returned
  bufferPct = 0,
  size = 300,
  label = 'HEALTH FACTOR',
}) {
  const noDebt = healthFactor >= INFINITE_HF
  const displayHf = noDebt ? HF_MAX : (healthFactor ?? HF_MIN)
  const swept = useSweep(displayHf)
  const tone = hfTone(healthFactor ?? 0, bands)
  const colour = TONE_HEX[tone]

  const cx = size / 2
  const cy = size / 2
  const r = size / 2 - 26
  const needleAngle = hfToAngle(swept)

  const segments = [
    { from: HF_MIN, to: bands.danger, tone: 'danger' },
    { from: bands.danger, to: bands.warning, tone: 'warn' },
    { from: bands.warning, to: HF_MAX, tone: 'safe' },
  ]

  const ticks = [
    { hf: bands.liquidatable, text: '1.00', caption: 'LIQUIDATION', strong: true },
    { hf: target, text: target.toFixed(2), caption: 'TARGET', strong: true },
  ]

  const [needleX, needleY] = polar(cx, cy, r - 30, needleAngle)
  const [tailX, tailY] = polar(cx, cy, 16, needleAngle + 180)

  return (
    <figure className="flex flex-col items-center gap-1">
      <svg
        viewBox={`0 0 ${size} ${size}`}
        width="100%"
        style={{ maxWidth: size }}
        role="img"
        aria-label={`Health Factor ${fmtHF(healthFactor)}, ${tone === 'safe' ? 'safe' : tone === 'warn' ? 'warning' : 'danger'}. Liquidation at 1.00, target ${target.toFixed(2)}.`}
      >
        {/* track */}
        <path
          d={arcPath(cx, cy, r, START_ANGLE, START_ANGLE + SWEEP)}
          fill="none"
          stroke="#242D3A"
          strokeWidth="14"
          strokeLinecap="round"
        />

        {/* banded zones, drawn thin behind the live arc */}
        {segments.map((seg) => (
          <path
            key={seg.tone}
            d={arcPath(cx, cy, r + 13, hfToAngle(seg.from), hfToAngle(seg.to))}
            fill="none"
            stroke={TONE_HEX[seg.tone]}
            strokeWidth="2"
            opacity="0.35"
          />
        ))}

        {/* live value arc */}
        <path
          d={arcPath(cx, cy, r, START_ANGLE, needleAngle)}
          fill="none"
          stroke={colour}
          strokeWidth="14"
          strokeLinecap="round"
          style={{ transition: 'stroke 500ms ease' }}
        />

        {/* threshold ticks */}
        {ticks.map((tick) => {
          const angle = hfToAngle(tick.hf)
          const [ix, iy] = polar(cx, cy, r - 12, angle)
          const [ox, oy] = polar(cx, cy, r + 10, angle)
          const [lx, ly] = polar(cx, cy, r + 24, angle)
          return (
            <g key={tick.caption}>
              <line
                x1={ix}
                y1={iy}
                x2={ox}
                y2={oy}
                stroke={tick.caption === 'LIQUIDATION' ? TONE_HEX.danger : '#E8ECF1'}
                strokeWidth={tick.strong ? 2.5 : 1.5}
              />
              <text
                x={lx}
                y={ly}
                fill="#7C8798"
                fontSize="9"
                fontFamily="'JetBrains Mono', monospace"
                textAnchor={lx < cx ? 'end' : 'start'}
                dominantBaseline="middle"
              >
                {tick.text}
              </text>
            </g>
          )
        })}

        {/* needle */}
        <line
          x1={tailX}
          y1={tailY}
          x2={needleX}
          y2={needleY}
          stroke={colour}
          strokeWidth="3"
          strokeLinecap="round"
        />
        <circle cx={cx} cy={cy} r="7" fill="#0D1117" stroke={colour} strokeWidth="2.5" />

        {/* readout */}
        <text
          x={cx}
          y={cy + 48}
          textAnchor="middle"
          fill={colour}
          fontSize="40"
          fontWeight="700"
          fontFamily="'JetBrains Mono', monospace"
          style={{ fontVariantNumeric: 'tabular-nums' }}
        >
          {fmtHF(healthFactor)}
        </text>
        <text
          x={cx}
          y={cy + 70}
          textAnchor="middle"
          fill="#7C8798"
          fontSize="10"
          letterSpacing="0.18em"
          fontFamily="'Space Grotesk', sans-serif"
        >
          {label}
        </text>
      </svg>

      <figcaption className="text-center text-xs text-muted">
        Safety buffer{' '}
        <span className="tabular text-ink">{(bufferPct ?? 0).toFixed(0)}%</span> of the
        1.00 → {target.toFixed(2)} band
      </figcaption>
    </figure>
  )
}

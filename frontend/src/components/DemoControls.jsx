import { Loader2, Play, RotateCcw } from 'lucide-react'
import { useShield } from '../state/ShieldContext'
import { Button } from './ui'
import { TONE_HEX } from '../lib/format'

/**
 * Demo Mode trigger.
 *
 * One click sends one number (the drop percentage) to the backend. What comes
 * back is replayed below: each line is a stage the engine reported, tagged
 * with the shield state it was in.
 */

const STATE_TONE = {
  ARMED: TONE_HEX.safe,
  PROTECTED: TONE_HEX.safe,
  ALERT: TONE_HEX.warn,
  PROTECTING: TONE_HEX.warn,
  SKIPPED: TONE_HEX.danger,
}

export default function DemoControls() {
  const { runDemo, resetPosition, demoRunning, traceSteps, busy, demoDropPct, preferences } =
    useShield()

  return (
    <div className="flex flex-col gap-2.5 rounded-lg border border-hairline bg-panel p-3">
      <p className="font-display text-[10px] tracking-[0.16em] text-muted uppercase">
        Demo scenario: ETH -{demoDropPct}%
      </p>

      <Button variant="primary" onClick={runDemo} disabled={demoRunning || busy}>
        {demoRunning ? (
          <>
            <Loader2 size={14} className="animate-spin" aria-hidden="true" />
            Running cycle…
          </>
        ) : (
          <>
            <Play size={14} aria-hidden="true" />
            Simulate {demoDropPct}% ETH drop
          </>
        )}
      </Button>

      <Button variant="ghost" onClick={resetPosition} disabled={demoRunning || busy}>
        <RotateCcw size={14} aria-hidden="true" />
        Reset position
      </Button>

      <p className="text-[11px] leading-snug text-muted">
        {preferences?.mode === 'ADVISORY'
          ? 'Advisory mode: the agent stops at the recommendation.'
          : 'Autonomous mode: the agent executes without asking.'}
      </p>

      <p className="text-[11px] leading-snug text-muted">
        Stress-tests the position at{' '}
        <span className="tabular text-ink">current price × 0.{100 - demoDropPct}</span>. The real
        market price is not changed.
      </p>

      {traceSteps.length > 0 && (
        <ol className="flex flex-col gap-1 border-t border-hairline pt-2.5" aria-live="polite">
          {traceSteps.map((step, i) => (
            <li key={step.stage + String(i)} className="flex gap-1.5 text-[11px] leading-snug">
              <span
                className="w-[68px] shrink-0 font-display text-[9px] tracking-[0.08em]"
                style={{ color: STATE_TONE[step.shield_state] ?? TONE_HEX.muted }}
              >
                {step.shield_state}
              </span>
              <span className={i === traceSteps.length - 1 ? 'text-ink' : 'text-muted'}>
                {step.label}
              </span>
            </li>
          ))}
          {demoRunning && (
            <li className="flex gap-1.5 text-[11px] text-muted">
              <span className="w-[68px] shrink-0" />
              <span className="animate-shield-pulse">…</span>
            </li>
          )}
        </ol>
      )}
    </div>
  )
}

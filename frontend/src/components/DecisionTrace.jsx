import { ArrowRight, ScrollText } from 'lucide-react'
import { useShield } from '../state/ShieldContext'
import { Badge, EmptyState, Panel } from './ui'
import { TONE_HEX, fmtHF, fmtPrice, fmtUsd0, riskTone } from '../lib/format'

/**
 * Decision Trace.
 *
 * Every field here is read straight out of the backend's `decision_trace`
 * block. Nothing is derived in the browser -- if the panel is wrong, the
 * engine is wrong, which is exactly the property we want.
 */

const FINAL_STATUS_TONE = {
  PROTECTED: 'safe',
  MONITORING: 'safe',
  'AWAITING CONFIRMATION': 'warn',
  'STOOD DOWN': 'danger',
}

const EXECUTION_TONE = {
  'SIMULATED SUCCESS': 'safe',
  'AWAITING CONFIRMATION': 'warn',
  'STOOD DOWN': 'danger',
  'NOT REQUIRED': 'muted',
}

function Row({ label, children, mono = false }) {
  return (
    <div className="flex flex-col gap-0.5 border-b border-hairline/60 py-2 last:border-b-0 sm:flex-row sm:items-baseline sm:gap-4">
      <dt className="font-display text-[10px] tracking-[0.14em] text-muted uppercase sm:w-44 sm:shrink-0">
        {label}
      </dt>
      <dd className={`min-w-0 break-words text-sm text-ink ${mono ? 'tabular' : ''}`}>
        {children}
      </dd>
    </div>
  )
}

export default function DecisionTrace() {
  const { decisionTrace, traceSteps, demoRunning, collateralSpec } = useShield()

  if (!decisionTrace) {
    return (
      <Panel title="Decision trace">
        <EmptyState icon={ScrollText} title="No cycle run yet">
          Enter your position and press <span className="text-ink">Analyze position</span>, or
          run <span className="text-ink">Simulate 10% ETH drop</span>. Either way the backend
          runs the whole cycle and returns each stage; this panel shows what it decided and why.
        </EmptyState>
      </Panel>
    )
  }

  const t = decisionTrace
  const executionTone = EXECUTION_TONE[t.execution] ?? 'muted'

  return (
    <Panel
      title="Decision trace"
      subtitle="Returned by the backend for this cycle. Not computed in the browser."
      actions={<Badge tone={executionTone}>{t.execution}</Badge>}
    >
      <dl className="flex flex-col">
        <Row label="Scenario" mono>
          {t.scenario}
          <span className="block text-muted sm:ml-2 sm:inline">
            {fmtPrice(t.price_before, collateralSpec?.price_decimals)}{' '}
            <ArrowRight size={11} className="inline" aria-hidden="true" />{' '}
            {fmtPrice(t.price_after, collateralSpec?.price_decimals)}
          </span>
        </Row>

        <Row label="Collateral after shock" mono>
          {fmtUsd0(t.collateral_value_after)}
        </Row>

        <Row label="Health factor" mono>
          <span style={{ color: TONE_HEX.muted }}>{fmtHF(t.health_factor_before)}</span>
          <span className="text-muted"> → </span>
          <span style={{ color: TONE_HEX[riskTone(t.risk_level)] }}>
            {fmtHF(t.health_factor_after_shock)}
          </span>
        </Row>

        <Row label="Risk">
          {t.risk_level_before && t.risk_level_before !== t.risk_level ? (
            <>
              <span style={{ color: TONE_HEX[riskTone(t.risk_level_before)] }}>
                {t.risk_level_before}
              </span>
              <span className="text-muted"> → </span>
              <span style={{ color: TONE_HEX[riskTone(t.risk_level)] }}>{t.risk_level}</span>
            </>
          ) : (
            <span style={{ color: TONE_HEX[riskTone(t.risk_level)] }}>{t.risk_level}</span>
          )}
        </Row>

        <Row label="Strategies generated" mono>
          {t.strategies_generated}
        </Row>

        <Row label="Strategies rejected" mono>
          <span style={{ color: t.strategies_rejected > 0 ? TONE_HEX.warn : TONE_HEX.muted }}>
            {t.strategies_rejected}
          </span>
          <span className="text-muted"> of {t.strategies_generated}</span>
        </Row>

        <Row label="Selected">{t.selected ?? <span className="text-muted">None</span>}</Row>

        <Row label="Why selected">
          <span className="text-muted">{t.why_selected}</span>
        </Row>

        <Row label="Mode">{t.mode === 'ADVISORY' ? 'Advisory' : 'Autonomous'}</Row>

        <Row label="Execution">
          <Badge tone={executionTone}>{t.execution}</Badge>
        </Row>

        <Row label="Final health factor" mono>
          <span style={{ color: TONE_HEX[riskTone(t.final_risk_level)] }}>
            {fmtHF(t.final_health_factor)}
          </span>
          <span className="text-muted"> · {t.final_risk_level}</span>
        </Row>

        <Row label="Final status">
          <Badge tone={FINAL_STATUS_TONE[t.final_status] ?? 'muted'}>
            {t.final_status ?? '—'}
          </Badge>
        </Row>
      </dl>

      {traceSteps.length > 0 && (
        <div className="mt-4 border-t border-hairline pt-3">
          <p className="font-display text-[10px] tracking-[0.14em] text-muted uppercase">
            Stage log
          </p>
          <ol className="mt-2 flex flex-col gap-1.5" aria-live="polite">
            {traceSteps.map((step, i) => (
              <li key={step.stage + String(i)} className="flex gap-2.5 text-xs">
                <span className="tabular w-6 shrink-0 text-muted">
                  {String(i + 1).padStart(2, '0')}
                </span>
                <span
                  className="w-24 shrink-0 font-display text-[10px] tracking-[0.1em]"
                  style={{
                    color:
                      step.shield_state === 'PROTECTED' || step.shield_state === 'ARMED'
                        ? TONE_HEX.safe
                        : step.shield_state === 'SKIPPED'
                          ? TONE_HEX.danger
                          : TONE_HEX.warn,
                  }}
                >
                  {step.shield_state}
                </span>
                <span className="min-w-0 break-words">
                  <span className="text-ink">{step.label}</span>
                  <span className="text-muted"> — {step.detail}</span>
                </span>
              </li>
            ))}
            {demoRunning && (
              <li className="flex gap-2.5 text-xs text-muted">
                <span className="tabular w-6 shrink-0">··</span>
                <span className="animate-shield-pulse">working…</span>
              </li>
            )}
          </ol>
        </div>
      )}
    </Panel>
  )
}

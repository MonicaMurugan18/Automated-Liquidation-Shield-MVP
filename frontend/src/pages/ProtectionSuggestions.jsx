import { CheckCircle2, ShieldCheck, XCircle } from 'lucide-react'
import { useShield } from '../state/ShieldContext'
import { Badge, Button, EmptyState, Panel, ScoreBar } from '../components/ui'
import {
  SAFETY_TONE,
  STATUS_LABEL,
  TONE_HEX,
  fmtHF,
  fmtPct,
  fmtUsd,
  fmtUsd0,
  hfTone,
  statusTone,
} from '../lib/format'

/**
 * Page 4: the generated strategies -- differentiator #2.
 *
 * Every candidate the agent produced, priced and constraint-checked. Rejected
 * candidates stay on screen with their reason: an audit trail that only lists
 * winners is not an audit trail.
 */

function StrategyCard({ row, bands }) {
  const tone = statusTone(row.status)
  const viable = row.status === 'VIABLE'

  return (
    <article
      className={`rounded-lg border bg-panel p-4 ${
        row.selected ? 'border-safe/60 ring-1 ring-safe/25' : 'border-hairline'
      }`}
    >
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          {viable ? (
            <CheckCircle2 size={16} className="shrink-0 text-safe" aria-hidden="true" />
          ) : (
            <XCircle size={16} className="shrink-0 text-danger" aria-hidden="true" />
          )}
          <h3 className="font-display text-sm font-medium text-ink">{row.name}</h3>
        </div>
        <div className="flex items-center gap-2">
          {row.selected && (
            <Badge tone="safe">
              <ShieldCheck size={11} aria-hidden="true" /> auto-selected
            </Badge>
          )}
          <Badge tone={tone}>{STATUS_LABEL[row.status] ?? row.status}</Badge>
        </div>
      </header>

      <dl className="mt-3.5 grid grid-cols-2 gap-x-4 gap-y-2 text-xs sm:grid-cols-4">
        <div>
          <dt className="text-muted">Amount</dt>
          <dd className="tabular mt-0.5 text-sm text-ink">
            {row.action_amount != null ? fmtUsd0(row.action_amount) : '—'}
          </dd>
        </div>
        <div>
          <dt className="text-muted">Capital needed</dt>
          <dd className="tabular mt-0.5 text-sm text-ink">
            {row.required_capital > 0 ? fmtUsd0(row.required_capital) : 'None'}
          </dd>
        </div>
        <div>
          <dt className="text-muted">HF after</dt>
          <dd
            className="tabular mt-0.5 text-sm"
            style={{
              color: viable ? TONE_HEX[hfTone(row.resulting_health_factor, bands)] : '#7C8798',
            }}
          >
            {row.resulting_health_factor > 0 ? fmtHF(row.resulting_health_factor) : '—'}
          </dd>
        </div>
        <div>
          <dt className="text-muted">Total cost</dt>
          <dd className="tabular mt-0.5 text-sm text-ink">{fmtUsd(row.total_cost)}</dd>
        </div>
      </dl>

      <dl className="mt-2.5 grid grid-cols-3 gap-x-4 gap-y-1 border-t border-hairline pt-2.5 text-[11px]">
        <div className="flex justify-between gap-2">
          <dt className="text-muted">Gas</dt>
          <dd className="tabular text-ink">{fmtUsd(row.gas_cost)}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-muted">Slippage</dt>
          <dd className="tabular text-ink">
            {row.slippage_pct > 0 ? fmtPct(row.slippage_pct) : '—'}
          </dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-muted">Flash fee</dt>
          <dd className="tabular text-ink">
            {row.flash_loan_fee > 0 ? fmtUsd(row.flash_loan_fee) : '—'}
          </dd>
        </div>
      </dl>

      {row.rejection_reason && (
        <p className="mt-3 rounded-md border border-hairline bg-base px-3 py-2 text-xs text-muted">
          {row.rejection_reason}
        </p>
      )}

      {viable && (
        <div className="mt-3 flex flex-col gap-1.5 border-t border-hairline pt-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <span className="font-display text-[10px] tracking-[0.14em] text-muted uppercase">
              Composite score
            </span>
            <span className="flex items-baseline gap-2">
              {row.safety_level && (
                <Badge tone={SAFETY_TONE[row.safety_level]}>
                  {row.safety_level} safety
                </Badge>
              )}
              <span className="tabular text-sm text-ink">
                {row.score_100}
                <span className="text-muted">/100</span>
              </span>
            </span>
          </div>
          {Object.entries(row.score_breakdown).map(([key, value]) => (
            <ScoreBar
              key={key}
              label={key}
              value={value}
              tone={value >= 0.75 ? 'safe' : value >= 0.4 ? 'warn' : 'danger'}
            />
          ))}
        </div>
      )}
    </article>
  )
}

export default function ProtectionSuggestions() {
  const {
    strategies: liveStrategies,
    explanation: liveExplanation,
    assessment,
    validation,
    selectedStrategy: liveSelected,
    executeRescue,
    busy,
    bands,
    preferences,
    lastCycle,
  } = useShield()

  if (!assessment) return null

  // Live candidates when the position still needs one; otherwise the set that
  // produced the last decision, so it stays auditable after the rescue.
  const reviewing = liveStrategies.length === 0 && Boolean(lastCycle)
  const strategies = reviewing ? lastCycle.strategies : liveStrategies
  const explanation = reviewing ? lastCycle.explanation : liveExplanation
  const selectedStrategy = reviewing ? lastCycle.selected : liveSelected
  // While reviewing, the live `validation` describes the *protected* position,
  // whose economics are all zero. Show the archived cycle's figures instead --
  // those are the numbers the decision was actually made on.
  const economics = reviewing ? lastCycle.economics : validation?.economics

  if (!strategies.length) {
    return (
      <Panel title="Protection strategies">
        <EmptyState icon={ShieldCheck} title="No rescue required">
          The position is at Health Factor {fmtHF(assessment.health_factor)}, above the{' '}
          {preferences.trigger_health_factor.toFixed(2)} intervention trigger. The agent
          generates strategies only when a position actually needs one — there is nothing to
          recommend here.
        </EmptyState>
      </Panel>
    )
  }

  const canConfirm = validation?.execution_status === 'AWAITING_CONFIRMATION'
  const counts = {
    total: strategies.length,
    valid: strategies.filter((s) => s.is_executable ?? s.status === 'VIABLE').length,
    rejected: strategies.filter((s) => !(s.is_executable ?? s.status === 'VIABLE')).length,
  }

  return (
    <div className="flex flex-col gap-5">
      {reviewing && (
        <p className="rounded-md border border-safe/40 bg-safe/10 px-4 py-2.5 text-sm text-safe">
          Reviewing the last completed cycle. The position is protected, so there is nothing
          live to suggest — this is the candidate set the agent actually chose from.
        </p>
      )}

      <Panel
        title={
          reviewing
            ? 'Decision taken'
            : preferences.mode === 'AUTONOMOUS'
              ? 'Autonomous decision'
              : 'Advisory recommendation'
        }
        actions={
          canConfirm && (
            <Button variant="primary" onClick={() => executeRescue({ confirm: true })} disabled={busy}>
              Confirm and execute
            </Button>
          )
        }
      >
        {selectedStrategy && (
          <div className="mb-3 grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
            <div>
              <p className="font-display text-[10px] tracking-[0.16em] text-muted uppercase">
                Selected strategy
              </p>
              <p className="mt-0.5 font-display text-lg text-safe">{selectedStrategy.name}</p>
            </div>
            <div className="flex flex-wrap gap-4 sm:justify-end">
              <div>
                <p className="font-display text-[10px] tracking-[0.16em] text-muted uppercase">
                  Score
                </p>
                <p className="tabular mt-0.5 text-lg text-ink">
                  {selectedStrategy.score_100}
                  <span className="text-muted">/100</span>
                </p>
              </div>
              <div>
                <p className="font-display text-[10px] tracking-[0.16em] text-muted uppercase">
                  HF after
                </p>
                <p className="tabular mt-0.5 text-lg text-safe">
                  {fmtHF(selectedStrategy.resulting_health_factor)}
                </p>
              </div>
            </div>
          </div>
        )}

        <dl className="mb-3 flex flex-wrap gap-x-6 gap-y-2 rounded-md border border-hairline bg-panel-raised px-3.5 py-2.5 text-xs">
          {[
            ['Strategies considered', counts.total, 'text-ink'],
            ['Valid', counts.valid, 'text-safe'],
            ['Rejected', counts.rejected, counts.rejected > 0 ? 'text-warn' : 'text-muted'],
          ].map(([label, value, tone]) => (
            <div key={label} className="flex gap-2">
              <dt className="text-muted">{label}</dt>
              <dd className={`tabular ${tone}`}>{value}</dd>
            </div>
          ))}
        </dl>

        <p className="font-display text-[10px] tracking-[0.16em] text-muted uppercase">
          Why selected
        </p>
        <p className="mt-1 text-sm text-ink">{explanation}</p>
        {economics && (
          <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-2 border-t border-hairline pt-3 text-xs">
            <div className="flex gap-2">
              <dt className="text-muted">Rescue cost</dt>
              <dd className="tabular text-ink">{fmtUsd(economics.rescue_cost)}</dd>
            </div>
            <div className="flex gap-2">
              <dt className="text-muted">Loss avoided</dt>
              <dd className="tabular text-ink">{fmtUsd(economics.potential_loss)}</dd>
            </div>
            <div className="flex gap-2">
              <dt className="text-muted">Net benefit</dt>
              <dd
                className="tabular"
                style={{
                  color: economics.net_benefit >= 0 ? TONE_HEX.safe : TONE_HEX.danger,
                }}
              >
                {fmtUsd(economics.net_benefit)}
              </dd>
            </div>
          </dl>
        )}
      </Panel>

      <div className="grid gap-4 xl:grid-cols-2">
        {strategies.map((row) => (
          <StrategyCard key={row.strategy_type} row={row} bands={bands} />
        ))}
      </div>

      {selectedStrategy && (
        <p className="text-xs text-muted">
          Scores are computed by the strategy engine from the weights on the Settings page.
          Rejected candidates score zero and can never be selected.
        </p>
      )}
    </div>
  )
}

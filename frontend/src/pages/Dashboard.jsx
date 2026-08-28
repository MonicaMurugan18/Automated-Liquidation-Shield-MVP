import { Link } from 'react-router-dom'
import { ArrowRight, CheckCircle2, CircleSlash, Info, Loader2 } from 'lucide-react'
import { useShield } from '../state/ShieldContext'
import HealthFactorGauge from '../components/HealthFactorGauge'
import DecisionTrace from '../components/DecisionTrace'
import PositionForm from '../components/PositionForm'
import MarketPanel from '../components/MarketPanel'
import StepIndicator from '../components/StepIndicator'
import { shieldState as lookupState } from '../lib/shieldStates'
import { Badge, Button, Panel, RiskBadge, Stat } from '../components/ui'
import {
  EXECUTION_LABEL,
  fmtHF,
  fmtPct,
  fmtPrice,
  fmtUsd,
  fmtUsd0,
  riskTone,
} from '../lib/format'

/**
 * Page 1: the instrument panel.
 *
 * Every figure below is a field of the backend's response. The protection
 * badge reflects the agent's actual state -- not the configured mode -- so it
 * cannot claim "protecting" while the agent is merely watching.
 */

function Working({ label }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-muted">
      <Loader2 size={12} className="animate-spin" aria-hidden="true" />
      {label}
    </span>
  )
}

export default function Dashboard() {
  const {
    position,
    preferences,
    assessment,
    validation,
    selectedStrategy,
    explanation,
    lastRescue,
    executeRescue,
    busy,
    activity,
    bands,
    breakingScenario,
    scenarioSummary,
    shieldState,
    demoRunning,
    collateralSpec,
  } = useShield()

  if (!assessment || !bands) return null

  const state = lookupState(shieldState)
  const advisoryHold = validation?.execution_status === 'AWAITING_CONFIRMATION'
  const stoodDown = validation?.execution_status?.startsWith('SKIPPED')

  const priceDecimals = collateralSpec?.price_decimals

  return (
    <div className="flex flex-col gap-5">
      <MarketPanel />

      <PositionForm />

      <Panel title="Workflow">
        <StepIndicator />
      </Panel>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,340px)_minmax(0,1fr)]">
        <Panel
          title="Health factor"
          actions={busy && <Working label={activity ?? 'Updating'} />}
        >
          <HealthFactorGauge
            healthFactor={assessment.health_factor}
            target={preferences.target_health_factor}
            bands={bands}
            bufferPct={assessment.safety_buffer_pct}
          />
          <div className="mt-4 flex items-center justify-center">
            <RiskBadge level={assessment.risk_level} />
          </div>
          <p className="mt-3 text-center text-sm text-muted">{assessment.message}</p>
        </Panel>

        <div className="flex flex-col gap-5">
          <Panel
            title="Position"
            actions={
              /* Driven by the agent's live state, never by the mode setting. */
              <Badge tone={state.tone}>{state.label}</Badge>
            }
          >
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Stat
                label="Collateral"
                value={fmtUsd0(assessment.collateral_value)}
                sub={`${position.collateral_amount.toFixed(4)} ${position.collateral_asset}`}
              />
              <Stat
                label="Debt"
                value={fmtUsd0(assessment.debt_value)}
                sub={position.debt_asset}
              />
              <Stat
                label={`${position.collateral_asset} price`}
                value={fmtPrice(position.collateral_price, priceDecimals)}
                sub={`Liq. at ${fmtPrice(assessment.liquidation_price, priceDecimals)}`}
              />
              <Stat
                label="Risk"
                value={assessment.risk_level}
                tone={riskTone(assessment.risk_level)}
                mono={false}
              />
            </div>

            <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
              <Stat
                label="Drop to liquidation"
                value={fmtPct(assessment.price_drop_to_liquidation_pct, 1)}
                sub="from the current price"
                tone={assessment.price_drop_to_liquidation_pct < 10 ? 'danger' : 'muted'}
              />
              <Stat
                label="Loss if liquidated"
                value={fmtUsd0(assessment.potential_liquidation_loss)}
                sub={`${(position.close_factor * 100).toFixed(0)}% close factor · ${(position.liquidation_bonus * 100).toFixed(0)}% penalty`}
              />
              <Stat
                label="Mode"
                value={preferences.mode === 'AUTONOMOUS' ? 'Autonomous' : 'Advisory'}
                mono={false}
                sub={`target ${preferences.target_health_factor.toFixed(2)} · acts below ${preferences.trigger_health_factor.toFixed(2)}`}
              />
            </div>
          </Panel>

          <Panel
            title="Agent decision"
            actions={demoRunning && <Working label="Cycle running" />}
          >
            {lastRescue?.executed ? (
              <div className="flex flex-col gap-3">
                <div className="flex items-start gap-2.5 rounded-md border border-safe/40 bg-safe/10 px-3.5 py-3">
                  <CheckCircle2 size={18} className="mt-0.5 shrink-0 text-safe" aria-hidden="true" />
                  <div>
                    <p className="font-display text-sm text-safe">Position protected</p>
                    <p className="mt-0.5 text-sm text-muted">
                      {lastRescue.selected_strategy.name} executed. Health Factor{' '}
                      <span className="tabular text-ink">
                        {fmtHF(lastRescue.assessment_before.health_factor)}
                      </span>{' '}
                      →{' '}
                      <span className="tabular text-safe">
                        {fmtHF(lastRescue.assessment_after.health_factor)}
                      </span>{' '}
                      at a cost of{' '}
                      <span className="tabular text-ink">
                        {fmtUsd(lastRescue.selected_strategy.total_cost)}
                      </span>
                      .
                    </p>
                  </div>
                </div>
                <p className="text-xs text-muted">
                  Simulated transaction {lastRescue.transaction.tx_hash.slice(0, 14)}… ·{' '}
                  <Link to="/portal/history" className="text-ink underline underline-offset-2">
                    view in history
                  </Link>
                </p>
              </div>
            ) : stoodDown ? (
              <div className="flex items-start gap-2.5 rounded-md border border-danger/40 bg-danger/10 px-3.5 py-3">
                <CircleSlash size={18} className="mt-0.5 shrink-0 text-danger" aria-hidden="true" />
                <div>
                  <p className="font-display text-sm text-danger">
                    {EXECUTION_LABEL[validation.execution_status]}
                  </p>
                  <p className="mt-0.5 text-sm text-muted">{validation.reason}</p>
                </div>
              </div>
            ) : advisoryHold ? (
              <div className="flex flex-col gap-3">
                <div className="flex items-start gap-2.5 rounded-md border border-warn/40 bg-warn/10 px-3.5 py-3">
                  <Info size={18} className="mt-0.5 shrink-0 text-warn" aria-hidden="true" />
                  <div>
                    <p className="font-display text-sm text-warn">Recommendation ready</p>
                    <p className="mt-0.5 text-sm text-muted">{explanation}</p>
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="primary"
                    onClick={() => executeRescue({ confirm: true })}
                    disabled={busy}
                  >
                    {busy ? (
                      <>
                        <Loader2 size={14} className="animate-spin" aria-hidden="true" />
                        Executing…
                      </>
                    ) : (
                      `Confirm ${selectedStrategy?.name}`
                    )}
                  </Button>
                  <Link
                    to="/portal/comparison"
                    className="inline-flex items-center gap-1.5 rounded-md border border-hairline bg-panel-raised px-3.5 py-2 font-display text-sm text-ink transition-colors hover:border-muted"
                  >
                    Review the comparison <ArrowRight size={14} aria-hidden="true" />
                  </Link>
                </div>
              </div>
            ) : assessment.requires_action ? (
              <div className="flex flex-col gap-3">
                <p className="text-sm text-muted">{explanation}</p>
                <Button variant="primary" onClick={() => executeRescue()} disabled={busy}>
                  {busy ? (
                    <>
                      <Loader2 size={14} className="animate-spin" aria-hidden="true" />
                      Executing…
                    </>
                  ) : (
                    'Execute now (simulated)'
                  )}
                </Button>
              </div>
            ) : (
              <div className="flex flex-col gap-3">
                <p className="text-sm text-muted">
                  No rescue required. The agent is holding at{' '}
                  <span className="tabular text-ink">{fmtHF(assessment.health_factor)}</span> and
                  will intervene below{' '}
                  <span className="tabular text-ink">
                    {preferences.trigger_health_factor.toFixed(2)}
                  </span>
                  .
                </p>
                <p className="text-sm text-muted">
                  {breakingScenario
                    ? `A ${breakingScenario.label} move would liquidate this position.`
                    : scenarioSummary}{' '}
                  <Link to="/portal/scenarios" className="text-ink underline underline-offset-2">
                    See the projections
                  </Link>
                  .
                </p>
              </div>
            )}
          </Panel>
        </div>
      </div>

      <DecisionTrace />
    </div>
  )
}

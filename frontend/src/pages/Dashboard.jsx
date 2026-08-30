import { useState } from 'react'
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
 * Every figure below is a field of the backend response.
 * The protection badge reflects the agent's actual state.
 */

function Working({ label }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-muted">
      <Loader2 size={12} className="animate-spin" aria-hidden="true" />
      {label}
    </span>
  )
}

/**
 * Adapt the backend guidance to the existing panel layout. The backend owns
 * the risk band, wording, and action list; this function only maps fields.
 */
function getSmartSuggestion(guidance) {
  if (!guidance) return null

  const icon = guidance.urgency === 'CRITICAL'
    ? '🚨'
    : guidance.tone === 'danger'
      ? '🔴'
      : guidance.tone === 'warn'
        ? '🟠'
        : '🟢'

  return {
    icon,
    title: guidance.headline,
    message: guidance.summary,
    actions: guidance.suggestions.map((suggestion) => `${suggestion.title}: ${suggestion.detail}`),
    tone: guidance.tone,
  }
}

export default function Dashboard() {
  const {
    position,
    preferences,
    assessment,
    validation,
    strategies,
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

  // Every hook must run on every render, so this sits ABOVE the early return
  // below. Placing it after the guard meant it was skipped whenever the
  // dashboard bailed out for missing data, and React's hook order broke on the
  // very next render that did have data.
  const [chosenStrategy, setChosenStrategy] = useState('')

  if (!assessment || !bands) return null

  const state = lookupState(shieldState)
  const viableCount = strategies.filter(
    (s) => s.is_executable ?? s.status === 'VIABLE',
  ).length
  const advisoryHold = validation?.execution_status === 'AWAITING_CONFIRMATION'
  const stoodDown = validation?.execution_status?.startsWith('SKIPPED')

  const priceDecimals = collateralSpec?.price_decimals

  const suggestion = getSmartSuggestion(validation?.guidance)

  return (
    <div className="flex flex-col gap-5">

      {/* =========================================================
          MARKET
      ========================================================== */}
      <MarketPanel />

      {/* =========================================================
          POSITION FORM
      ========================================================== */}
      <PositionForm />

      {/* =========================================================
          WORKFLOW
      ========================================================== */}
      <Panel title="Workflow">
        <StepIndicator />
      </Panel>

      {/* =========================================================
          MAIN DASHBOARD
      ========================================================== */}
      <div className="grid gap-5 lg:grid-cols-[minmax(0,340px)_minmax(0,1fr)]">

        {/* =======================================================
            HEALTH FACTOR
        ======================================================== */}
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

          <p className="mt-3 text-center text-sm text-muted">
            {assessment.message}
          </p>
        </Panel>

        {/* =======================================================
            RIGHT SIDE
        ======================================================== */}
        <div className="flex flex-col gap-5">

          {/* =====================================================
              POSITION
          ====================================================== */}
          <Panel
            title="Position"
            actions={
              <Badge tone={state.tone}>
                {state.label}
              </Badge>
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
                value={fmtPrice(
                  position.collateral_price,
                  priceDecimals,
                )}
                sub={`Liq. at ${fmtPrice(
                  assessment.liquidation_price,
                  priceDecimals,
                )}`}
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
                value={fmtPct(
                  assessment.price_drop_to_liquidation_pct,
                  1,
                )}
                sub="from the current price"
                tone={
                  assessment.price_drop_to_liquidation_pct < 10
                    ? 'danger'
                    : 'muted'
                }
              />

              <Stat
                label="Loss if liquidated"
                value={fmtUsd0(
                  assessment.potential_liquidation_loss,
                )}
                sub={`${(
                  position.close_factor * 100
                ).toFixed(0)}% close factor · ${(
                  position.liquidation_bonus * 100
                ).toFixed(0)}% penalty`}
              />

              <Stat
                label="Mode"
                value={
                  preferences.mode === 'AUTONOMOUS'
                    ? 'Autonomous'
                    : 'Advisory'
                }
                mono={false}
                sub={`target ${preferences.target_health_factor.toFixed(
                  2,
                )} · acts below ${preferences.trigger_health_factor.toFixed(
                  2,
                )}`}
              />

            </div>
          </Panel>

          {/* =====================================================
              SMART PROTECTION SUGGESTION
          ====================================================== */}
          {suggestion && (
            <Panel title="Protection recommendation">

              <div
                className={`rounded-md border px-4 py-4 ${
                  suggestion.tone === 'danger'
                    ? 'border-danger/40 bg-danger/10'
                    : suggestion.tone === 'warn'
                      ? 'border-warn/40 bg-warn/10'
                      : 'border-safe/40 bg-safe/10'
                }`}
              >

                <div className="flex items-start gap-3">

                  <span
                    className="text-xl"
                    aria-hidden="true"
                  >
                    {suggestion.icon}
                  </span>

                  <div className="flex-1">

                    <p className="font-display text-sm text-ink">
                      {suggestion.title}
                    </p>

                    <p className="mt-1 text-sm leading-6 text-muted">
                      {suggestion.message}
                    </p>

                    <p className="mt-4 text-xs uppercase tracking-wider text-muted">
                      Suggested actions
                    </p>

                    <div className="mt-2 space-y-2">

                      {suggestion.actions.map(
                        (action, index) => (
                          <div
                            key={index}
                            className="flex items-start gap-2 text-sm text-muted"
                          >
                            <span className="text-ink">
                              •
                            </span>

                            <span>
                              {action}
                            </span>
                          </div>
                        ),
                      )}

                    </div>

                    {/* =================================================
                        FUTURE SCENARIO SUMMARY
                    ================================================== */}
                    {scenarioSummary && (
                      <div className="mt-4 rounded-md border border-hairline bg-panel-raised px-3 py-3">

                        <p className="text-xs uppercase tracking-wider text-muted">
                          Future risk
                        </p>

                        <p className="mt-1 text-sm text-ink">
                          {breakingScenario
                            ? `${breakingScenario.label} scenario may push the position toward liquidation.`
                            : scenarioSummary}
                        </p>

                        <Link
                          to="/portal/scenarios"
                          className="mt-2 inline-block text-sm text-ink underline underline-offset-2"
                        >
                          View future predictions →
                        </Link>

                      </div>
                    )}

                  </div>

                </div>

              </div>

            </Panel>
          )}

          {/* =====================================================
              AGENT DECISION
          ====================================================== */}
          <Panel
            title="Agent decision"
            actions={
              demoRunning && (
                <Working label="Cycle running" />
              )
            }
          >

            {/* ===================================================
                EXECUTED RESCUE
            ==================================================== */}
            {lastRescue && !lastRescue.executed ? (

              /* =================================================
                 EXECUTION ATTEMPTED, NOTHING RAN
              ================================================== */
              <div className="flex items-start gap-2.5 rounded-md border border-warn/40 bg-warn/10 px-3.5 py-3">
                <CircleSlash size={18} className="mt-0.5 shrink-0 text-warn" aria-hidden="true" />
                <div>
                  <p className="font-display text-sm text-warn">
                    No protection executed — no viable strategy.
                  </p>
                  <p className="mt-0.5 text-sm text-muted">{lastRescue.explanation}</p>
                </div>
              </div>

            ) : lastRescue?.executed ? (

              <div className="flex flex-col gap-3">

                <div className="flex items-start gap-2.5 rounded-md border border-safe/40 bg-safe/10 px-3.5 py-3">

                  <CheckCircle2
                    size={18}
                    className="mt-0.5 shrink-0 text-safe"
                    aria-hidden="true"
                  />

                  <div>

                    <p className="font-display text-sm text-safe">
                      Position protected
                    </p>

                    <p className="mt-0.5 text-sm text-muted">

                      {lastRescue.selected_strategy.name}
                      {' '}executed. Health Factor{' '}

                      <span className="tabular text-ink">
                        {fmtHF(
                          lastRescue.assessment_before
                            .health_factor,
                        )}
                      </span>

                      {' '}→{' '}

                      <span className="tabular text-safe">
                        {fmtHF(
                          lastRescue.assessment_after
                            .health_factor,
                        )}
                      </span>

                      {' '}at a cost of{' '}

                      <span className="tabular text-ink">
                        {fmtUsd(
                          lastRescue.selected_strategy
                            .total_cost,
                        )}
                      </span>.

                    </p>

                  </div>

                </div>

                {/* Receipt. Every field is the backend's; nothing here is
                    computed or assumed in the browser. */}
                <dl className="grid grid-cols-2 gap-x-4 gap-y-2 rounded-md border border-hairline bg-panel-raised px-3.5 py-3 text-xs sm:grid-cols-3">
                  {[
                    ['Strategy', lastRescue.transaction.strategy_name],
                    ['Action', lastRescue.transaction.action],
                    ['Amount', fmtUsd(lastRescue.transaction.action_amount)],
                    ['Previous HF', fmtHF(lastRescue.transaction.health_factor_before)],
                    ['Resulting HF', fmtHF(lastRescue.transaction.health_factor_after)],
                    [
                      'Risk',
                      `${lastRescue.transaction.risk_before} → ${lastRescue.transaction.risk_after}`,
                    ],
                  ].map(([label, value]) => (
                    <div key={label}>
                      <dt className="font-display text-[9px] tracking-[0.16em] text-muted uppercase">
                        {label}
                      </dt>
                      <dd className="tabular mt-0.5 text-ink">{value}</dd>
                    </div>
                  ))}
                </dl>

                <div className="rounded-md border border-warn/40 bg-warn/10 px-3.5 py-2.5">
                  <p className="font-display text-[11px] tracking-[0.14em] text-warn uppercase">
                    Simulated transaction &middot; No real funds were moved
                  </p>
                  <p className="tabular mt-1 text-xs break-all text-muted">
                    Status:{' '}
                    <span className="text-ink">{lastRescue.transaction.status_label}</span>
                    {' · '}
                    Transaction ID:{' '}
                    <span className="text-ink">{lastRescue.transaction.tx_hash}</span>
                  </p>
                </div>

                <p className="text-xs text-muted">
                  <Link to="/portal/history" className="text-ink underline underline-offset-2">
                    View in Rescue History
                  </Link>
                </p>

              </div>

            ) : stoodDown ? (

              /* =================================================
                 STAND DOWN
              ================================================== */
              <div className="flex items-start gap-2.5 rounded-md border border-danger/40 bg-danger/10 px-3.5 py-3">

                <CircleSlash
                  size={18}
                  className="mt-0.5 shrink-0 text-danger"
                  aria-hidden="true"
                />

                <div>

                  <p className="font-display text-sm text-danger">
                    {EXECUTION_LABEL[
                      validation.execution_status
                    ]}
                  </p>

                  <p className="mt-0.5 text-sm text-muted">
                    {validation.reason}
                  </p>

                </div>

              </div>

            ) : advisoryHold ? (

              /* =================================================
                 ADVISORY MODE
              ================================================== */
              <div className="flex flex-col gap-3">

                <div className="flex items-start gap-2.5 rounded-md border border-warn/40 bg-warn/10 px-3.5 py-3">

                  <Info
                    size={18}
                    className="mt-0.5 shrink-0 text-warn"
                    aria-hidden="true"
                  />

                  <div>

                    <p className="font-display text-sm text-warn">
                      Recommendation ready
                    </p>

                    <p className="mt-0.5 text-sm text-muted">
                      {explanation}
                    </p>

                  </div>

                </div>

                <div className="flex flex-wrap gap-2">

                  <Button
                    variant="primary"
                    onClick={() =>
                      executeRescue({
                        confirm: true,
                      })
                    }
                    disabled={busy}
                  >

                    {busy ? (
                      <>
                        <Loader2
                          size={14}
                          className="animate-spin"
                          aria-hidden="true"
                        />
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
                    Review the comparison
                    <ArrowRight
                      size={14}
                      aria-hidden="true"
                    />
                  </Link>

                </div>

              </div>

            ) : assessment.requires_action ? (

              /* =================================================
                 ACTION REQUIRED
              ================================================== */
              <div className="flex flex-col gap-3">

                <p className="text-sm text-muted">
                  {explanation}
                </p>

                <Button
                  variant="primary"
                  onClick={() => executeRescue()}
                  disabled={busy}
                >

                  {busy ? (
                    <>
                      <Loader2
                        size={14}
                        className="animate-spin"
                        aria-hidden="true"
                      />
                      Executing…
                    </>
                  ) : (
                    'Execute now (simulated)'
                  )}

                </Button>

              </div>

            ) : (

              /* =================================================
                 NO RESCUE REQUIRED
              ================================================== */
              <div className="flex flex-col gap-3">

                <p className="text-sm text-muted">

                  No rescue required. The agent is holding at{' '}

                  <span className="tabular text-ink">
                    {fmtHF(
                      assessment.health_factor,
                    )}
                  </span>

                  {' '}and will intervene below{' '}

                  <span className="tabular text-ink">
                    {preferences.trigger_health_factor.toFixed(
                      2,
                    )}
                  </span>.

                </p>

                <p className="text-sm text-muted">

                  {breakingScenario
                    ? `A ${breakingScenario.label} move would liquidate this position.`
                    : scenarioSummary}{' '}

                  <Link
                    to="/portal/scenarios"
                    className="text-ink underline underline-offset-2"
                  >
                    See the projections
                  </Link>.

                </p>

                {/* The agent will not act above the trigger, but the options
                    are real and a cautious user may want the buffer rebuilt
                    now. Executing here is opt-in, never automatic. */}
                {viableCount > 0 && (
                  <div className="flex flex-col gap-2 border-t border-hairline pt-3">
                    <p className="text-xs text-muted">
                      {viableCount} protection option{viableCount === 1 ? '' : 's'} available
                      if you would rather rebuild the buffer now.
                    </p>
                    <label className="flex flex-col gap-1">
                      <span className="font-display text-[10px] tracking-[0.14em] text-muted uppercase">
                        Strategy
                      </span>
                      <select
                        value={chosenStrategy}
                        onChange={(e) => setChosenStrategy(e.target.value)}
                        className="rounded-md border border-hairline bg-base px-3 py-2 font-display text-sm text-ink outline-none focus:border-safe"
                      >
                        <option value="">Let the agent choose</option>
                        {strategies
                          .filter((s) => s.is_executable ?? s.status === 'VIABLE')
                          .map((s) => (
                            <option key={s.strategy_type} value={s.strategy_type}>
                              {s.name}
                            </option>
                          ))}
                      </select>
                    </label>
                    <Button
                      variant="primary"
                      onClick={() =>
                        executeRescue({
                          confirm: true,
                          strategyType: chosenStrategy || null,
                        })
                      }
                      disabled={busy}
                    >
                      {busy ? (
                        <>
                          <Loader2 size={14} className="animate-spin" aria-hidden="true" />
                          Executing…
                        </>
                      ) : (
                        'Execute Protection (simulated)'
                      )}
                    </Button>
                  </div>
                )}

              </div>

            )}

          </Panel>

        </div>
      </div>

      {/* =========================================================
          DECISION TRACE
      ========================================================== */}
      <DecisionTrace />

    </div>
  )
}
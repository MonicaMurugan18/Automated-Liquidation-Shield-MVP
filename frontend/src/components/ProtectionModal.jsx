import { useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  CircleSlash,
  Coins,
  Layers,
  ShieldCheck,
  Repeat,
  X,
  Zap,
} from 'lucide-react'
import { useShield } from '../state/ShieldContext'
import { Badge, Button } from './ui'
import { TONE_HEX, fmtHF, fmtPrice, fmtUsd, fmtUsd0, riskTone } from '../lib/format'

/**
 * Protection panel, raised when the agent finds a position at real risk.
 *
 * Opens only when the backend classified the position DANGER or LIQUIDATABLE.
 * A WARNING position is handled inline on the dashboard -- interrupting
 * someone for a position that is merely below target would train them to
 * dismiss the thing without reading it, which is exactly what you do not want
 * from a liquidation alarm.
 *
 * Every figure here is a field of the cycle response. Nothing is computed in
 * this component, and the strategy list is whatever the Strategy Engine
 * generated for this specific position -- not a fixed menu.
 */

const STRATEGY_ICON = {
  REPAY_DEBT: Coins,
  ADD_COLLATERAL: Layers,
  COLLATERAL_SWAP: Repeat,
  FLASH_LOAN_DELEVERAGE: Zap,
  PARTIAL_DELEVERAGE: Coins,
}

/** Plain-language blurbs. Labels only -- every number comes from the engine. */
const STRATEGY_BLURB = {
  REPAY_DEBT: 'Reduce outstanding debt to improve the Health Factor.',
  ADD_COLLATERAL: 'Increase collateral to create a larger safety buffer.',
  COLLATERAL_SWAP: 'Sell part of the collateral and repay — no new capital needed.',
  FLASH_LOAN_DELEVERAGE: 'Use simulated liquidity to restore the position atomically.',
  PARTIAL_DELEVERAGE: 'A minimal repayment, evaluated as a low-cost baseline.',
}

function Figure({ label, children, tone }) {
  return (
    <div>
      <p className="font-display text-[9px] tracking-[0.16em] text-muted uppercase">{label}</p>
      <p className="tabular mt-0.5 text-lg" style={tone ? { color: tone } : undefined}>
        {children}
      </p>
    </div>
  )
}

export default function ProtectionModal() {
  const {
    protectionAlert,
    dismissProtectionAlert,
    executeRescue,
    busy,
    collateralSpec,
  } = useShield()
  const closeRef = useRef(null)

  // Escape closes, and focus lands somewhere sensible when it opens.
  useEffect(() => {
    if (!protectionAlert) return undefined
    const onKey = (e) => {
      if (e.key === 'Escape') dismissProtectionAlert()
    }
    document.addEventListener('keydown', onKey)
    closeRef.current?.focus()
    return () => document.removeEventListener('keydown', onKey)
  }, [protectionAlert, dismissProtectionAlert])

  if (!protectionAlert) return null

  const {
    assessment_shocked: at_risk,
    assessment_final: final,
    selected_strategy: selected,
    strategies = [],
    economics,
    executed,
    execution_status: status,
    explanation,
    price_after: price,
    position_before: position,
  } = protectionAlert

  const viable = strategies.filter((s) => s.is_executable)
  const rejected = strategies.filter((s) => !s.is_executable)
  const stoodDown = !selected
  const awaiting = status === 'AWAITING_CONFIRMATION'
  const decimals = collateralSpec?.price_decimals

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-base/80 p-4 backdrop-blur-sm sm:items-center"
      role="presentation"
      onClick={(e) => e.target === e.currentTarget && dismissProtectionAlert()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="protection-modal-title"
        className="my-auto w-full max-w-2xl rounded-lg border border-danger/50 bg-panel shadow-2xl"
      >
        {/* --- header ------------------------------------------------------ */}
        <header className="flex items-start justify-between gap-3 border-b border-hairline px-5 py-4">
          <div className="flex items-start gap-3">
            <AlertTriangle size={22} className="mt-0.5 shrink-0 text-danger" aria-hidden="true" />
            <div>
              <h2
                id="protection-modal-title"
                className="font-display text-base font-semibold text-danger"
              >
                {stoodDown ? 'Protection stood down' : 'Protection required'}
              </h2>
              <p className="mt-0.5 text-sm text-muted">
                Your position may approach liquidation if {position?.collateral_asset ?? 'ETH'}{' '}
                continues to fall.
              </p>
            </div>
          </div>
          <button
            ref={closeRef}
            type="button"
            onClick={dismissProtectionAlert}
            aria-label="Close protection panel"
            className="shrink-0 rounded-md border border-hairline p-1.5 text-muted transition-colors hover:text-ink"
          >
            <X size={15} />
          </button>
        </header>

        <div className="flex flex-col gap-4 px-5 py-4">
          {/* --- the risk that was detected -------------------------------- */}
          <div className="grid grid-cols-2 gap-4 rounded-md border border-hairline bg-panel-raised px-4 py-3 sm:grid-cols-4">
            <Figure label="Health factor" tone={TONE_HEX[riskTone(at_risk.risk_level)]}>
              {fmtHF(at_risk.health_factor)}
            </Figure>
            <Figure label="Risk" tone={TONE_HEX[riskTone(at_risk.risk_level)]}>
              <span className="font-display text-sm">{at_risk.risk_level}</span>
            </Figure>
            <Figure label={`${position?.collateral_asset ?? 'ETH'} price`}>
              {fmtPrice(price, decimals)}
            </Figure>
            <Figure label="At risk">{fmtUsd0(at_risk.potential_liquidation_loss)}</Figure>
          </div>

          {/* --- stand-down, or the recommendation ------------------------- */}
          {stoodDown ? (
            <div className="flex items-start gap-2.5 rounded-md border border-danger/40 bg-danger/10 px-4 py-3">
              <CircleSlash size={18} className="mt-0.5 shrink-0 text-danger" aria-hidden="true" />
              <div>
                <p className="font-display text-sm text-danger">No rescue was executed</p>
                <p className="mt-0.5 text-sm text-muted">{explanation}</p>
              </div>
            </div>
          ) : (
            <section className="rounded-md border border-safe/40 bg-safe/10 px-4 py-3.5">
              <div className="flex flex-wrap items-center gap-2">
                <ShieldCheck size={16} className="text-safe" aria-hidden="true" />
                <p className="font-display text-[10px] tracking-[0.16em] text-safe uppercase">
                  Autonomous recommendation
                </p>
                <Badge tone="safe">{selected.score_100}/100</Badge>
              </div>

              <p className="mt-1.5 font-display text-lg text-ink">{selected.name}</p>

              <div className="mt-3 grid grid-cols-2 gap-4 sm:grid-cols-4">
                <Figure label="Amount">{fmtUsd0(selected.action_amount)}</Figure>
                <Figure label="Expected HF" tone={TONE_HEX.safe}>
                  {fmtHF(selected.resulting_health_factor)}
                </Figure>
                <Figure label="Estimated cost">{fmtUsd(selected.total_cost)}</Figure>
                <Figure
                  label="Risk after"
                  tone={TONE_HEX[riskTone(selected.resulting_risk_level)]}
                >
                  <span className="font-display text-sm">{selected.resulting_risk_level}</span>
                </Figure>
              </div>

              <p className="mt-3 border-t border-safe/20 pt-2.5 text-xs leading-relaxed text-muted">
                <span className="font-display text-[10px] tracking-[0.14em] text-muted uppercase">
                  Why
                </span>
                <br />
                {explanation}
              </p>

              {economics && (
                <dl className="mt-2.5 flex flex-wrap gap-x-5 gap-y-1 text-xs">
                  <div className="flex gap-1.5">
                    <dt className="text-muted">Rescue cost</dt>
                    <dd className="tabular text-ink">{fmtUsd(economics.rescue_cost)}</dd>
                  </div>
                  <div className="flex gap-1.5">
                    <dt className="text-muted">Loss avoided</dt>
                    <dd className="tabular text-ink">{fmtUsd(economics.potential_loss)}</dd>
                  </div>
                  <div className="flex gap-1.5">
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
            </section>
          )}

          {/* --- the candidates the engine actually generated --------------- */}
          {viable.length > 0 && (
            <section className="flex flex-col gap-2">
              <p className="font-display text-[10px] tracking-[0.16em] text-muted uppercase">
                Feasible protection strategies · {viable.length} of {strategies.length}
              </p>
              <ul className="flex flex-col gap-1.5">
                {viable.map((s) => {
                  const Icon = STRATEGY_ICON[s.strategy_type] ?? ShieldCheck
                  return (
                    <li
                      key={s.strategy_type}
                      className={`flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border px-3 py-2 text-sm ${
                        s.selected ? 'border-safe/50 bg-safe/5' : 'border-hairline'
                      }`}
                    >
                      <Icon
                        size={15}
                        className={s.selected ? 'shrink-0 text-safe' : 'shrink-0 text-muted'}
                        aria-hidden="true"
                      />
                      <span className="text-ink">{s.name}</span>
                      {s.selected && <Badge tone="safe">selected</Badge>}
                      <span className="text-xs text-muted">
                        {STRATEGY_BLURB[s.strategy_type]}
                      </span>
                      <span className="tabular ml-auto text-xs text-muted">
                        HF {fmtHF(s.resulting_health_factor)} · {fmtUsd(s.total_cost)} ·{' '}
                        <span className="text-ink">{s.score_100}/100</span>
                      </span>
                    </li>
                  )
                })}
              </ul>
              {rejected.length > 0 && (
                <p className="text-xs text-muted">
                  {rejected.length} further{' '}
                  {rejected.length === 1 ? 'candidate was' : 'candidates were'} generated and
                  rejected — see the comparison for the reasons.
                </p>
              )}
            </section>
          )}

          {/* --- outcome --------------------------------------------------- */}
          {executed && final && (
            <div className="flex items-start gap-2.5 rounded-md border border-safe/40 bg-safe/10 px-4 py-3">
              <CheckCircle2 size={18} className="mt-0.5 shrink-0 text-safe" aria-hidden="true" />
              <p className="text-sm text-muted">
                <span className="font-display text-safe">Position protected.</span> Simulated
                execution complete — Health Factor{' '}
                <span className="tabular text-ink">{fmtHF(at_risk.health_factor)}</span> →{' '}
                <span className="tabular text-safe">{fmtHF(final.health_factor)}</span> (
                {final.risk_level}). No real transaction was signed or broadcast.
              </p>
            </div>
          )}
        </div>

        {/* --- actions ------------------------------------------------------ */}
        <footer className="flex flex-wrap items-center gap-2 border-t border-hairline px-5 py-3.5">
          <Link
            to="/portal/comparison"
            onClick={dismissProtectionAlert}
            className="inline-flex items-center gap-1.5 rounded-md border border-hairline bg-panel-raised px-3.5 py-2 font-display text-sm text-ink transition-colors hover:border-muted"
          >
            View all strategies
            <ArrowRight size={14} aria-hidden="true" />
          </Link>

          {awaiting && (
            <Button
              variant="primary"
              disabled={busy}
              onClick={async () => {
                await executeRescue({ confirm: true })
                dismissProtectionAlert()
              }}
            >
              <ShieldCheck size={14} aria-hidden="true" />
              Protect position
            </Button>
          )}

          <Button variant="ghost" onClick={dismissProtectionAlert} className="ml-auto">
            {executed || stoodDown ? 'Close' : 'Dismiss'}
          </Button>
        </footer>
      </div>
    </div>
  )
}

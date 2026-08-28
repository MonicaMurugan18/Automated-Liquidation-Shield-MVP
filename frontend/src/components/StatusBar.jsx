import { useShield } from '../state/ShieldContext'
import { fmtPrice } from '../lib/format'
import { shieldState as lookupState } from '../lib/shieldStates'

/**
 * Persistent agent status bar.
 *
 * Its job is to make one thing unmistakable: this is a process that is
 * running, not a report you opened. It is pinned above every page and reads
 * the same state machine the backend returns.
 */

const DOT = { safe: 'bg-safe', warn: 'bg-warn', danger: 'bg-danger' }
const TEXT = { safe: 'text-safe', warn: 'text-warn', danger: 'text-danger' }

export default function StatusBar() {
  const { shieldState, position, preferences, assessment, persistence, busy, activity, collateralSpec } =
    useShield()
  const state = lookupState(shieldState)
  const { Icon } = state

  return (
    <div
      className="sticky top-0 z-30 border-b border-hairline bg-panel/95 backdrop-blur"
      role="status"
      aria-live="polite"
    >
      <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-6 gap-y-2 px-4 py-2.5 sm:px-6">
        <div className="flex items-center gap-2.5">
          <span
            className={`h-2 w-2 shrink-0 rounded-full ${DOT[state.tone]} ${
              state.pulse ? 'animate-shield-pulse' : ''
            }`}
            aria-hidden="true"
          />
          <Icon size={16} className={TEXT[state.tone]} aria-hidden="true" />
          <span
            className={`font-display text-sm font-semibold tracking-[0.18em] ${TEXT[state.tone]}`}
          >
            {state.label}
          </span>
        </div>

        <p className="hidden flex-1 items-center gap-2 text-xs text-muted lg:flex">
          {busy && activity ? (
            <>
              <span
                className="h-1.5 w-1.5 animate-shield-pulse rounded-full bg-warn"
                aria-hidden="true"
              />
              <span className="text-ink">{activity}…</span>
            </>
          ) : (
            state.caption
          )}
        </p>

        <dl className="ml-auto flex flex-wrap items-center gap-x-5 gap-y-1 text-xs">
          <div className="flex items-center gap-1.5">
            <dt className="text-muted">{position?.collateral_asset ?? "ASSET"}</dt>
            <dd className="tabular text-ink">
              {fmtPrice(position?.collateral_price, collateralSpec?.price_decimals)}
            </dd>
          </div>
          <div className="flex items-center gap-1.5">
            <dt className="text-muted">HF</dt>
            <dd className="tabular text-ink">
              {assessment?.health_factor?.toFixed(3) ?? '--'}
            </dd>
          </div>
          <div className="flex items-center gap-1.5">
            <dt className="text-muted">MODE</dt>
            <dd className="font-display text-ink">
              {preferences?.mode === 'ADVISORY' ? 'Advisory' : 'Autonomous'}
            </dd>
          </div>
          <div className="hidden items-center gap-1.5 sm:flex">
            <dt className="text-muted">STORE</dt>
            <dd className="font-display text-muted">{persistence}</dd>
          </div>
        </dl>
      </div>
    </div>
  )
}

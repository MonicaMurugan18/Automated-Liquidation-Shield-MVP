import { AlertTriangle, Loader2, RadioTower, RefreshCw } from 'lucide-react'
import { useShield } from '../state/ShieldContext'
import { Badge, Button, Panel } from './ui'
import { fmtPrice } from '../lib/format'

/**
 * Live ETH/USD readout.
 *
 * The one panel on the dashboard showing REAL data. Everything else on screen
 * is derived from it by simulation, so this panel is deliberately explicit
 * about which it is: a live price is labelled as live with its source and the
 * moment it was read, and a failed fetch says so plainly rather than quietly
 * showing a stale or invented number.
 */

function relativeTime(iso, ageSeconds) {
  if (typeof ageSeconds === 'number' && ageSeconds < 60) {
    return ageSeconds < 5 ? 'just now' : `${Math.round(ageSeconds)}s ago`
  }
  if (!iso) return '—'
  const then = new Date(iso)
  if (Number.isNaN(then.getTime())) return '—'
  const seconds = Math.max(0, (Date.now() - then.getTime()) / 1000)
  if (seconds < 60) return `${Math.round(seconds)}s ago`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`
  return then.toLocaleTimeString('en-US', { hour12: false })
}

export default function MarketPanel() {
  const { livePrice, marketStatus, marketError, fetchLivePrice, position, busy } = useShield()

  const loading = marketStatus === 'loading'
  const live = marketStatus === 'live' && livePrice
  const usingLive =
    live && position && Math.abs(position.collateral_price - livePrice.price) < 0.01

  return (
    <Panel
      title="Market data"
      actions={
        <Button
          variant="default"
          onClick={() => fetchLivePrice({ force: true })}
          disabled={loading || busy}
          aria-label="Refresh ETH price"
        >
          {loading ? (
            <Loader2 size={14} className="animate-spin" aria-hidden="true" />
          ) : (
            <RefreshCw size={14} aria-hidden="true" />
          )}
          Refresh ETH price
        </Button>
      }
    >
      {live ? (
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="font-display text-[10px] tracking-[0.16em] text-muted uppercase">
                {livePrice.asset}/{livePrice.currency}
              </p>
              <p className="tabular mt-0.5 text-3xl text-ink">{fmtPrice(livePrice.price, 2)}</p>
            </div>
            <Badge tone="safe">
              <RadioTower size={11} aria-hidden="true" />
              Live market data
            </Badge>
          </div>

          <dl className="grid grid-cols-2 gap-3 border-t border-hairline pt-3 text-xs sm:grid-cols-3">
            <div>
              <dt className="text-muted">Source</dt>
              <dd className="mt-0.5 text-ink">{livePrice.source}</dd>
            </div>
            <div>
              <dt className="text-muted">Updated</dt>
              <dd className="tabular mt-0.5 text-ink">
                {relativeTime(livePrice.timestamp, livePrice.age_seconds)}
              </dd>
            </div>
            <div>
              <dt className="text-muted">Applied to position</dt>
              <dd className={`mt-0.5 ${usingLive ? 'text-safe' : 'text-warn'}`}>
                {usingLive ? 'Yes' : 'No — using entered price'}
              </dd>
            </div>
          </dl>

          <p className="text-xs leading-relaxed text-muted">
            <span className="text-ink">Real:</span> this spot price and its timestamp.{' '}
            <span className="text-ink">Simulated:</span> every price derived from it, the
            projected Health Factors, the strategies and the rescue.
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <div className="flex items-start gap-2.5 rounded-md border border-warn/40 bg-warn/10 px-3.5 py-3">
            {loading ? (
              <Loader2 size={18} className="mt-0.5 shrink-0 animate-spin text-warn" aria-hidden="true" />
            ) : (
              <AlertTriangle size={18} className="mt-0.5 shrink-0 text-warn" aria-hidden="true" />
            )}
            <div>
              <p className="font-display text-sm text-warn">
                {loading ? 'Fetching live market data…' : 'Live market data unavailable.'}
              </p>
              {!loading && (
                <p className="mt-0.5 text-sm text-muted">
                  Every provider failed. You can carry on with a manually entered price — the
                  risk, scenario and strategy engines work exactly the same either way.
                </p>
              )}
            </div>
          </div>

          {!loading && (
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="warn">Demo / manual price</Badge>
              <span className="tabular text-sm text-ink">
                {fmtPrice(position?.collateral_price, 2)}
              </span>
              <span className="text-xs text-muted">in use for this position</span>
            </div>
          )}

          {marketError && !loading && (
            <p className="text-xs break-words text-muted">{marketError}</p>
          )}
        </div>
      )}
    </Panel>
  )
}

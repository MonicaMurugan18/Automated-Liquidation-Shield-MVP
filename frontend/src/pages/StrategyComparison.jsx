import { ShieldCheck } from 'lucide-react'
import { useShield } from '../state/ShieldContext'
import { Badge, EmptyState, Panel } from '../components/ui'
import {
  STATUS_LABEL_SHORT,
  TONE_HEX,
  fmtHF,
  fmtPct,
  fmtUsd,
  fmtUsd0,
  hfTone,
  statusTone,
} from '../lib/format'

/**
 * Page 5: the comparison matrix -- differentiator #3's transparency layer.
 *
 * This view explains a decision the agent has already made. It is not a menu:
 * nothing here is clickable, because by the time you read it in Autonomous
 * mode the rescue has run.
 */

const COLUMNS = [
  { key: 'name', label: 'Strategy', align: 'left' },
  { key: 'resulting_health_factor', label: 'Resulting HF' },
  { key: 'safety', label: 'Safety' },
  { key: 'required_capital', label: 'Capital' },
  { key: 'slippage_pct', label: 'Slippage' },
  { key: 'liquidity', label: 'Liquidity' },
  { key: 'gas_cost', label: 'Gas' },
  { key: 'flash_loan_fee', label: 'Flash fee' },
  { key: 'total_cost', label: 'Total cost' },
  { key: 'score', label: 'Score /100' },
  { key: 'status', label: 'Status', align: 'left' },
]

export default function StrategyComparison() {
  const {
    strategies: liveStrategies,
    explanation: liveExplanation,
    selectedStrategy: liveSelected,
    weights,
    bands,
    assessment,
    lastCycle,
  } = useShield()

  // See ProtectionSuggestions: the comparison exists to audit a decision that
  // has already been made, so it outlives the risk that prompted it.
  const reviewing = liveStrategies.length === 0 && Boolean(lastCycle)
  const strategies = reviewing ? lastCycle.strategies : liveStrategies
  const explanation = reviewing ? lastCycle.explanation : liveExplanation
  const selectedStrategy = reviewing ? lastCycle.selected : liveSelected

  if (!strategies.length) {
    return (
      <Panel title="Strategy comparison">
        <EmptyState icon={ShieldCheck} title="Nothing to compare">
          The agent only builds a comparison when a position needs rescuing. Current Health
          Factor is {fmtHF(assessment?.health_factor)}.
        </EmptyState>
      </Panel>
    )
  }

  const cell = (row, key) => {
    switch (key) {
      case 'name':
        return (
          <div className="flex items-center gap-2">
            <span className="text-ink">{row.name}</span>
            {row.selected && (
              <Badge tone="safe">
                <ShieldCheck size={11} aria-hidden="true" /> selected
              </Badge>
            )}
          </div>
        )
      case 'resulting_health_factor':
        return (
          <span
            style={{
              color:
                row.status === 'VIABLE'
                  ? TONE_HEX[hfTone(row.resulting_health_factor, bands)]
                  : '#7C8798',
            }}
          >
            {row.resulting_health_factor > 0 ? fmtHF(row.resulting_health_factor) : '—'}
          </span>
        )
      case 'safety':
      case 'liquidity':
        return row.score_breakdown?.[key] != null
          ? (row.score_breakdown[key] * 100).toFixed(0)
          : '—'
      case 'required_capital':
        return row.required_capital > 0 ? fmtUsd0(row.required_capital) : '—'
      case 'slippage_pct':
        return row.slippage_pct > 0 ? fmtPct(row.slippage_pct) : '—'
      case 'gas_cost':
        return fmtUsd(row.gas_cost)
      case 'flash_loan_fee':
        return row.flash_loan_fee > 0 ? fmtUsd(row.flash_loan_fee) : '—'
      case 'total_cost':
        return fmtUsd(row.total_cost)
      case 'score':
        return (
          <span className={row.selected ? 'text-safe' : row.score > 0 ? 'text-ink' : 'text-muted'}>
            {row.score_100}<span className="text-muted">/100</span>
          </span>
        )
      case 'status':
        return <Badge tone={statusTone(row.status)}>{STATUS_LABEL_SHORT[row.status] ?? row.status}</Badge>
      default:
        return '—'
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <Panel
        title="Auto-selection"
        subtitle={
          reviewing
            ? "Why the agent chose what it chose, on the last completed cycle."
            : "Why the agent chose what it chose."
        }
      >
        <p className="text-sm text-ink">{explanation}</p>
        {selectedStrategy && (
          <p className="mt-2 text-sm text-muted">{selectedStrategy.description}</p>
        )}
      </Panel>

      <Panel
        title="Comparison matrix"
        subtitle="Every candidate across every scored dimension. Safety and liquidity are shown as sub-scores out of 100."
      >
        <div className="-mx-4 overflow-x-auto px-4">
          <table className="w-full min-w-[1000px] border-collapse text-sm">
            <caption className="sr-only">
              Candidate protection strategies compared on safety, cost, slippage, liquidity and
              required capital, with the composite score used for auto-selection.
            </caption>
            <thead>
              <tr className="border-b border-hairline">
                {COLUMNS.map((col) => (
                  <th
                    key={col.key}
                    scope="col"
                    className={`px-2 py-2 font-display text-[10px] tracking-[0.14em] text-muted uppercase ${
                      col.align === 'left' ? 'text-left' : 'text-right'
                    }`}
                  >
                    {col.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {strategies.map((row) => (
                <tr
                  key={row.strategy_type}
                  className={`border-b border-hairline/60 ${
                    row.selected ? 'bg-safe/5' : row.status !== 'VIABLE' ? 'opacity-70' : ''
                  }`}
                >
                  {COLUMNS.map((col) => (
                    <td
                      key={col.key}
                      className={`px-2 py-2.5 ${
                        col.align === 'left' ? 'text-left' : 'tabular text-right'
                      }`}
                    >
                      {cell(row, col.key)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="mt-4 flex flex-col gap-2 border-t border-hairline pt-3">
          <p className="font-display text-[10px] tracking-[0.14em] text-muted uppercase">
            Composite weights
          </p>
          <ul className="flex flex-wrap gap-x-5 gap-y-1 text-xs">
            {Object.entries(weights).map(([key, value]) => (
              <li key={key} className="flex gap-1.5">
                <span className="text-muted capitalize">{key}</span>
                <span className="tabular text-ink">{(value * 100).toFixed(0)}%</span>
              </li>
            ))}
          </ul>
          <p className="text-xs text-muted">
            Change these on the Settings page and the selection changes with them — the ranking
            is computed, not hard-coded.
          </p>
        </div>
      </Panel>

      <Panel title="Rejected candidates">
        <ul className="flex flex-col gap-2">
          {strategies
            .filter((row) => row.status !== 'VIABLE')
            .map((row) => (
              <li key={row.strategy_type} className="flex flex-wrap items-baseline gap-2 text-sm">
                <span className="text-ink">{row.name}</span>
                <Badge tone={statusTone(row.status)}>{STATUS_LABEL_SHORT[row.status]}</Badge>
                <span className="text-muted">{row.rejection_reason}</span>
              </li>
            ))}
          {strategies.every((row) => row.status === 'VIABLE') && (
            <li className="text-sm text-muted">
              Every candidate cleared every constraint on this run.
            </li>
          )}
        </ul>
      </Panel>
    </div>
  )
}

import { History as HistoryIcon } from 'lucide-react'
import { useShield } from '../state/ShieldContext'
import { Badge, EmptyState, Panel } from '../components/ui'
import { TONE_HEX, fmtDateTime, fmtHF, fmtUsd, fmtUsd0, shortHash } from '../lib/format'

/** Page 6: every rescue the agent has executed. All simulated. */
export default function RescueHistory() {
  const { history, persistence } = useShield()

  return (
    <Panel
      title="Rescue history"
      subtitle={
        persistence === 'supabase'
          ? 'Persisted to Supabase.'
          : 'In-memory store — configure Supabase credentials to persist across restarts.'
      }
      actions={<Badge tone="muted">{history.length} executed</Badge>}
    >
      {history.length === 0 ? (
        <EmptyState icon={HistoryIcon} title="No rescues yet">
          Run Demo Mode to trigger an autonomous rescue. Skipped and stood-down decisions are
          not recorded here — only executions are.
        </EmptyState>
      ) : (
        <div className="-mx-4 overflow-x-auto px-4">
          <table className="w-full min-w-[900px] border-collapse text-sm">
            <thead>
              <tr className="border-b border-hairline text-left">
                {['Time', 'Strategy', 'Mode', 'Amount', 'Cost', 'HF before → after', 'Transaction'].map(
                  (h) => (
                    <th
                      key={h}
                      scope="col"
                      className="px-2 py-2 font-display text-[10px] tracking-[0.14em] text-muted uppercase"
                    >
                      {h}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {history.map((tx) => (
                <tr key={tx.id ?? tx.tx_hash} className="border-b border-hairline/60">
                  <td className="tabular px-2 py-2.5 text-muted">
                    {fmtDateTime(tx.executed_at ?? tx.created_at)}
                  </td>
                  <td className="px-2 py-2.5 text-ink">{tx.strategy_name}</td>
                  <td className="px-2 py-2.5">
                    <Badge tone={tx.mode === 'AUTONOMOUS' ? 'safe' : 'warn'}>
                      {tx.mode === 'AUTONOMOUS' ? 'Autonomous' : 'Advisory'}
                    </Badge>
                  </td>
                  <td className="tabular px-2 py-2.5 text-muted">{fmtUsd0(tx.action_amount)}</td>
                  <td className="tabular px-2 py-2.5 text-muted">{fmtUsd(tx.total_cost)}</td>
                  <td className="tabular px-2 py-2.5">
                    <span style={{ color: TONE_HEX.danger }}>
                      {fmtHF(tx.health_factor_before)}
                    </span>
                    <span className="text-muted"> → </span>
                    <span style={{ color: TONE_HEX.safe }}>{fmtHF(tx.health_factor_after)}</span>
                  </td>
                  <td className="px-2 py-2.5">
                    <div className="flex items-center gap-2">
                      <span className="tabular text-muted">{shortHash(tx.tx_hash)}</span>
                      <Badge tone="muted">simulated</Badge>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  )
}

import { ShieldCheck } from 'lucide-react'
import { useShield } from '../state/ShieldContext'
import { Badge, Button, EmptyState, Panel, RiskBadge } from '../components/ui'
import { fmtHF, fmtUsd, riskTone } from '../lib/format'

export default function ProtectionSuggestions() {
  const {
    assessment,
    validation,
    strategies,
    selectedStrategy,
    executeRescue,
    busy,
    scenarios,
  } = useShield()

  if (!assessment || !validation) return null

  const viable = strategies.filter((strategy) => strategy.status === 'VIABLE')
  const guidance = validation.guidance

  return (
    <div className="flex flex-col gap-5">
      <Panel title="Protection suggestions" subtitle="Recommendations generated and validated by the backend.">
        <div className="flex flex-wrap items-center gap-3">
          <RiskBadge level={assessment.risk_level} />
          <span className="tabular text-sm text-muted">HF {fmtHF(assessment.health_factor)}</span>
          {selectedStrategy && <Badge tone="safe">{selectedStrategy.name}</Badge>}
        </div>
        <p className="mt-3 text-sm text-muted">{guidance?.summary ?? validation.reason}</p>

        {guidance?.suggestions?.length > 0 && (
          <ul className="mt-4 flex flex-col gap-2 border-t border-hairline pt-3">
            {guidance.suggestions.map((suggestion) => (
              <li key={`${suggestion.kind}-${suggestion.title}`} className="flex gap-2 text-sm text-muted">
                <ShieldCheck size={15} className="mt-0.5 shrink-0 text-safe" aria-hidden="true" />
                <span><span className="text-ink">{suggestion.title}:</span> {suggestion.detail}</span>
              </li>
            ))}
          </ul>
        )}

        {selectedStrategy && validation.can_execute && (
          <Button
            className="mt-4"
            variant="primary"
            disabled={busy}
            onClick={() => executeRescue({ confirm: true })}
          >
            Execute {selectedStrategy.name} (simulated)
          </Button>
        )}

        {!validation.can_execute && (
          <div className="mt-4 rounded-md border border-danger/40 bg-danger/10 px-3 py-3 text-sm text-muted">
            <span className="text-danger">No protection action executed.</span>{' '}
            {validation.reason}
          </div>
        )}
      </Panel>

      <Panel title="Generated strategies" subtitle={`${viable.length} viable of ${strategies.length} generated.`}>
        {strategies.length === 0 ? (
          <EmptyState title="No strategy required">The backend reports that the current position does not need rescuing.</EmptyState>
        ) : (
          <ul className="flex flex-col gap-2">
            {strategies.map((strategy) => (
              <li key={strategy.strategy_type} className="flex flex-wrap items-center gap-3 rounded-md border border-hairline px-3 py-2.5">
                <span className="text-sm text-ink">{strategy.name}</span>
                <Badge tone={riskTone(strategy.status === 'VIABLE' ? strategy.resulting_risk_level : 'DANGER')}>
                  {strategy.status}
                </Badge>
                <span className="text-xs text-muted">{strategy.status === 'VIABLE' ? `HF ${fmtHF(strategy.resulting_health_factor)} · ${fmtUsd(strategy.total_cost)}` : strategy.rejection_reason}</span>
                {strategy.selected && <Badge tone="safe">backend selected</Badge>}
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel title="Simulated future risk" subtitle="Stress-test outputs from the backend, not predictions.">
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
          {scenarios.map((scenario) => (
            <div key={scenario.label} className="rounded-md border border-hairline bg-panel-raised px-3 py-3">
              <p className="font-display text-xs text-muted">{scenario.label}</p>
              <p className="tabular mt-2 text-lg text-ink">{fmtHF(scenario.health_factor)}</p>
              <p className="mt-1 text-xs text-muted">{scenario.risk_level}</p>
              <p className="mt-2 text-xs text-muted">{scenario.intervention_summary}</p>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  )
}

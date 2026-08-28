import { Check, Loader2, Minus } from 'lucide-react'
import { useShield } from '../state/ShieldContext'
import { deriveSteps } from '../lib/workflow'

/** The eight-step progress rail, read from the backend's trace. */

const DOT = {
  done: 'border-safe bg-safe/20 text-safe',
  active: 'border-warn bg-warn/20 text-warn',
  skipped: 'border-hairline bg-panel-raised text-muted',
  pending: 'border-hairline bg-panel-raised text-muted',
}

const LABEL = {
  done: 'text-ink',
  active: 'text-warn',
  skipped: 'text-muted line-through decoration-hairline',
  pending: 'text-muted',
}

export default function StepIndicator() {
  const { traceSteps, analysing, decisionTrace } = useShield()
  const steps = deriveSteps(traceSteps, analysing, decisionTrace)

  return (
    <ol
      className="flex flex-wrap gap-x-1 gap-y-3 sm:flex-nowrap"
      aria-label="Protection workflow progress"
    >
      {steps.map((step, i) => (
        <li key={step.id} className="flex min-w-[86px] flex-1 flex-col items-center gap-1.5">
          <div className="flex w-full items-center gap-1">
            <span
              className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-[10px] ${DOT[step.status]}`}
              aria-hidden="true"
            >
              {step.status === 'done' ? (
                <Check size={12} />
              ) : step.status === 'active' ? (
                <Loader2 size={12} className="animate-spin" />
              ) : step.status === 'skipped' ? (
                <Minus size={12} />
              ) : (
                <span className="tabular">{i + 1}</span>
              )}
            </span>
            {i < steps.length - 1 && (
              <span
                className={`h-px flex-1 ${step.status === 'done' ? 'bg-safe/40' : 'bg-hairline'}`}
                aria-hidden="true"
              />
            )}
          </div>
          <span className={`text-center text-[10px] leading-tight ${LABEL[step.status]}`}>
            {step.label}
            <span className="sr-only"> — {step.status}</span>
          </span>
          {step.note && (
            <span className="text-center text-[9px] leading-tight text-muted">{step.note}</span>
          )}
        </li>
      ))}
    </ol>
  )
}

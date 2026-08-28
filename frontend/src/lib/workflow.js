/**
 * The eight-step user workflow, derived from the backend's trace.
 *
 * The steps are a reading of what the engine reported, not a script the UI
 * plays. A step is only `done` once the stage that proves it appears in
 * `trace`, and steps the engine legitimately never reaches are marked
 * `skipped` rather than left looking stuck.
 */

export const STEPS = [
  { id: 'enter', label: 'Enter position', stage: null },
  { id: 'analyze', label: 'Analyze', stage: null },
  { id: 'risk', label: 'Current risk', stage: 'ASSESS' },
  { id: 'scenarios', label: 'Future scenarios', stage: 'ASSESS' },
  { id: 'generate', label: 'Strategies generated', stage: 'GENERATE' },
  { id: 'select', label: 'Best strategy selected', stage: 'SELECT' },
  { id: 'execute', label: 'Simulated protection', stage: 'EXECUTE' },
  { id: 'protected', label: 'Position protected', stage: 'SETTLE' },
]

/**
 * @param {object[]} trace        stages the backend reported, in order
 * @param {boolean}  analysing    a request is in flight
 * @param {object?}  decisionTrace the run's summary, once it exists
 * @returns {{id: string, label: string, status: 'done'|'active'|'skipped'|'pending', note?: string}[]}
 */
export function deriveSteps(trace, analysing, decisionTrace) {
  const seen = new Set((trace ?? []).map((s) => s.stage))
  const started = analysing || (trace ?? []).length > 0
  const finished = Boolean(decisionTrace) && !analysing
  const execution = decisionTrace?.execution

  return STEPS.map((step, index) => {
    if (step.id === 'enter') {
      return { ...step, status: started || finished ? 'done' : 'active' }
    }
    if (step.id === 'analyze') {
      if (analysing) return { ...step, status: 'active' }
      return { ...step, status: started ? 'done' : 'pending' }
    }

    if (seen.has(step.stage)) {
      // The last stage reported while a run is still streaming is the active
      // one; everything before it is done.
      const isLast = trace[trace.length - 1]?.stage === step.stage
      return { ...step, status: isLast && analysing ? 'active' : 'done' }
    }

    // Reached the end without this stage: decide whether it was skipped for a
    // legitimate reason or is simply still ahead.
    if (finished) {
      if (execution === 'NOT REQUIRED') {
        return {
          ...step,
          status: index >= 4 ? 'skipped' : 'done',
          note: index >= 4 ? 'No rescue needed' : undefined,
        }
      }
      if (execution === 'STOOD DOWN') {
        return { ...step, status: 'skipped', note: 'Agent stood down' }
      }
      if (execution === 'AWAITING CONFIRMATION') {
        return {
          ...step,
          status: step.id === 'execute' ? 'active' : 'pending',
          note: step.id === 'execute' ? 'Awaiting your confirmation' : undefined,
        }
      }
    }
    return { ...step, status: 'pending' }
  })
}

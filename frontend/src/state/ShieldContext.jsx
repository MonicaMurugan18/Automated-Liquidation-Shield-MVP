import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import {
  api,
  toMarketPayload,
  toPositionPayload,
  toPreferencesPayload,
} from '../api/client'

/**
 * Client-side view of the agent.
 *
 * This module holds no liquidation logic. It does not compute a price, a
 * Health Factor, a cost or a shield state -- every one of those values
 * arrives from the backend and is stored here verbatim for the pages to
 * render.
 *
 * The one thing that is genuinely client-side is *pacing*: the demo replays
 * the backend's ordered trace with a delay between stages so a human can read
 * the transition. Each replayed stage carries the state and the numbers the
 * engine computed for it, so what you watch is what the engine did.
 */

const ShieldContext = createContext(null)

/** The scenario the Demo Mode button requests. Sent to the backend as a
 *  parameter; the backend derives the price, never the browser. */
const DEMO_DROP_PCT = 10

/** Milliseconds between replayed trace stages. Presentation only. */
const STAGE_BEAT = 750

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

/**
 * Pause between replayed stages -- but only for someone who is actually
 * watching. Background tabs clamp setTimeout hard, which would leave the walk
 * frozen mid-rescue until the tab is refocused. The decision is already
 * computed either way; the pacing is purely for the eye.
 */
const pace = () =>
  typeof document !== 'undefined' && document.hidden ? Promise.resolve() : sleep(STAGE_BEAT)

export function ShieldProvider({ children }) {
  const [booted, setBooted] = useState(false)
  const [bootError, setBootError] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  /** What the agent is doing right now, for the loading indicators. */
  const [activity, setActivity] = useState(null)

  const [position, setPosition] = useState(null)
  const [basePosition, setBasePosition] = useState(null)
  const [preferences, setPreferences] = useState(null)
  const [market, setMarket] = useState(null)
  const [bands, setBands] = useState(null)
  const [assetCatalogue, setAssetCatalogue] = useState(null)
  const [demoPosition, setDemoPosition] = useState(null)

  const [assessment, setAssessment] = useState(null)
  const [scenarios, setScenarios] = useState([])
  const [scenarioSummary, setScenarioSummary] = useState('')
  const [breakingScenario, setBreakingScenario] = useState(null)
  const [thresholds, setThresholds] = useState(null)
  const [strategies, setStrategies] = useState([])
  const [selectedStrategy, setSelectedStrategy] = useState(null)
  const [explanation, setExplanation] = useState('')
  const [weights, setWeights] = useState({})
  const [validation, setValidation] = useState(null)
  const [history, setHistory] = useState([])
  const [persistence, setPersistence] = useState('unknown')
  const [systemHealth, setSystemHealth] = useState(null)

  const [shieldState, setShieldState] = useState('ARMED')
  const [lastRescue, setLastRescue] = useState(null)
  const [decisionTrace, setDecisionTrace] = useState(null)
  /**
   * The candidate set from the most recent completed cycle.
   *
   * After an autonomous rescue the position is safe, so the live strategy list
   * is legitimately empty -- there is nothing left to suggest. But the whole
   * point of the comparison view is auditing a decision that already happened,
   * so the set that produced it is kept here for review.
   */
  const [lastCycle, setLastCycle] = useState(null)
  const [traceSteps, setTraceSteps] = useState([])
  const [demoRunning, setDemoRunning] = useState(false)
  const [analysing, setAnalysing] = useState(false)

  // Guards the demo against double-clicks without waiting for a state flush.
  const demoLock = useRef(false)

  const payloadFor = useCallback(
    (pos, prefs, mkt) => ({
      position: toPositionPayload(pos),
      preferences: toPreferencesPayload(prefs),
      // The market's eth_price is the gas denomination and is sent as-is. It
      // is deliberately NOT the collateral price: a BTC position still pays
      // gas in ETH.
      market: toMarketPayload(mkt),
    }),
    [],
  )

  /** Pull every engine output for a given position/preferences/market. */
  const evaluate = useCallback(
    async (pos, prefs, mkt, { quiet = false, label = 'Re-evaluating position' } = {}) => {
      if (!quiet) {
        setBusy(true)
        setActivity(label)
      }
      try {
        const body = payloadFor(pos, prefs, mkt)
        const [analysis, scenarioResult, comparison] = await Promise.all([
          api.analyze({ position: body.position, preferences: body.preferences }),
          api.simulateScenarios({ position: body.position, preferences: body.preferences }),
          api.compareStrategies(body),
        ])
        const check = await api.validateRescue(body)

        setAssessment(analysis.assessment)
        setScenarios(scenarioResult.scenarios)
        setScenarioSummary(scenarioResult.summary)
        setBreakingScenario(scenarioResult.first_breaking_scenario)
        setThresholds(scenarioResult.thresholds)
        setStrategies(comparison.rows)
        setSelectedStrategy(comparison.selected_strategy)
        setExplanation(comparison.explanation)
        setWeights(comparison.weights)
        setValidation(check)
        setError(null)
        return { analysis, comparison, check }
      } catch (err) {
        setError(err.message)
        throw err
      } finally {
        if (!quiet) {
          setBusy(false)
          setActivity(null)
        }
      }
    },
    [payloadFor],
  )

  const refreshHistory = useCallback(async () => {
    try {
      const result = await api.history()
      setHistory(result.transactions)
      setPersistence(result.persistence)
    } catch {
      /* history is non-critical; the dashboard still works without it */
    }
  }, [])

  // --- boot ---------------------------------------------------------------
  const boot = useCallback(async () => {
    setBootError(null)
    try {
      const [defaults, health, catalogue] = await Promise.all([
        api.defaults(),
        api.health(),
        api.assets(),
      ])
      setPosition(defaults.position)
      setBasePosition(defaults.position)
      setPreferences(defaults.preferences)
      setMarket(defaults.market)
      setBands(defaults.risk_bands)
      setAssetCatalogue(catalogue)
      setDemoPosition(defaults.position)
      setPersistence(health.persistence)
      setSystemHealth(health)
      await evaluate(defaults.position, defaults.preferences, defaults.market, {
        quiet: true,
      })
      await refreshHistory()
      setBooted(true)
    } catch (err) {
      setSystemHealth(null)
      setBootError(err.message)
    }
  }, [evaluate, refreshHistory])

  useEffect(() => {
    boot()
    // Boot runs once; `boot` is stable for the lifetime of the provider.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Outside a demo run the status bar follows whatever the backend's last
  // validate call said. It is still the backend's verdict, not a local guess.
  useEffect(() => {
    if (demoRunning || !assessment || !validation) return
    if (validation.execution_status?.startsWith('SKIPPED')) {
      setShieldState('SKIPPED')
    } else if (assessment.requires_action) {
      setShieldState('ALERT')
    } else {
      setShieldState('ARMED')
    }
  }, [assessment, validation, demoRunning])

  // --- actions ------------------------------------------------------------

  const applyPosition = useCallback(
    async (patch) => {
      const next = { ...position, ...patch }
      setPosition(next)
      setBasePosition(next)
      setLastRescue(null)
      setDecisionTrace(null)
      setLastCycle(null)
      await evaluate(next, preferences, market)
    },
    [position, preferences, market, evaluate],
  )

  const applyPreferences = useCallback(
    async (patch) => {
      const next = { ...preferences, ...patch }
      setPreferences(next)
      await evaluate(position, next, market, { label: 'Re-scoring strategies' })
    },
    [position, preferences, market, evaluate],
  )

  const applyMarket = useCallback(
    async (patch) => {
      const next = { ...market, ...patch }
      setMarket(next)
      await evaluate(position, preferences, next, { label: 'Re-costing strategies' })
    },
    [position, preferences, market, evaluate],
  )

  const resetPosition = useCallback(async () => {
    setLastRescue(null)
    setDecisionTrace(null)
    setLastCycle(null)
    setTraceSteps([])
    setPosition(basePosition)
    await evaluate(basePosition, preferences, market, { label: 'Resetting position' })
  }, [basePosition, preferences, market, evaluate])

  /**
   * Execute the currently selected strategy. Used by the Advisory-mode
   * confirm button. Simulated end to end on the server.
   */
  const executeRescue = useCallback(
    async ({ confirm = true } = {}) => {
      setBusy(true)
      setActivity('Executing rescue')
      // The only state the client asserts, and only because the request is
      // still in flight: the server cannot report "currently executing" until
      // it has finished. Every state after this one comes from the response.
      setShieldState('PROTECTING')
      try {
        const body = { ...payloadFor(position, preferences, market), confirm }
        const result = await api.autoexecute(body)
        setLastRescue(result)

        if (result.executed) {
          // The backend reports PROTECTED once the rescue has landed.
          setShieldState(result.shield_state)
          const next = { ...position, ...result.position_after }
          setPosition(next)
          setDecisionTrace((prev) =>
            prev
              ? {
                  ...prev,
                  execution: 'SIMULATED SUCCESS',
                  final_health_factor: result.assessment_after.health_factor,
                  final_risk_level: result.assessment_after.risk_level,
                }
              : prev,
          )
          await evaluate(next, preferences, market, { quiet: true })
          await refreshHistory()
          await sleep(STAGE_BEAT)
          setShieldState('ARMED')
        } else {
          setShieldState(result.shield_state)
        }
        return result
      } catch (err) {
        setError(err.message)
        setShieldState('ALERT')
        throw err
      } finally {
        setBusy(false)
        setActivity(null)
      }
    },
    [position, preferences, market, payloadFor, evaluate, refreshHistory],
  )

  /**
   * Walk one cycle response into the UI.
   *
   * Shared by Demo Mode and by "Analyze position", because both are the same
   * server-side cycle -- one at -10%, one at 0%. Every state in the walk and
   * every number in the commentary comes out of `cycle.trace`; nothing here
   * invents either. The only client-side element is the pause between stages.
   */
  const replayCycle = useCallback(
    async (cycle, prefsForCycle) => {
      const prefs = prefsForCycle ?? preferences
      setDecisionTrace(cycle.decision_trace)
      setLastCycle(
        cycle.strategies?.length
          ? {
              strategies: cycle.strategies,
              selected: cycle.selected_strategy,
              explanation: cycle.explanation,
              executed: cycle.executed,
              economics: cycle.economics,
              decisionTrace: cycle.decision_trace,
            }
          : null,
      )

      const shown = []
      for (const step of cycle.trace) {
        shown.push(step)
        setTraceSteps([...shown])
        setShieldState(step.shield_state)

        // Keep the dashboard's headline figures in step with the narration.
        if (step.stage === 'SHOCK' || step.stage === 'ASSESS') {
          setPosition(cycle.position_shocked)
          setAssessment(cycle.assessment_shocked)
          setScenarios(cycle.scenarios)
        }
        if (step.stage === 'GENERATE' || step.stage === 'SCORE' || step.stage === 'SELECT') {
          setStrategies(cycle.strategies)
          setSelectedStrategy(cycle.selected_strategy)
          setExplanation(cycle.explanation)
        }
        if (step.stage === 'SETTLE') {
          setPosition(cycle.position_final)
          setAssessment(cycle.assessment_final)
        }
        await pace()
      }

      if (cycle.executed) {
        setLastRescue({
          executed: true,
          selected_strategy: cycle.selected_strategy,
          assessment_before: cycle.assessment_shocked,
          assessment_after: cycle.assessment_final,
          transaction: cycle.transaction,
        })
        await refreshHistory()
      }

      // Settle the app on whatever position the cycle ended with, and refresh
      // the other pages from the API rather than reusing stale numbers.
      setPosition(cycle.position_final)
      await evaluate(cycle.position_final, prefs, market, { quiet: true })
      setShieldState(cycle.shield_state)
      return cycle
    },
    [preferences, market, evaluate, refreshHistory],
  )

  /**
   * Demo Mode: the same cycle, run at a -10% price shock.
   */
  const runDemo = useCallback(async () => {
    if (demoLock.current || !position) return null
    demoLock.current = true
    setDemoRunning(true)
    setLastRescue(null)
    setDecisionTrace(null)
    setTraceSteps([])
    setError(null)
    setBusy(true)
    setActivity(`Running the agent cycle at -${DEMO_DROP_PCT}%`)

    try {
      const cycle = await api.simulateDrop({
        ...payloadFor(position, preferences, market),
        price_drop_pct: DEMO_DROP_PCT,
        confirm: false,
      })
      setBusy(false)
      setActivity(null)
      return await replayCycle(cycle)
    } catch (err) {
      setError(err.message)
      setShieldState('ALERT')
      setBusy(false)
      setActivity(null)
      return null
    } finally {
      setDemoRunning(false)
      demoLock.current = false
    }
  }, [position, preferences, market, payloadFor, replayCycle])

  /**
   * Analyze a position the user typed in.
   *
   * Runs the very same server-side cycle the demo runs, at a 0% price shock:
   * assess, project scenarios, generate, cost, reject, score, select, and (in
   * Autonomous mode) execute. There is no separate code path for user input --
   * that is the whole point.
   */
  const analysePosition = useCallback(
    async ({ position: entered, preferences: entered_prefs }) => {
      if (demoLock.current) return null
      demoLock.current = true
      setAnalysing(true)
      setBusy(true)
      setActivity('Analyzing your position')
      setError(null)
      setLastRescue(null)
      setDecisionTrace(null)
      setTraceSteps([])

      const nextPosition = {
        ...position,
        ...entered,
        // Let the backend resolve these from the chosen asset.
        liquidation_threshold: null,
        liquidation_bonus: null,
        close_factor: null,
      }
      const nextPrefs = { ...preferences, ...entered_prefs }

      try {
        const cycle = await api.simulateDrop({
          position: toPositionPayload(nextPosition),
          preferences: toPreferencesPayload(nextPrefs),
          market: toMarketPayload(market),
          price_drop_pct: 0,
          confirm: false,
        })

        setPreferences(nextPrefs)
        // The server echoes back the position with the asset's resolved risk
        // parameters; adopt that rather than the half-filled draft.
        setBasePosition(cycle.position_before)
        setBusy(false)
        setActivity(null)
        setAnalysing(false)
        await replayCycle(cycle, nextPrefs)
        return cycle
      } catch (err) {
        setError(err.message)
        setBusy(false)
        setActivity(null)
        setAnalysing(false)
        return null
      } finally {
        demoLock.current = false
      }
    },
    [position, preferences, market, replayCycle],
  )

  /** Put the built-in demo position back in play, then analyse it. */
  const loadDemoPosition = useCallback(async () => {
    if (!demoPosition) return null
    setPosition(demoPosition)
    setBasePosition(demoPosition)
    return analysePosition({
      position: demoPosition,
      preferences: { target_health_factor: 1.5, trigger_health_factor: 1.2 },
    })
  }, [demoPosition, analysePosition])

  /** Catalogue entry for whatever asset the current position holds. */
  const collateralSpec =
    assetCatalogue?.assets?.find((a) => a.symbol === position?.collateral_asset) ?? null

  const value = useMemo(
    () => ({
      booted,
      bootError,
      error,
      busy,
      activity,
      position,
      basePosition,
      preferences,
      market,
      bands,
      assessment,
      scenarios,
      scenarioSummary,
      breakingScenario,
      thresholds,
      strategies,
      selectedStrategy,
      explanation,
      weights,
      validation,
      history,
      persistence,
      systemHealth,
      shieldState,
      lastRescue,
      decisionTrace,
      lastCycle,
      traceSteps,
      demoRunning,
      demoDropPct: DEMO_DROP_PCT,
      assetCatalogue,
      collateralSpec,
      demoPosition,
      analysing,
      analysePosition,
      loadDemoPosition,
      retryBoot: boot,
      applyPosition,
      applyPreferences,
      applyMarket,
      resetPosition,
      executeRescue,
      runDemo,
      clearError: () => setError(null),
    }),
    [
      booted, bootError, error, busy, activity, position, basePosition, preferences,
      market, bands, assessment, scenarios, scenarioSummary, breakingScenario, thresholds,
      strategies, selectedStrategy, explanation, weights, validation, history,
      persistence, systemHealth, shieldState, lastRescue, decisionTrace, lastCycle, traceSteps, demoRunning,
      assetCatalogue, collateralSpec, demoPosition, analysing, boot, applyPosition, applyPreferences,
      applyMarket, resetPosition, executeRescue, runDemo, analysePosition,
      loadDemoPosition,
    ],
  )

  return <ShieldContext.Provider value={value}>{children}</ShieldContext.Provider>
}

export function useShield() {
  const ctx = useContext(ShieldContext)
  if (!ctx) throw new Error('useShield must be used inside a ShieldProvider')
  return ctx
}

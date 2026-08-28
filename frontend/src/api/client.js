/**
 * The only module that talks to the backend.
 *
 * Nothing in the frontend imports a web3 library, signs anything, or knows
 * what a flash loan is. Every number on screen came out of the Python engines
 * over one of these calls -- which is what keeps the architecture layering
 * honest: Frontend -> FastAPI -> engines.
 */

const BASE = import.meta.env.VITE_API_BASE ?? '/api'

export class ApiError extends Error {
  constructor(message, status, detail) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

/** Turn FastAPI's two error shapes into one readable sentence. */
function readDetail(payload, status) {
  const detail = payload?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((d) => {
        const field = (d.loc ?? []).filter((p) => p !== 'body').join('.')
        return field ? `${field}: ${d.msg}` : d.msg
      })
      .join('; ')
  }
  return `Request failed with status ${status}.`
}

async function request(path, { method = 'GET', body } = {}) {
  let response
  try {
    response = await fetch(`${BASE}${path}`, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    })
  } catch {
    throw new ApiError(
      'Cannot reach the protection service. Is the backend running on port 8001?',
      0,
    )
  }

  const payload = await response.json().catch(() => null)
  if (!response.ok) {
    throw new ApiError(readDetail(payload, response.status), response.status, payload?.detail)
  }
  return payload
}

export const api = {
  health: () => request('/health'),
  defaults: () => request('/defaults'),
  assets: () => request('/assets'),

  /**
   * The live ETH/USD spot price.
   *
   * The ONLY real-world data in the system, and it is fetched here rather than
   * in a component so no browser ever talks to a market API directly. The
   * backend owns the providers, the timeout handling and the rate limiting.
   */
  ethPrice: (refresh = false) => request(`/market/eth-price${refresh ? '?refresh=true' : ''}`),

  analyze: (body) => request('/position/analyze', { method: 'POST', body }),
  simulateScenarios: (body) => request('/scenario/simulate', { method: 'POST', body }),
  generateStrategies: (body) => request('/strategies/generate', { method: 'POST', body }),
  compareStrategies: (body) => request('/strategies/compare', { method: 'POST', body }),
  validateRescue: (body) => request('/rescue/validate', { method: 'POST', body }),
  autoexecute: (body) => request('/rescue/autoexecute', { method: 'POST', body }),
  history: (limit = 50) => request(`/history?limit=${limit}`),

  /**
   * One full agent cycle, run server-side.
   *
   * The client sends a percentage and nothing else. The backend applies the
   * shock, revalues collateral, recalculates the Health Factor and risk band,
   * generates and costs the candidates, rejects, scores, selects, executes (or
   * holds), recomputes the final Health Factor, and returns an ordered trace
   * carrying the shield state at every stage.
   */
  simulateDrop: (body) => request('/demo/simulate-drop', { method: 'POST', body }),
}

/** Strip a position payload down to the fields the API accepts. */
export function toPositionPayload(position) {
  const payload = {
    collateral_asset: position.collateral_asset,
    debt_asset: position.debt_asset,
    debt_amount: position.debt_amount,
    collateral_price: position.collateral_price,
    // Resolved server-side from the asset catalogue when absent, which is
    // how a user-entered position gets its risk parameters.
    liquidation_threshold: position.liquidation_threshold ?? null,
    liquidation_bonus: position.liquidation_bonus ?? null,
    close_factor: position.close_factor ?? null,
  }

  // Collateral goes over the wire EITHER as units or as dollars, never both --
  // the API rejects both, because two sources of truth disagree the moment the
  // price moves. Units win when present: they are price-independent, so a
  // re-evaluation after a shock stays correct. Dollars are what the form
  // collects, and the server converts them.
  if (position.collateral_amount != null) {
    payload.collateral_amount = position.collateral_amount
  } else if (position.collateral_value != null) {
    payload.collateral_value = position.collateral_value
  }
  return payload
}

/** Strip a preferences payload down to the fields the API accepts. */
export function toPreferencesPayload(prefs) {
  return {
    target_health_factor: prefs.target_health_factor,
    trigger_health_factor: prefs.trigger_health_factor,
    max_slippage_pct: prefs.max_slippage_pct,
    mode: prefs.mode,
    available_capital: prefs.available_capital,
    weight_safety: prefs.weight_safety,
    weight_cost: prefs.weight_cost,
    weight_slippage: prefs.weight_slippage,
    weight_liquidity: prefs.weight_liquidity,
    weight_capital: prefs.weight_capital,
  }
}

export function toMarketPayload(market) {
  return {
    eth_price: market.eth_price,
    gas_price_gwei: market.gas_price_gwei,
    dex_liquidity_usd: market.dex_liquidity_usd,
    dex_base_fee_pct: market.dex_base_fee_pct,
    max_pool_utilisation: market.max_pool_utilisation,
    flash_loan_fee_pct: market.flash_loan_fee_pct,
  }
}

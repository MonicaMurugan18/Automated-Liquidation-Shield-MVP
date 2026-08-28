/** Display formatting. All numeric output is rendered in JetBrains Mono via
 *  the `.tabular` class so digits align and do not jitter on live updates. */

export const RISK_TONE = {
  SAFE: 'safe',
  WARNING: 'warn',
  DANGER: 'danger',
  LIQUIDATABLE: 'danger',
}

export const TONE_TEXT = {
  safe: 'text-safe',
  warn: 'text-warn',
  danger: 'text-danger',
  muted: 'text-muted',
}

export const TONE_BORDER = {
  safe: 'border-safe/40',
  warn: 'border-warn/40',
  danger: 'border-danger/40',
  muted: 'border-hairline',
}

export const TONE_BG = {
  safe: 'bg-safe/10',
  warn: 'bg-warn/10',
  danger: 'bg-danger/10',
  muted: 'bg-panel-raised',
}

export const TONE_HEX = {
  safe: '#2DD9A8',
  warn: '#E8A33D',
  danger: '#E1524F',
  muted: '#7C8798',
}

/** The sentinel the backend uses for a position with no debt. */
export const INFINITE_HF = 999

export function riskTone(level) {
  return RISK_TONE[level] ?? 'muted'
}

/**
 * Last-resort band values, used only for the frames before `/api/defaults`
 * has answered. The backend is the authority: every caller passes the bands
 * it returned, and these must never be treated as the real thresholds.
 */
export const FALLBACK_BANDS = { liquidatable: 1.0, danger: 1.2, warning: 1.5 }

/** Tone from a raw Health Factor, using the backend's bands. */
export function hfTone(hf, bands) {
  const b = bands ?? FALLBACK_BANDS
  if (hf >= INFINITE_HF) return 'safe'
  if (hf < b.liquidatable) return 'danger'
  if (hf < b.danger) return 'danger'
  if (hf < b.warning) return 'warn'
  return 'safe'
}

export function fmtHF(hf) {
  if (hf == null) return '--'
  if (hf >= INFINITE_HF) return '∞'
  return hf.toFixed(3)
}

export function fmtUsd(value, digits = 2) {
  if (value == null) return '--'
  return value.toLocaleString('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

export function fmtUsd0(value) {
  return fmtUsd(value, 0)
}

/**
 * Format an asset price at the precision that asset deserves. $60,000 wants no
 * decimals; $0.80 wants four, or it renders as "$1" and the whole dashboard
 * looks broken.
 */
export function fmtPrice(value, decimals) {
  if (value == null) return '--'
  if (decimals != null) return fmtUsd(value, decimals)
  if (value >= 1000) return fmtUsd(value, 0)
  if (value >= 1) return fmtUsd(value, 2)
  return fmtUsd(value, 4)
}

export function fmtPct(value, digits = 2) {
  if (value == null) return '--'
  return `${value.toFixed(digits)}%`
}

export function fmtNumber(value, digits = 4) {
  if (value == null) return '--'
  return value.toFixed(digits)
}

export function fmtDateTime(iso) {
  if (!iso) return '--'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '--'
  return d.toLocaleString('en-US', {
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

export function shortHash(hash) {
  if (!hash) return '--'
  return `${hash.slice(0, 10)}…${hash.slice(-6)}`
}

/** Human labels for the engine's status enums. */
export const STATUS_LABEL = {
  VIABLE: 'Valid',
  REJECTED_HIGH_SLIPPAGE: 'Rejected — excessive slippage',
  REJECTED_INSUFFICIENT_LIQUIDITY: 'Rejected — insufficient liquidity',
  REJECTED_INSUFFICIENT_CAPITAL: 'Rejected — insufficient capital',
  INVALID_CANNOT_REACH_TARGET: 'Rejected — cannot restore target HF',
  NOT_REQUIRED: 'Not required',
}

/** Compact form for the comparison matrix, where the column is narrow. */
export const STATUS_LABEL_SHORT = {
  VIABLE: 'Valid',
  REJECTED_HIGH_SLIPPAGE: 'Rejected · slippage',
  REJECTED_INSUFFICIENT_LIQUIDITY: 'Rejected · liquidity',
  REJECTED_INSUFFICIENT_CAPITAL: 'Rejected · capital',
  INVALID_CANNOT_REACH_TARGET: 'Rejected · misses target',
  NOT_REQUIRED: 'Not required',
}

export const SAFETY_TONE = { HIGH: 'safe', MEDIUM: 'warn', LOW: 'danger' }

export const EXECUTION_LABEL = {
  NO_ACTION_REQUIRED: 'No action required',
  EXECUTED: 'Executed',
  AWAITING_CONFIRMATION: 'Awaiting confirmation',
  SKIPPED_UNECONOMICAL: 'Skipped · uneconomical',
  SKIPPED_NO_VIABLE_STRATEGY: 'Skipped · no viable strategy',
}

export function statusTone(status) {
  if (status === 'VIABLE') return 'safe'
  if (status === 'INVALID_CANNOT_REACH_TARGET') return 'warn'
  if (status === 'NOT_REQUIRED') return 'muted'
  return 'danger'
}

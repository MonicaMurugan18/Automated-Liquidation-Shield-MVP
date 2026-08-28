import { TONE_BG, TONE_BORDER, TONE_TEXT, riskTone } from '../lib/format'

/** Shared chrome. Quiet by design -- the gauge is the only loud element. */

export function Panel({ title, subtitle, actions, children, className = '', as: Tag = 'section' }) {
  return (
    <Tag
      className={`rounded-lg border border-hairline bg-panel ${className}`}
    >
      {(title || actions) && (
        <header className="flex flex-wrap items-start justify-between gap-3 border-b border-hairline px-4 py-3">
          <div>
            {title && (
              <h2 className="font-display text-[13px] font-medium tracking-[0.14em] text-muted uppercase">
                {title}
              </h2>
            )}
            {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
          </div>
          {actions}
        </header>
      )}
      <div className="p-4">{children}</div>
    </Tag>
  )
}

export function Stat({ label, value, sub, tone = 'muted', mono = true }) {
  return (
    <div className="rounded-md border border-hairline bg-panel-raised px-3 py-3">
      <div className="font-display text-[10px] tracking-[0.16em] text-muted uppercase">
        {label}
      </div>
      <div
        className={`mt-1.5 text-xl ${mono ? 'tabular' : 'font-display'} ${
          tone === 'muted' ? 'text-ink' : TONE_TEXT[tone]
        }`}
      >
        {value}
      </div>
      {sub && <div className="mt-0.5 text-xs text-muted">{sub}</div>}
    </div>
  )
}

export function Badge({ children, tone = 'muted', className = '' }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 font-display text-[11px] tracking-[0.1em] uppercase ${TONE_BORDER[tone]} ${TONE_BG[tone]} ${TONE_TEXT[tone]} ${className}`}
    >
      {children}
    </span>
  )
}

export function RiskBadge({ level }) {
  return <Badge tone={riskTone(level)}>{level ?? 'unknown'}</Badge>
}

export function Button({
  children,
  onClick,
  variant = 'default',
  disabled = false,
  type = 'button',
  className = '',
  ...rest
}) {
  const styles = {
    default:
      'border-hairline bg-panel-raised text-ink hover:border-muted hover:bg-hairline',
    primary:
      'border-safe/50 bg-safe/15 text-safe hover:bg-safe/25',
    danger:
      'border-danger/50 bg-danger/15 text-danger hover:bg-danger/25',
    ghost: 'border-transparent bg-transparent text-muted hover:text-ink',
  }
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center justify-center gap-2 rounded-md border px-3.5 py-2 font-display text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-45 ${styles[variant]} ${className}`}
      {...rest}
    >
      {children}
    </button>
  )
}

export function Field({ label, hint, error, children, htmlFor }) {
  // The hint and the error share one id so a single aria-describedby on the
  // control always points at whichever text is currently on screen.
  const describedBy = htmlFor ? `${htmlFor}-desc` : undefined
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="font-display text-xs tracking-wide text-ink">
        {label}
      </label>
      {children}
      {error ? (
        <p id={describedBy} role="alert" className="text-xs text-danger">
          {error}
        </p>
      ) : (
        hint && (
          <p id={describedBy} className="text-xs text-muted">
            {hint}
          </p>
        )
      )}
    </div>
  )
}

export function NumberInput({
  id,
  value,
  onChange,
  step = 1,
  min,
  max,
  suffix,
  invalid,
  placeholder,
  inputRef,
}) {
  return (
    <div className="relative">
      <input
        id={id}
        ref={inputRef}
        type="number"
        inputMode="decimal"
        value={value}
        step={step}
        min={min}
        max={max}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        aria-invalid={invalid || undefined}
        aria-describedby={id ? `${id}-desc` : undefined}
        className={`tabular w-full rounded-md border bg-base px-3 py-2 text-sm text-ink outline-none focus:border-safe ${
          invalid ? 'border-danger' : 'border-hairline'
        } ${suffix ? 'pr-12' : ''}`}
      />
      {suffix && (
        <span className="tabular pointer-events-none absolute top-1/2 right-3 -translate-y-1/2 text-xs text-muted">
          {suffix}
        </span>
      )}
    </div>
  )
}

export function Select({ id, value, onChange, options, invalid, describedBy }) {
  return (
    <select
      id={id}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      aria-invalid={invalid || undefined}
      aria-describedby={describedBy}
      className={`w-full rounded-md border bg-base px-3 py-2 font-display text-sm text-ink outline-none focus:border-safe ${
        invalid ? 'border-danger' : 'border-hairline'
      }`}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  )
}

export function EmptyState({ icon: Icon, title, children }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-md border border-dashed border-hairline px-6 py-10 text-center">
      {Icon && <Icon size={22} className="text-muted" aria-hidden="true" />}
      <p className="font-display text-sm text-ink">{title}</p>
      {children && <p className="max-w-md text-sm text-muted">{children}</p>}
    </div>
  )
}

export function ErrorBanner({ message, onDismiss }) {
  if (!message) return null
  return (
    <div
      role="alert"
      className="flex items-start justify-between gap-3 rounded-md border border-danger/50 bg-danger/10 px-4 py-3 text-sm text-danger"
    >
      <span>{message}</span>
      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          className="font-display text-xs tracking-wide text-danger/80 hover:text-danger"
        >
          DISMISS
        </button>
      )}
    </div>
  )
}

/** A labelled horizontal meter for score components. */
export function ScoreBar({ label, value, tone = 'safe' }) {
  const pct = Math.round((value ?? 0) * 100)
  const fill = { safe: 'bg-safe', warn: 'bg-warn', danger: 'bg-danger', muted: 'bg-muted' }
  return (
    <div className="flex items-center gap-2">
      <span className="w-20 shrink-0 text-[11px] text-muted capitalize">{label}</span>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-hairline">
        <div className={`h-full rounded-full ${fill[tone]}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="tabular w-9 shrink-0 text-right text-[11px] text-muted">{pct}</span>
    </div>
  )
}

import { Link } from 'react-router-dom'
import {
  Activity,
  ArrowRight,
  Crosshair,
  Layers,
  Radar,
  Scale,
  ShieldCheck,
  ShieldHalf,
  Siren,
  TrendingDown,
} from 'lucide-react'
import { useShield } from '../state/ShieldContext'
import HealthFactorGauge from '../components/HealthFactorGauge'
import { shieldState as lookupState } from '../lib/shieldStates'
import { RiskBadge } from '../components/ui'
import { fmtHF, fmtUsd0 } from '../lib/format'

/**
 * Landing dashboard: the entrance to the control room.
 *
 * Deliberately not a marketing page. The telemetry on this screen is live --
 * the engine statuses come from `GET /api/health` and the Health Factor
 * preview is the real seed position read through the same risk engine the
 * portal uses. When the backend is down this page says so rather than
 * printing a reassuring "ONLINE" it cannot vouch for.
 */

const PORTAL = '/portal'

// ---------------------------------------------------------------------------

function Rule({ label }) {
  return (
    <div className="flex items-center gap-3">
      <span className="font-display text-[10px] tracking-[0.22em] text-muted uppercase">
        {label}
      </span>
      <span className="h-px flex-1 bg-hairline" aria-hidden="true" />
    </div>
  )
}

function PortalButton({ children, className = '', variant = 'primary' }) {
  const styles =
    variant === 'primary'
      ? 'border-safe/50 bg-safe/15 text-safe hover:bg-safe/25'
      : 'border-hairline bg-panel-raised text-ink hover:border-muted'
  return (
    <Link
      to={PORTAL}
      className={`inline-flex items-center justify-center gap-2 rounded-md border px-4 py-2.5 font-display text-sm tracking-wide transition-colors ${styles} ${className}`}
    >
      {children}
      <ArrowRight size={15} aria-hidden="true" />
    </Link>
  )
}

// ---------------------------------------------------------------------------

function Header({ state, online }) {
  const { Icon } = state
  const tone = online ? state.tone : 'danger'
  const TEXT = { safe: 'text-safe', warn: 'text-warn', danger: 'text-danger' }
  const DOT = { safe: 'bg-safe', warn: 'bg-warn', danger: 'bg-danger' }

  return (
    <header className="sticky top-0 z-30 border-b border-hairline bg-base/95 backdrop-blur">
      <div className="mx-auto flex max-w-[1200px] flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3 sm:px-6">
        <div className="flex items-center gap-2.5">
          <ShieldHalf size={22} className="shrink-0 text-safe" aria-hidden="true" />
          <div>
            <p className="font-display text-sm leading-tight font-semibold tracking-wide text-ink">
              AUTOMATED LIQUIDATION SHIELD
            </p>
            <p className="font-display text-[10px] leading-tight tracking-[0.18em] text-muted uppercase">
              Autonomous DeFi protection system
            </p>
          </div>
        </div>

        <div className="order-3 flex w-full items-center gap-4 lg:order-none lg:ml-auto lg:w-auto">
          <span
            className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 font-display text-[11px] tracking-[0.14em] ${
              online ? 'border-safe/40 bg-safe/10' : 'border-danger/40 bg-danger/10'
            } ${TEXT[tone]}`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${DOT[tone]} ${state.pulse && online ? 'animate-shield-pulse' : ''}`}
              aria-hidden="true"
            />
            <Icon size={12} aria-hidden="true" />
            {online ? `SYSTEM ${state.short}` : 'SYSTEM OFFLINE'}
          </span>

          <nav aria-label="Landing sections" className="hidden items-center gap-5 md:flex">
            {[
              ['#overview', 'Overview'],
              ['#how-it-works', 'How It Works'],
              ['#about', 'About'],
            ].map(([href, label]) => (
              <a
                key={href}
                href={href}
                className="font-display text-sm text-muted transition-colors hover:text-ink"
              >
                {label}
              </a>
            ))}
          </nav>

          <PortalButton className="ml-auto lg:ml-0">ENTER PROTECTION PORTAL</PortalButton>
        </div>
      </div>
    </header>
  )
}

// ---------------------------------------------------------------------------

const PILLARS = [
  {
    Icon: TrendingDown,
    title: 'Scenario prediction',
    body: 'Simulate future market movements and project the Health Factor across every one.',
  },
  {
    Icon: Scale,
    title: 'Multi-strategy scoring',
    body: 'Evaluate several protection strategies on safety, cost, slippage and liquidity.',
  },
  {
    Icon: Crosshair,
    title: 'Autonomous execution',
    body: 'Automatically select and execute the best valid rescue, without waiting for you.',
  },
]

function Hero() {
  return (
    <section id="overview" className="flex flex-col gap-8 scroll-mt-24">
      <div className="flex flex-col gap-5">
        <Rule label="Control center" />
        <h1 className="max-w-3xl font-display text-3xl leading-[1.15] font-semibold text-balance text-ink sm:text-4xl lg:text-5xl">
          Protect your DeFi position
          <span className="block text-muted">before liquidation happens.</span>
        </h1>
        <p className="max-w-2xl text-sm leading-relaxed text-muted sm:text-base">
          An autonomous risk-management system that monitors DeFi positions, simulates future
          market scenarios, evaluates multiple protection strategies, and automatically executes
          the best valid rescue.
        </p>
      </div>

      <ul className="grid gap-3 sm:grid-cols-3">
        {PILLARS.map(({ Icon, title, body }) => (
          <li
            key={title}
            className="flex flex-col gap-2 rounded-lg border border-hairline bg-panel p-4"
          >
            <Icon size={18} className="text-safe" aria-hidden="true" />
            <h2 className="font-display text-[11px] tracking-[0.16em] text-ink uppercase">
              {title}
            </h2>
            <p className="text-sm leading-relaxed text-muted">{body}</p>
          </li>
        ))}
      </ul>
    </section>
  )
}

// ---------------------------------------------------------------------------

function Telemetry({ state, online, health, mode }) {
  const engines = health?.engines ?? {}
  const engineStatus = (key) => {
    if (!online) return { text: 'UNREACHABLE', tone: 'danger' }
    return engines[key] === 'ready'
      ? { text: 'ONLINE', tone: 'safe' }
      : { text: 'UNKNOWN', tone: 'warn' }
  }

  const rows = [
    {
      label: 'System status',
      ...(online
        ? { text: state.short, tone: state.tone, dot: true }
        : { text: 'OFFLINE', tone: 'danger', dot: true }),
    },
    {
      label: 'Position monitoring',
      text: online ? 'ACTIVE' : 'HALTED',
      tone: online ? 'safe' : 'danger',
    },
    { label: 'Risk engine', ...engineStatus('risk_engine') },
    { label: 'Scenario engine', ...engineStatus('scenario_engine') },
    { label: 'Strategy engine', ...engineStatus('strategy_engine') },
    {
      label: 'Execution mode',
      text: online ? mode : '—',
      tone: online && mode === 'AUTONOMOUS' ? 'safe' : 'warn',
    },
  ]

  const TEXT = { safe: 'text-safe', warn: 'text-warn', danger: 'text-danger' }
  const DOT = { safe: 'bg-safe', warn: 'bg-warn', danger: 'bg-danger' }

  return (
    <section className="flex flex-col gap-4">
      <Rule label="Live system status" />
      <div className="rounded-lg border border-hairline bg-panel">
        <dl className="grid grid-cols-2 divide-hairline sm:grid-cols-3 lg:grid-cols-6 lg:divide-x">
          {rows.map((row) => (
            <div
              key={row.label}
              className="flex flex-col gap-1.5 border-b border-hairline px-4 py-3.5 last:border-b-0 lg:border-b-0"
            >
              <dt className="font-display text-[9px] tracking-[0.16em] text-muted uppercase">
                {row.label}
              </dt>
              <dd className={`tabular flex items-center gap-1.5 text-sm ${TEXT[row.tone]}`}>
                {row.dot && (
                  <span
                    className={`h-1.5 w-1.5 shrink-0 rounded-full ${DOT[row.tone]}`}
                    aria-hidden="true"
                  />
                )}
                {row.text}
              </dd>
            </div>
          ))}
        </dl>
        <p className="flex flex-wrap items-center gap-2 border-t border-hairline px-4 py-2.5 text-xs text-muted">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-warn/40 bg-warn/10 px-2.5 py-0.5 font-display text-[10px] tracking-[0.14em] text-warn uppercase">
            <Siren size={11} aria-hidden="true" />
            Simulation environment
          </span>
          Prototype telemetry. No transaction is signed or broadcast; market, gas and DEX data
          are modelled in the Python engines.
        </p>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------

const PIPELINE = [
  { Icon: Radar, name: 'Monitor', body: 'Watch position health' },
  { Icon: TrendingDown, name: 'Scenario', body: 'Simulate future price drops' },
  { Icon: Siren, name: 'Risk', body: 'Detect unsafe conditions' },
  { Icon: Layers, name: 'Strategies', body: 'Generate possible interventions' },
  { Icon: Scale, name: 'Score', body: 'Evaluate safety and cost' },
  { Icon: Crosshair, name: 'Auto-select', body: 'Choose the best valid strategy' },
  { Icon: ShieldCheck, name: 'Protect', body: 'Execute simulated rescue' },
]

function Pipeline() {
  return (
    <section className="flex flex-col gap-4">
      <Rule label="Protection pipeline" />
      <ol className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7">
        {PIPELINE.map(({ Icon, name, body }, i) => (
          <li
            key={name}
            className="relative flex flex-col gap-2 rounded-lg border border-hairline bg-panel p-3.5"
          >
            <div className="flex items-center gap-2">
              <Icon size={15} className="shrink-0 text-safe" aria-hidden="true" />
              <span className="tabular text-[10px] text-muted">
                {String(i + 1).padStart(2, '0')}
              </span>
            </div>
            <h3 className="font-display text-[11px] tracking-[0.14em] text-ink uppercase">
              {name}
            </h3>
            <p className="text-xs leading-snug text-muted">{body}</p>
            {i < PIPELINE.length - 1 && (
              <span
                className="absolute top-1/2 -right-[9px] hidden h-px w-[10px] bg-hairline xl:block"
                aria-hidden="true"
              />
            )}
          </li>
        ))}
      </ol>
    </section>
  )
}

// ---------------------------------------------------------------------------

function GaugePreview({ assessment, preferences, bands, position, online }) {
  return (
    <section className="flex flex-col gap-4">
      <Rule label="Central risk measurement" />
      <div className="grid gap-5 rounded-lg border border-hairline bg-panel p-5 lg:grid-cols-[minmax(0,260px)_minmax(0,1fr)] lg:items-center">
        <div className="flex justify-center">
          {online && assessment ? (
            <HealthFactorGauge
              healthFactor={assessment.health_factor}
              target={preferences?.target_health_factor ?? 1.5}
              bands={bands}
              bufferPct={assessment.safety_buffer_pct}
              size={230}
            />
          ) : (
            <div className="flex h-[230px] w-[230px] items-center justify-center rounded-full border border-dashed border-hairline text-center text-xs text-muted">
              Telemetry unavailable
              <br />
              while the engine is offline
            </div>
          )}
        </div>

        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="font-display text-lg text-ink">Health Factor</h2>
            {online && assessment && <RiskBadge level={assessment.risk_level} />}
          </div>
          <p className="text-sm leading-relaxed text-muted">
            One number decides everything. Below <span className="tabular text-ink">1.00</span> a
            liquidator can seize your collateral at a discount. The shield sizes every rescue to
            restore your target and intervenes before the line is crossed — the arc, its tick
            marks and the sweeping needle are the instrument you watch inside the portal.
          </p>
          {online && assessment && position && (
            <dl className="grid grid-cols-2 gap-3 border-t border-hairline pt-3 sm:grid-cols-4">
              {[
                ['Health factor', fmtHF(assessment.health_factor)],
                ['Collateral', fmtUsd0(assessment.collateral_value)],
                ['Debt', fmtUsd0(assessment.debt_value)],
                ['Liquidation at', fmtUsd0(assessment.liquidation_price)],
              ].map(([label, value]) => (
                <div key={label}>
                  <dt className="font-display text-[9px] tracking-[0.16em] text-muted uppercase">
                    {label}
                  </dt>
                  <dd className="tabular mt-0.5 text-sm text-ink">{value}</dd>
                </div>
              ))}
            </dl>
          )}
          <p className="text-xs text-muted">
            Live reading of the currently loaded position, straight from the risk engine.
          </p>
        </div>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------

const STEPS = [
  { n: '01', name: 'Monitor', body: 'Continuously evaluate the DeFi position.' },
  { n: '02', name: 'Predict', body: 'Simulate future adverse price scenarios.' },
  { n: '03', name: 'Decide', body: 'Generate, score and rank protection strategies.' },
  { n: '04', name: 'Protect', body: 'Automatically execute the best valid strategy.' },
]

function HowItWorks() {
  return (
    <section id="how-it-works" className="flex flex-col gap-4 scroll-mt-24">
      <Rule label="How the autonomous shield works" />
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {STEPS.map(({ n, name, body }) => (
          <article
            key={n}
            className="flex flex-col gap-2 rounded-lg border border-hairline bg-panel p-4"
          >
            <span className="tabular text-2xl leading-none text-hairline">{n}</span>
            <h3 className="font-display text-[11px] tracking-[0.16em] text-ink uppercase">
              {name}
            </h3>
            <p className="text-sm leading-relaxed text-muted">{body}</p>
          </article>
        ))}
      </div>
      <p className="rounded-md border border-hairline bg-panel-raised px-4 py-3 text-sm text-muted">
        Strategy comparison is provided for transparency and explainability. Autonomous Mode does
        not require the user to manually choose a strategy.
      </p>
    </section>
  )
}

// ---------------------------------------------------------------------------

function DemoCta() {
  return (
    <section className="flex flex-col gap-4 rounded-lg border border-hairline bg-panel p-6 sm:p-8">
      <div className="flex flex-col gap-2">
        <h2 className="font-display text-xl font-semibold text-ink sm:text-2xl">
          Ready to test the shield?
        </h2>
        <p className="max-w-2xl text-sm leading-relaxed text-muted">
          Load a simulated DeFi position and see how the autonomous protection engine responds to
          a market shock.
        </p>
      </div>
      <div className="flex flex-wrap gap-2.5">
        <PortalButton>OPEN PROTECTION PORTAL</PortalButton>
        <Link
          to={`${PORTAL}?demo=1`}
          className="inline-flex items-center justify-center gap-2 rounded-md border border-hairline bg-panel-raised px-4 py-2.5 font-display text-sm tracking-wide text-ink transition-colors hover:border-muted"
        >
          LOAD DEMO POSITION
          <ArrowRight size={15} aria-hidden="true" />
        </Link>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------

function About({ health }) {
  return (
    <section id="about" className="flex flex-col gap-4 scroll-mt-24">
      <Rule label="About" />
      <div className="grid gap-3 lg:grid-cols-3">
        <p className="text-sm leading-relaxed text-muted lg:col-span-2">
          A hackathon prototype. The risk, scenario and strategy engines are real Python — Health
          Factor maths, repayment sizing, constraint checks, composite scoring and autonomous
          selection all run server-side and are covered by an automated test suite. What is
          simulated is the chain: prices, gas, DEX liquidity and flash loans are modelled, and
          execution never leaves memory. Every simulated receipt is flagged and prefixed{' '}
          <span className="tabular text-ink">0xSIM</span>.
        </p>
        <dl className="flex flex-col gap-2 rounded-lg border border-hairline bg-panel p-4 text-xs">
          {[
            ['Service', health?.service ?? 'Automated Liquidation Shield'],
            ['API version', health?.version ?? '—'],
            ['Blockchain', health?.engines?.blockchain ?? 'simulated'],
            ['Persistence', health?.persistence ?? '—'],
          ].map(([label, value]) => (
            <div key={label} className="flex items-baseline justify-between gap-3">
              <dt className="text-muted">{label}</dt>
              <dd className="tabular text-right text-ink">{value}</dd>
            </div>
          ))}
        </dl>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------

export default function Landing() {
  const { assessment, preferences, bands, position, systemHealth, shieldState, bootError, booted } =
    useShield()

  const online = booted && !bootError
  const state = lookupState(online ? shieldState : 'ARMED')
  const mode = preferences?.mode ?? 'AUTONOMOUS'

  return (
    <div className="min-h-screen bg-base">
      <Header state={state} online={online} />

      <main className="mx-auto flex max-w-[1200px] flex-col gap-12 px-4 py-10 sm:px-6 sm:py-14">
        <Hero />
        <Telemetry state={state} online={online} health={systemHealth} mode={mode} />
        <Pipeline />
        <GaugePreview
          assessment={assessment}
          preferences={preferences}
          bands={bands}
          position={position}
          online={online}
        />
        <HowItWorks />
        <DemoCta />
        <About health={systemHealth} />
      </main>

      <footer className="border-t border-hairline">
        <div className="mx-auto flex max-w-[1200px] flex-wrap items-center justify-between gap-4 px-4 py-6 sm:px-6">
          <div className="flex items-center gap-2.5">
            <Activity size={16} className="text-muted" aria-hidden="true" />
            <div>
              <p className="font-display text-xs tracking-[0.14em] text-ink uppercase">
                Automated Liquidation Shield
              </p>
              <p className="text-xs text-muted">
                Scenario-driven autonomous DeFi protection
              </p>
            </div>
          </div>
          <p className="font-display text-[10px] tracking-[0.18em] text-muted uppercase">
            Prototype • Simulated environment
          </p>
        </div>
      </footer>
    </div>
  )
}

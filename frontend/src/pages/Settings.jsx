import { useEffect, useState } from 'react'
import { Bot, UserCheck } from 'lucide-react'
import { useShield } from '../state/ShieldContext'
import { Button, Field, NumberInput, Panel } from '../components/ui'
import { fmtPct } from '../lib/format'

/** Page 7: risk preferences, score weights, and the Autonomous/Advisory toggle. */

function ModeToggle({ mode, onChange, disabled }) {
  const options = [
    {
      value: 'AUTONOMOUS',
      label: 'Autonomous',
      Icon: Bot,
      blurb: 'The agent executes the top-scored strategy on its own. Default.',
    },
    {
      value: 'ADVISORY',
      label: 'Advisory',
      Icon: UserCheck,
      blurb: 'Same reasoning, same selection — execution pauses for your confirmation.',
    },
  ]

  return (
    <fieldset disabled={disabled} className="flex flex-col gap-2">
      <legend className="font-display text-xs tracking-wide text-ink">Protection mode</legend>
      <div className="grid gap-2 sm:grid-cols-2">
        {options.map(({ value, label, Icon, blurb }) => {
          const active = mode === value
          return (
            <label
              key={value}
              className={`flex cursor-pointer gap-2.5 rounded-md border p-3 transition-colors ${
                active
                  ? 'border-safe/60 bg-safe/10'
                  : 'border-hairline bg-panel-raised hover:border-muted'
              }`}
            >
              <input
                type="radio"
                name="mode"
                value={value}
                checked={active}
                onChange={() => onChange(value)}
                className="sr-only"
              />
              <Icon
                size={16}
                className={`mt-0.5 shrink-0 ${active ? 'text-safe' : 'text-muted'}`}
                aria-hidden="true"
              />
              <div>
                <p className={`font-display text-sm ${active ? 'text-safe' : 'text-ink'}`}>
                  {label}
                </p>
                <p className="mt-0.5 text-xs text-muted">{blurb}</p>
              </div>
            </label>
          )
        })}
      </div>
    </fieldset>
  )
}

const WEIGHT_FIELDS = [
  ['weight_safety', 'Safety', 'Resulting Health Factor, discounted for execution risk.'],
  ['weight_cost', 'Cost', 'Total rescue cost against the loss it prevents.'],
  ['weight_slippage', 'Slippage', 'Headroom left inside your price-impact tolerance.'],
  ['weight_liquidity', 'Liquidity', 'Share of routable DEX depth the trade consumes.'],
  ['weight_capital', 'Capital', 'How much idle wallet capital the rescue locks up.'],
]

export default function Settings() {
  const { preferences, market, applyPreferences, applyMarket, busy } = useShield()
  const [draft, setDraft] = useState(null)
  const [marketDraft, setMarketDraft] = useState(null)
  const [problem, setProblem] = useState(null)

  useEffect(() => {
    if (preferences) setDraft({ ...preferences })
  }, [preferences])
  useEffect(() => {
    if (market) setMarketDraft({ ...market })
  }, [market])

  if (!draft || !marketDraft) return null

  const set = (key) => (value) => setDraft((d) => ({ ...d, [key]: value }))
  const setMarketValue = (key) => (value) => setMarketDraft((d) => ({ ...d, [key]: value }))

  const weightTotal = WEIGHT_FIELDS.reduce((sum, [key]) => sum + Number(draft[key] || 0), 0)

  const validate = () => {
    const target = Number(draft.target_health_factor)
    const trigger = Number(draft.trigger_health_factor)
    if (Number.isNaN(target) || target <= 1) return 'Target Health Factor must be above 1.00.'
    if (Number.isNaN(trigger) || trigger <= 1) return 'Trigger Health Factor must be above 1.00.'
    if (trigger > target) return 'The trigger cannot be above the target.'
    if (Number(draft.max_slippage_pct) <= 0) return 'Maximum slippage must be above zero.'
    if (Number(draft.available_capital) < 0) return 'Available capital cannot be negative.'
    if (weightTotal <= 0) return 'At least one score weight must be above zero.'
    return null
  }

  const savePreferences = async (e) => {
    e.preventDefault()
    const found = validate()
    setProblem(found)
    if (found) return
    const numeric = Object.fromEntries(
      Object.entries(draft).map(([k, v]) => [k, k === 'mode' ? v : Number(v)]),
    )
    try {
      await applyPreferences(numeric)
    } catch {
      /* reported by the shell banner */
    }
  }

  const changeMode = async (mode) => {
    setDraft((d) => ({ ...d, mode }))
    try {
      await applyPreferences({ mode })
    } catch {
      /* reported by the shell banner */
    }
  }

  const saveMarket = async (e) => {
    e.preventDefault()
    try {
      await applyMarket(
        Object.fromEntries(Object.entries(marketDraft).map(([k, v]) => [k, Number(v)])),
      )
    } catch {
      /* reported by the shell banner */
    }
  }

  return (
    <div className="grid gap-5 xl:grid-cols-2">
      <Panel title="Protection mode" subtitle="Autonomous is the default behaviour.">
        <ModeToggle mode={draft.mode} onChange={changeMode} disabled={busy} />
      </Panel>

      <Panel title="Risk preferences">
        <form onSubmit={savePreferences} noValidate className="flex flex-col gap-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              label="Target Health Factor"
              htmlFor="target-hf"
              hint="Every rescue is sized to restore exactly this."
            >
              <NumberInput
                id="target-hf"
                value={draft.target_health_factor}
                onChange={set('target_health_factor')}
                step="0.05"
                min="1.01"
              />
            </Field>
            <Field
              label="Intervention trigger"
              htmlFor="trigger-hf"
              hint="The agent acts at or below this Health Factor."
            >
              <NumberInput
                id="trigger-hf"
                value={draft.trigger_health_factor}
                onChange={set('trigger_health_factor')}
                step="0.05"
                min="1.01"
              />
            </Field>
            <Field
              label="Maximum slippage"
              htmlFor="max-slippage"
              hint="Strategies above this are rejected outright."
            >
              <NumberInput
                id="max-slippage"
                value={draft.max_slippage_pct}
                onChange={set('max_slippage_pct')}
                step="0.1"
                min="0.01"
                suffix="%"
              />
            </Field>
            <Field
              label="Available capital"
              htmlFor="available-capital"
              hint="Idle wallet funds the agent may deploy."
            >
              <NumberInput
                id="available-capital"
                value={draft.available_capital}
                onChange={set('available_capital')}
                step="250"
                min="0"
                suffix="USD"
              />
            </Field>
          </div>

          <div className="flex flex-col gap-3 border-t border-hairline pt-4">
            <div className="flex items-baseline justify-between">
              <p className="font-display text-xs tracking-wide text-ink">Score weights</p>
              <p className="text-xs text-muted">
                Normalised on the server —{' '}
                <span className="tabular text-ink">{weightTotal.toFixed(2)}</span> total is fine.
              </p>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              {WEIGHT_FIELDS.map(([key, label, hint]) => (
                <Field key={key} label={label} htmlFor={key} hint={hint}>
                  <NumberInput
                    id={key}
                    value={draft[key]}
                    onChange={set(key)}
                    step="0.05"
                    min="0"
                    max="1"
                  />
                </Field>
              ))}
            </div>
          </div>

          {problem && <p className="text-xs text-danger">{problem}</p>}

          <div>
            <Button type="submit" variant="primary" disabled={busy}>
              Save preferences
            </Button>
          </div>
        </form>
      </Panel>

      <Panel
        title="Simulated market"
        subtitle="The seam where live oracle, DEX and gas data plug in later."
        className="xl:col-span-2"
      >
        <form onSubmit={saveMarket} noValidate className="flex flex-col gap-4">
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <Field label="Gas price" htmlFor="gas-price" hint="Drives every strategy's gas cost.">
              <NumberInput
                id="gas-price"
                value={marketDraft.gas_price_gwei}
                onChange={setMarketValue('gas_price_gwei')}
                step="1"
                min="0.1"
                suffix="gwei"
              />
            </Field>
            <Field
              label="DEX liquidity"
              htmlFor="dex-liquidity"
              hint="Lower it to see the liquidity and slippage rejections."
            >
              <NumberInput
                id="dex-liquidity"
                value={marketDraft.dex_liquidity_usd}
                onChange={setMarketValue('dex_liquidity_usd')}
                step="10000"
                min="1"
                suffix="USD"
              />
            </Field>
            <Field
              label="Max pool utilisation"
              htmlFor="pool-utilisation"
              hint="Largest share of depth the agent will route through."
            >
              <NumberInput
                id="pool-utilisation"
                value={marketDraft.max_pool_utilisation}
                onChange={setMarketValue('max_pool_utilisation')}
                step="0.05"
                min="0.01"
                max="1"
              />
            </Field>
            <Field
              label="Flash loan fee"
              htmlFor="flash-fee"
              hint={`Aave v3 premium (${fmtPct(marketDraft.flash_loan_fee_pct)}).`}
            >
              <NumberInput
                id="flash-fee"
                value={marketDraft.flash_loan_fee_pct}
                onChange={setMarketValue('flash_loan_fee_pct')}
                step="0.01"
                min="0"
                suffix="%"
              />
            </Field>
          </div>
          <div>
            <Button type="submit" disabled={busy}>
              Apply market conditions
            </Button>
          </div>
        </form>
      </Panel>
    </div>
  )
}

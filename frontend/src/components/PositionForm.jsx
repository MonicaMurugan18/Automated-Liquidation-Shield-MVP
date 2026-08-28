import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Loader2, PlayCircle, RadioTower, RefreshCw, Search } from 'lucide-react'
import { useShield } from '../state/ShieldContext'
import { Badge, Button, Field, NumberInput, Panel, Select } from './ui'
import { fmtPrice } from '../lib/format'

/**
 * "Analyze Your Position" -- the entry point for a user's own position.
 *
 * The form collects values and nothing else. It does not compute a collateral
 * value, a Health Factor or a risk level: those come back from the API, which
 * is also where the liquidation threshold for the chosen asset lives. Picking
 * BTC changes the threshold because the backend says so, not because this file
 * knows anything about BTC.
 */

const BLANK_FIELDS = {
  collateral_asset: 'ETH',
  // Collateral is entered in DOLLARS -- the friendlier unit for someone who
  // knows they deposited "about $10,000". The backend converts it to units at
  // the entered price, because only a quantity re-values itself when the
  // price moves. The conversion is deliberately not done here.
  collateral_value: '',
  collateral_price: '',
  debt_amount: '',
  target_health_factor: '1.50',
  trigger_health_factor: '1.20',
}

/** Friendly, field-level validation mirroring the backend's rules. */
function validate(values) {
  const errors = {}
  const collateral = Number(values.collateral_value)
  const price = Number(values.collateral_price)
  const debt = Number(values.debt_amount)
  const target = Number(values.target_health_factor)
  const trigger = Number(values.trigger_health_factor)

  if (values.collateral_value === '' || Number.isNaN(collateral)) {
    errors.collateral_value = 'Please enter your collateral value.'
  } else if (collateral < 0) {
    errors.collateral_value = 'Collateral cannot be negative.'
  } else if (collateral === 0) {
    errors.collateral_value = 'Collateral must be greater than zero.'
  }

  if (values.collateral_price === '' || Number.isNaN(price)) {
    errors.collateral_price = 'Please enter the current asset price.'
  } else if (price <= 0) {
    errors.collateral_price = 'Asset price must be greater than zero.'
  }

  if (values.debt_amount === '' || Number.isNaN(debt)) {
    errors.debt_amount = 'Please enter your debt amount. Enter 0 if you have none.'
  } else if (debt < 0) {
    errors.debt_amount = 'Debt cannot be negative.'
  }

  if (Number.isNaN(target) || target <= 1) {
    errors.target_health_factor =
      'Target Health Factor must be above 1.00 — anything lower offers no protection.'
  }
  if (Number.isNaN(trigger) || trigger <= 1) {
    errors.trigger_health_factor = 'Intervention trigger must be above 1.00.'
  } else if (!Number.isNaN(target) && trigger > target) {
    errors.trigger_health_factor =
      'The trigger cannot be above the target — the agent would act after it was already too late.'
  }

  return errors
}

const FIELD_ORDER = [
  'collateral_value',
  'collateral_price',
  'debt_amount',
  'target_health_factor',
  'trigger_health_factor',
]

export default function PositionForm() {
  const {
    assetCatalogue,
    analysePosition,
    loadDemoPosition,
    analysing,
    busy,
    demoPosition,
    livePrice,
    marketStatus,
    fetchLivePrice,
  } = useShield()
  const [useLivePrice, setUseLivePrice] = useState(true)
  const [values, setValues] = useState(BLANK_FIELDS)
  const [errors, setErrors] = useState({})
  const [touched, setTouched] = useState(false)
  const refs = useRef({})
  const [searchParams, setSearchParams] = useSearchParams()
  const autoloaded = useRef(false)

  const assets = assetCatalogue?.assets ?? []
  const spec = assets.find((a) => a.symbol === values.collateral_asset)

  const applyDemoPosition = useCallback(async () => {
    if (!demoPosition) return
    setValues({
      collateral_asset: demoPosition.collateral_asset,
      collateral_value: String(Math.round(demoPosition.collateral_value)),
      collateral_price: String(demoPosition.collateral_price),
      debt_amount: String(demoPosition.debt_amount),
      target_health_factor: '1.50',
      trigger_health_factor: '1.20',
    })
    setErrors({})
    setTouched(false)
    await loadDemoPosition()
  }, [demoPosition, loadDemoPosition])

  // Seed the price box from the catalogue when the asset changes, so a
  // beginner is never staring at an empty required field. The number stays
  // editable -- it is the user's price, not ours.
  useEffect(() => {
    if (spec && values.collateral_price === '') {
      setValues((v) => ({ ...v, collateral_price: String(spec.reference_price) }))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [spec])

  // Mirror the live price into the form while "use live price" is on. The
  // field stays a plain input -- switching the toggle off hands control back
  // with the last live figure already in place, so nothing is lost.
  const liveEth = marketStatus === 'live' && values.collateral_asset === 'ETH' ? livePrice : null
  useEffect(() => {
    if (liveEth && useLivePrice) {
      setValues((v) => ({ ...v, collateral_price: String(liveEth.price) }))
    }
  }, [liveEth, useLivePrice])

  // Arriving from the landing page's "Load demo position" button.
  useEffect(() => {
    if (autoloaded.current || searchParams.get('demo') !== '1' || !demoPosition) return
    autoloaded.current = true
    setSearchParams({}, { replace: true })
    applyDemoPosition()
  }, [searchParams, setSearchParams, demoPosition, applyDemoPosition])

  if (!assetCatalogue) return null

  const set = (key) => (value) => {
    setValues((v) => ({ ...v, [key]: value }))
    if (touched) setErrors((e) => ({ ...e, [key]: undefined }))
  }

  const changeAsset = (symbol) => {
    const next = assets.find((a) => a.symbol === symbol)
    setValues((v) => ({
      ...v,
      collateral_asset: symbol,
      // Re-seed the price for the new asset; keeping $3,000 after switching to
      // ARB would be a worse default than an obvious one.
      collateral_price: next ? String(next.reference_price) : v.collateral_price,
    }))
    if (touched) setErrors((e) => ({ ...e, collateral_price: undefined }))
  }

  const submit = async (e) => {
    e.preventDefault()
    setTouched(true)
    const found = validate(values)
    setErrors(found)

    const firstBad = FIELD_ORDER.find((f) => found[f])
    if (firstBad) {
      refs.current[firstBad]?.focus()
      return
    }

    await analysePosition({
      position: {
        collateral_asset: values.collateral_asset,
        collateral_value: Number(values.collateral_value),
        collateral_price: Number(values.collateral_price),
        debt_amount: Number(values.debt_amount),
      },
      preferences: {
        target_health_factor: Number(values.target_health_factor),
        trigger_health_factor: Number(values.trigger_health_factor),
      },
    })
  }

  const assetOptions = assets.map((a) => ({
    value: a.symbol,
    label: `${a.symbol} — ${a.name}`,
  }))

  return (
    <Panel
      title="Protect your position"
      subtitle="Enter what you deposited and what you borrowed. The engine does the rest."
    >
      <form onSubmit={submit} noValidate className="flex flex-col gap-4">
        <fieldset disabled={busy} className="flex flex-col gap-4">
          <legend className="sr-only">Your lending position</legend>

          <div className="flex flex-wrap items-center gap-3 rounded-md border border-hairline bg-panel-raised px-3.5 py-2.5">
            <label className="flex cursor-pointer items-center gap-2 text-sm text-ink">
              <input
                type="checkbox"
                checked={useLivePrice}
                onChange={(e) => setUseLivePrice(e.target.checked)}
                className="h-4 w-4 accent-[#2DD9A8]"
              />
              Use live ETH price
            </label>

            {marketStatus === 'live' && livePrice ? (
              <>
                <Badge tone="safe">
                  <RadioTower size={11} aria-hidden="true" />
                  {livePrice.source}
                </Badge>
                <span className="tabular text-sm text-ink">{fmtPrice(livePrice.price, 2)}</span>
              </>
            ) : marketStatus === 'loading' ? (
              <span className="flex items-center gap-1.5 text-xs text-muted">
                <Loader2 size={12} className="animate-spin" aria-hidden="true" />
                fetching…
              </span>
            ) : (
              <Badge tone="warn">Live market data unavailable — demo / manual price</Badge>
            )}

            <button
              type="button"
              onClick={() => fetchLivePrice({ force: true })}
              disabled={marketStatus === 'loading' || busy}
              className="ml-auto inline-flex items-center gap-1.5 rounded-md border border-hairline px-2.5 py-1 font-display text-xs text-muted transition-colors hover:border-muted hover:text-ink disabled:opacity-45"
            >
              <RefreshCw size={12} aria-hidden="true" />
              Refresh
            </button>
          </div>

          {values.collateral_asset !== 'ETH' && useLivePrice && (
            <p className="text-xs text-warn">
              Live pricing covers ETH/USD only. {values.collateral_asset} uses the price you
              enter below.
            </p>
          )}

          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <Field
              label="Collateral asset"
              htmlFor="pf-asset"
              hint={
                spec
                  ? `Simulated liquidation threshold ${(spec.liquidation_threshold * 100).toFixed(1)}% (Aave v3 uses ${(spec.real_world_threshold * 100).toFixed(1)}%)`
                  : 'What you deposited'
              }
            >
              <Select
                id="pf-asset"
                value={values.collateral_asset}
                onChange={changeAsset}
                options={assetOptions}
                describedBy="pf-asset-desc"
              />
            </Field>

            <Field
              label="Collateral value"
              htmlFor="pf-collateral"
              hint={`What your ${values.collateral_asset} deposit is worth today`}
              error={errors.collateral_value}
            >
              <NumberInput
                id="pf-collateral"
                inputRef={(el) => (refs.current.collateral_value = el)}
                value={values.collateral_value}
                onChange={set('collateral_value')}
                step="any"
                placeholder="10000"
                suffix="USD"
                invalid={Boolean(errors.collateral_value)}
              />
            </Field>

            <Field
              label="Current asset price"
              htmlFor="pf-price"
              hint={
                liveEth && useLivePrice
                  ? `Live from ${liveEth.source}. Untick "use live ETH price" to override.`
                  : "Today's market price, in USD"
              }
              error={errors.collateral_price}
            >
              <NumberInput
                id="pf-price"
                inputRef={(el) => (refs.current.collateral_price = el)}
                value={values.collateral_price}
                onChange={set('collateral_price')}
                step="any"
                placeholder="0.00"
                suffix="USD"
                invalid={Boolean(errors.collateral_price)}
              />
            </Field>

            <Field
              label="Debt amount"
              htmlFor="pf-debt"
              hint="What you owe the lending protocol, in USD"
              error={errors.debt_amount}
            >
              <NumberInput
                id="pf-debt"
                inputRef={(el) => (refs.current.debt_amount = el)}
                value={values.debt_amount}
                onChange={set('debt_amount')}
                step="any"
                placeholder="0.00"
                suffix={assetCatalogue.default_debt_asset}
                invalid={Boolean(errors.debt_amount)}
              />
            </Field>
          </div>

          <div className="grid gap-4 border-t border-hairline pt-4 sm:grid-cols-2 xl:grid-cols-4">
            <Field
              label="Target Health Factor"
              htmlFor="pf-target"
              hint="The safety level every rescue restores. 1.50 is a sensible default."
              error={errors.target_health_factor}
            >
              <NumberInput
                id="pf-target"
                inputRef={(el) => (refs.current.target_health_factor = el)}
                value={values.target_health_factor}
                onChange={set('target_health_factor')}
                step="any"
                invalid={Boolean(errors.target_health_factor)}
              />
            </Field>

            <Field
              label="Intervention trigger"
              htmlFor="pf-trigger"
              hint="The agent steps in at or below this Health Factor."
              error={errors.trigger_health_factor}
            >
              <NumberInput
                id="pf-trigger"
                inputRef={(el) => (refs.current.trigger_health_factor = el)}
                value={values.trigger_health_factor}
                onChange={set('trigger_health_factor')}
                step="any"
                invalid={Boolean(errors.trigger_health_factor)}
              />
            </Field>

            <div className="flex items-end gap-2 sm:col-span-2">
              <Button type="submit" variant="primary" disabled={analysing || busy}>
                {analysing ? (
                  <>
                    <Loader2 size={14} className="animate-spin" aria-hidden="true" />
                    Analyzing…
                  </>
                ) : (
                  <>
                    <Search size={14} aria-hidden="true" />
                    ANALYZE POSITION
                  </>
                )}
              </Button>
              <Button type="button" onClick={applyDemoPosition} disabled={analysing || busy}>
                <PlayCircle size={14} aria-hidden="true" />
                Load demo position
              </Button>
            </div>
          </div>
        </fieldset>

        <p className="text-xs text-muted">
          Everything below updates from the engine&apos;s response — Health Factor, risk level,
          scenarios, strategies and the rescue decision. Nothing is calculated in your browser.
        </p>
      </form>
    </Panel>
  )
}

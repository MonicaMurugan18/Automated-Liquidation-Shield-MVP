import { useEffect, useState } from 'react'
import { useShield } from '../state/ShieldContext'
import { Button, Field, NumberInput, Panel, RiskBadge, Stat } from '../components/ui'
import { fmtHF, fmtPct, fmtPrice, fmtUsd, fmtUsd0, riskTone } from '../lib/format'

/** Page 2: the position itself, and the only place it can be edited. */
export default function PositionOverview() {
  const { position, assessment, preferences, applyPosition, busy, collateralSpec } = useShield()
  const [draft, setDraft] = useState(null)
  const [fieldError, setFieldError] = useState(null)

  useEffect(() => {
    if (position) {
      setDraft({
        collateral_amount: position.collateral_amount,
        debt_amount: position.debt_amount,
        collateral_price: position.collateral_price,
        liquidation_threshold: position.liquidation_threshold,
      })
    }
  }, [position])

  if (!assessment || !draft) return null

  const set = (key) => (value) => setDraft((d) => ({ ...d, [key]: value }))

  /** Edge case 8: catch bad input in the browser, and let the API catch the
   *  rest. The engine is the authority; this is a courtesy. */
  const validate = () => {
    const amount = Number(draft.collateral_amount)
    const debt = Number(draft.debt_amount)
    const price = Number(draft.collateral_price)
    const lt = Number(draft.liquidation_threshold)

    if ([amount, debt, price, lt].some((v) => Number.isNaN(v))) return 'All fields must be numbers.'
    if (amount < 0) return 'Collateral amount cannot be negative.'
    if (debt < 0) return 'Debt cannot be negative.'
    if (price <= 0) return 'Price must be greater than zero.'
    if (lt <= 0 || lt > 1) return 'Liquidation threshold must be between 0 and 1.'
    return null
  }

  const submit = async (e) => {
    e.preventDefault()
    const problem = validate()
    setFieldError(problem)
    if (problem) return
    try {
      await applyPosition({
        collateral_amount: Number(draft.collateral_amount),
        debt_amount: Number(draft.debt_amount),
        collateral_price: Number(draft.collateral_price),
        liquidation_threshold: Number(draft.liquidation_threshold),
      })
    } catch {
      /* the banner in the shell already reports it */
    }
  }

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Panel title="Position overview" subtitle="Live values from the risk engine.">
        <div className="grid grid-cols-2 gap-3">
          <Stat
            label="Collateral value"
            value={fmtUsd0(assessment.collateral_value)}
            sub={`${position.collateral_amount.toFixed(4)} ${position.collateral_asset} @ ${fmtPrice(position.collateral_price, collateralSpec?.price_decimals)}`}
          />
          <Stat label="Debt" value={fmtUsd0(assessment.debt_value)} sub={position.debt_asset} />
          <Stat
            label="Health factor"
            value={fmtHF(assessment.health_factor)}
            tone={riskTone(assessment.risk_level)}
            sub={`target ${preferences.target_health_factor.toFixed(2)}`}
          />
          <Stat
            label="Liquidation price"
            value={fmtPrice(assessment.liquidation_price, collateralSpec?.price_decimals)}
            sub={`${fmtPct(assessment.price_drop_to_liquidation_pct, 1)} below spot`}
          />
          <Stat
            label="Liquidation threshold"
            value={fmtPct(position.liquidation_threshold * 100, 1)}
            sub="share of collateral counted"
          />
          <Stat
            label="Loss if liquidated"
            value={fmtUsd(assessment.potential_liquidation_loss)}
            sub="close factor × penalty"
          />
        </div>

        <div className="mt-4 flex items-center gap-3 border-t border-hairline pt-4">
          <RiskBadge level={assessment.risk_level} />
          <p className="text-sm text-muted">{assessment.message}</p>
        </div>
      </Panel>

      <Panel
        title="Edit position"
        subtitle="Change the inputs to test the engine against your own numbers."
      >
        <form onSubmit={submit} noValidate className="flex flex-col gap-4">
          <Field
            label="Collateral amount"
            htmlFor="collateral-amount"
            hint={`Units of ${position.collateral_asset}, not dollars`}
          >
            <NumberInput
              id="collateral-amount"
              value={draft.collateral_amount}
              onChange={set('collateral_amount')}
              step="0.0001"
              min="0"
              suffix={position.collateral_asset}
            />
          </Field>

          <Field label="Debt" htmlFor="debt-amount" hint="Stablecoin debt, 1 unit = $1">
            <NumberInput
              id="debt-amount"
              value={draft.debt_amount}
              onChange={set('debt_amount')}
              step="100"
              min="0"
              suffix={position.debt_asset}
            />
          </Field>

          <Field label="Collateral price" htmlFor="collateral-price">
            <NumberInput
              id="collateral-price"
              value={draft.collateral_price}
              onChange={set('collateral_price')}
              step="50"
              min="0"
              suffix="USD"
            />
          </Field>

          <Field
            label="Liquidation threshold"
            htmlFor="liquidation-threshold"
            hint="0.625 is the demo market tier. Aave v3 ETH is 0.825."
            error={fieldError}
          >
            <NumberInput
              id="liquidation-threshold"
              value={draft.liquidation_threshold}
              onChange={set('liquidation_threshold')}
              step="0.005"
              min="0"
              max="1"
              invalid={Boolean(fieldError)}
            />
          </Field>

          <div className="flex gap-2">
            <Button type="submit" variant="primary" disabled={busy}>
              Re-evaluate position
            </Button>
          </div>
        </form>
      </Panel>
    </div>
  )
}

import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { useShield } from '../state/ShieldContext'
import { Panel, RiskBadge } from '../components/ui'
import { TONE_HEX, fmtHF, fmtPrice, fmtUsd0, hfTone, riskTone } from '../lib/format'

/**
 * Page 3: scenario prediction -- differentiator #1.
 *
 * The point is not that a Health Factor can be recomputed. It is that the
 * agent computes the whole trajectory before the market gets there, so the
 * intervention it would need at each rung is already sized.
 */

function ChartTooltip({ active, payload, bands, priceDecimals }) {
  if (!active || !payload?.length) return null
  const row = payload[0].payload
  return (
    <div className="rounded-md border border-hairline bg-panel px-3 py-2 text-xs shadow-lg">
      <p className="font-display text-ink">{row.label}</p>
      <p className="tabular mt-1 text-muted">
        Price <span className="text-ink">{fmtPrice(row.new_price, priceDecimals)}</span>
      </p>
      <p className="tabular text-muted">
        HF{' '}
        <span style={{ color: TONE_HEX[hfTone(row.health_factor, bands)] }}>
          {fmtHF(row.health_factor)}
        </span>
      </p>
      <p className="tabular text-muted">
        Repay <span className="text-ink">{fmtUsd0(row.required_repayment)}</span>
      </p>
    </div>
  )
}

export default function ScenarioPrediction() {
  const {
    scenarios,
    scenarioSummary,
    breakingScenario,
    preferences,
    bands,
    position,
    collateralSpec,
    thresholds,
  } = useShield()

  if (!scenarios.length || !bands || !position) return null

  const priceDecimals = collateralSpec?.price_decimals

  // The three lines the chart marks all come from the backend's scenario
  // response, so they can never disagree with the numbers plotted against them.
  const target = thresholds?.target ?? preferences.target_health_factor
  const trigger = thresholds?.intervention_trigger ?? preferences.trigger_health_factor
  const liquidation = thresholds?.liquidation ?? bands.liquidatable
  const minHf = Math.min(...scenarios.map((s) => s.health_factor), liquidation)
  const maxHf = Math.max(...scenarios.map((s) => s.health_factor), target)

  return (
    <div className="flex flex-col gap-5">
      <Panel
        title="Simulated price scenarios"
        subtitle={scenarioSummary}
        actions={
          breakingScenario ? (
            <RiskBadge level="LIQUIDATABLE" />
          ) : (
            <RiskBadge level={scenarios[scenarios.length - 1].risk_level} />
          )
        }
      >
        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={scenarios} margin={{ top: 8, right: 16, bottom: 4, left: -8 }}>
              <CartesianGrid stroke="#242D3A" strokeDasharray="3 3" vertical={false} />
              <XAxis
                dataKey="label"
                stroke="#7C8798"
                tick={{ fill: '#7C8798', fontSize: 11, fontFamily: 'JetBrains Mono' }}
                tickLine={false}
                axisLine={{ stroke: '#242D3A' }}
              />
              <YAxis
                domain={[Math.min(0.9, minHf - 0.1), Math.max(maxHf + 0.1, 1.6)]}
                stroke="#7C8798"
                tick={{ fill: '#7C8798', fontSize: 11, fontFamily: 'JetBrains Mono' }}
                tickLine={false}
                axisLine={{ stroke: '#242D3A' }}
                tickFormatter={(v) => v.toFixed(2)}
                width={48}
              />
              <Tooltip
                content={<ChartTooltip bands={bands} priceDecimals={priceDecimals} />}
                cursor={{ stroke: '#242D3A' }}
              />

              <ReferenceLine
                y={target}
                stroke={TONE_HEX.safe}
                strokeDasharray="4 4"
                label={{
                  value: `TARGET ${target.toFixed(2)}`,
                  position: 'insideTopRight',
                  fill: TONE_HEX.safe,
                  fontSize: 10,
                  fontFamily: 'JetBrains Mono',
                }}
              />
              <ReferenceLine
                y={trigger}
                stroke={TONE_HEX.warn}
                strokeDasharray="2 3"
                label={{
                  value: `INTERVENTION TRIGGER ${trigger.toFixed(2)}`,
                  position: 'insideRight',
                  fill: TONE_HEX.warn,
                  fontSize: 10,
                  fontFamily: 'JetBrains Mono',
                }}
              />
              <ReferenceLine
                y={liquidation}
                stroke={TONE_HEX.danger}
                label={{
                  value: `LIQUIDATION ${liquidation.toFixed(2)}`,
                  position: 'insideBottomRight',
                  fill: TONE_HEX.danger,
                  fontSize: 10,
                  fontFamily: 'JetBrains Mono',
                }}
              />

              <Line
                type="monotone"
                dataKey="health_factor"
                stroke={TONE_HEX.warn}
                strokeWidth={2}
                dot={(props) => {
                  const { cx, cy, payload, index } = props
                  return (
                    <circle
                      key={index}
                      cx={cx}
                      cy={cy}
                      r={4}
                      fill={TONE_HEX[hfTone(payload.health_factor, bands)]}
                      stroke="#0D1117"
                      strokeWidth={2}
                    />
                  )
                }}
                activeDot={{ r: 6 }}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-hairline pt-3">
          {[
            ['Target', target, TONE_HEX.safe],
            ['Intervention trigger', trigger, TONE_HEX.warn],
            ['Liquidation', liquidation, TONE_HEX.danger],
          ].map(([label, value, colour]) => (
            <span key={label} className="flex items-center gap-1.5 text-xs text-muted">
              <span className="h-px w-4" style={{ backgroundColor: colour }} aria-hidden="true" />
              {label}
              <span className="tabular text-ink">{value.toFixed(2)}</span>
            </span>
          ))}
        </div>

        <p className="mt-3 text-xs leading-relaxed text-muted">
          Scenario projections based on the current {position.collateral_asset} market price.
          Scenario simulation shows how the position could behave under different market
          conditions — these are simulated stress tests, not guaranteed predictions, and
          nothing here forecasts where the price will actually go.
        </p>
      </Panel>

      <Panel
        title="Projected interventions"
        subtitle="Sized at each simulated rung, before any such move happens."
      >
        <div className="-mx-4 overflow-x-auto px-4">
          <table className="w-full min-w-[860px] border-collapse text-sm">
            <thead>
              <tr className="border-b border-hairline text-left">
                {[
                  'Scenario',
                  `${position.collateral_asset} price`,
                  'Collateral',
                  'Health factor',
                  'Risk',
                  'Intervention',
                  'Repay to target',
                  'Or add collateral',
                ].map((h) => (
                  <th
                    key={h}
                    scope="col"
                    className="px-2 py-2 font-display text-[10px] tracking-[0.14em] text-muted uppercase"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {scenarios.map((s) => (
                <tr
                  key={s.label}
                  className={`border-b border-hairline/60 ${
                    s.liquidatable ? 'bg-danger/5' : ''
                  }`}
                >
                  <th
                    scope="row"
                    className="tabular px-2 py-2.5 text-left font-normal text-ink"
                  >
                    {s.label}
                  </th>
                  <td className="tabular px-2 py-2.5 text-muted">
                    {fmtPrice(s.new_price, priceDecimals)}
                  </td>
                  <td className="tabular px-2 py-2.5 text-muted">
                    {fmtUsd0(s.new_collateral_value)}
                  </td>
                  <td
                    className="tabular px-2 py-2.5"
                    style={{ color: TONE_HEX[hfTone(s.health_factor, bands)] }}
                  >
                    {fmtHF(s.health_factor)}
                  </td>
                  <td className="px-2 py-2.5">
                    <RiskBadge level={s.risk_level} />
                  </td>
                  <td className="px-2 py-2.5">
                    {s.requires_intervention ? (
                      <span className="font-display text-[11px] tracking-wide text-warn">
                        REQUIRED
                      </span>
                    ) : (
                      <span className="font-display text-[11px] tracking-wide text-muted">
                        none
                      </span>
                    )}
                  </td>
                  <td className="tabular px-2 py-2.5 text-ink">
                    {s.required_repayment > 0 ? fmtUsd0(s.required_repayment) : '—'}
                  </td>
                  <td className="tabular px-2 py-2.5 text-muted">
                    {s.required_collateral_topup > 0
                      ? fmtUsd0(s.required_collateral_topup)
                      : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <ul className="mt-4 flex flex-col gap-1.5 border-t border-hairline pt-3">
          {scenarios.map((s) => (
            <li key={s.label} className="flex gap-2 text-xs text-muted">
              <span
                className="tabular w-14 shrink-0"
                style={{ color: TONE_HEX[riskTone(s.risk_level)] }}
              >
                {s.label}
              </span>
              <span>{s.intervention_summary}</span>
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  )
}

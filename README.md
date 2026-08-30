# Automated Liquidation Shield

**Autonomous, scenario-driven liquidation protection for a DeFi lending position.**

## At a glance

| | |
| --- | --- |
| **What it does** | Watches a DeFi borrow position, predicts how it behaves under future price shocks, generates and scores several rescue strategies, and executes the best one autonomously |
| **Stack** | React 19 · Vite · Tailwind v4 · Recharts · FastAPI · Python 3.13+ · Supabase (optional) |
| **Tests** | 238, covering the engines, the API and all eight edge cases |
| **Market data** | **Real** ETH/USD spot price from public APIs — see [Market data](#market-data) |
| **Blockchain** | **None.** Fully simulated — see [What is simulated](#what-is-simulated) |
| **Run it** | [Quick start](#quick-start) — two terminals, no credentials needed |
| **Ports** | backend `8001`, frontend `5173` |

## The problem

In DeFi lending platforms, users deposit crypto assets as collateral and borrow
against them. When the collateral price falls, the user's Health Factor
decreases and the risk of liquidation rises.

The real difficulty is not spotting that risk — it is that **users cannot see
how a future price drop will affect their position, or which protection action
would be most suitable.** Deciding what to do manually, during a market that is
moving quickly, is harder still.

So this project predicts potential liquidation risk, evaluates different future
scenarios, and selects the most suitable protection strategy.

> **In one line:** the system predicts how a DeFi position may behave under
> future price drops, generates and scores multiple protection strategies, and
> autonomously selects the best one to prevent liquidation.

### Why this is not just risk detection

Detecting liquidation risk is table stakes. The question this system answers is
the harder one — *what could happen next, and what is the best action to
protect the position?*

```
Risk detection                    ← where most tools stop
      ↓
Scenario prediction               ← how the position behaves under -5/-10/-15/-20%
      ↓
Multiple strategies               ← five candidate interventions, generated and priced
      ↓
Strategy scoring                  ← safety, cost, slippage, liquidity, capital
      ↓
Autonomous selection              ← the agent picks, and executes, without asking
```

### The pipeline, end to end

```
Position details (collateral asset, amount, price, debt)
      ↓
1. Calculate the current Health Factor
      ↓
2. Identify the current risk level
      ↓
3. Simulate future price-drop scenarios     Current / -5% / -10% / -15% / -20%
      ↓
4. Calculate the future Health Factor for each scenario
      ↓
5. Determine the required protection / intervention per scenario
      ↓
6. Generate multiple protection suggestions
      ↓
7. Compare the possible strategies
      ↓
8. Select the most suitable strategy  →  simulated execution  →  final Health Factor
```

---

## Specification traceability

Every claim below is backed by code you can read and a check you can run.

| # | Specification | Where it lives | How to verify |
| --- | --- | --- | --- |
| 1 | **User input** — the user enters their own position, not fixed values | [`PositionForm.jsx`](frontend/src/components/PositionForm.jsx), [`assets.py`](backend/app/services/assets.py) | Enter any position at `/portal`; 7 collateral assets, each with its own liquidation tier |
| 2 | **Health Factor** and risk level (Safe → Warning → Risk) | [`risk_engine.py`](backend/app/services/risk_engine.py) | `pytest tests/test_risk_engine.py` — 4 bands: SAFE / WARNING / DANGER / LIQUIDATABLE |
| 3 | **Scenario prediction** at −5/−10/−15/−20% | [`scenario_engine.py`](backend/app/services/scenario_engine.py) | `POST /api/scenario/simulate`, or the Scenarios page |
| 4 | **Risk visualisation** — gauge, charts, indicators | [`HealthFactorGauge.jsx`](frontend/src/components/HealthFactorGauge.jsx), [`ScenarioPrediction.jsx`](frontend/src/pages/ScenarioPrediction.jsx) | Radial shield-arc gauge; Recharts line marking target, trigger and liquidation |
| 5 | **Protection suggestions** — repay, add collateral, swap, liquidity-based | [`strategy_engine.py`](backend/app/services/strategy_engine.py) | 5 candidates: `REPAY_DEBT`, `ADD_COLLATERAL`, `COLLATERAL_SWAP`, `FLASH_LOAN_DELEVERAGE`, `PARTIAL_DELEVERAGE` |
| 6 | **Strategy comparison** on safety, cost, slippage, gas, resulting HF | [`strategy_engine.py`](backend/app/services/strategy_engine.py) | Comparison page; 5 weighted sub-scores plus gas and flash-fee columns |
| 7 | **Autonomous selection** of the best-scored strategy | [`agent_cycle.py`](backend/app/services/agent_cycle.py) | Autonomous mode selects *and executes*; Advisory mode stops at the recommendation |
| 8 | **Demo mode** — simulated ETH price drop, end to end | [`DemoControls.jsx`](frontend/src/components/DemoControls.jsx), `POST /api/demo/simulate-drop` | "Simulate 10% ETH drop"; status walks ARMED → ALERT → PROTECTING → PROTECTED → ARMED |
| 9 | **Backend** — Python + FastAPI, separate engines | [`backend/app/services/`](backend/app/services/) | `risk_engine.py`, `scenario_engine.py`, `strategy_engine.py`, orchestrated by `agent_cycle.py` |
| 10 | **Frontend** — React + Tailwind CSS | [`frontend/src/`](frontend/src/) | React 19, Vite, Tailwind v4, Recharts |
| 11 | **Blockchain simulated** — no wallets, contracts, flash loans or real transactions | [What is simulated](#what-is-simulated) | No web3 dependency in `package.json`; receipts flagged `simulated: true`, hashes prefixed `0xSIM` |

### Two notes on how the build reads against the spec

**Input shape.** The spec lists the input as *collateral value*. The form asks
instead for **collateral amount and current price**, and the backend derives
the value. This is deliberate: holding units rather than a dollar figure is
what lets a price shock re-value the position automatically, which the whole
scenario engine depends on. The collateral *value* is displayed everywhere the
spec expects it.

**"Liquidity-based protection".** This is implemented as `FLASH_LOAN_DELEVERAGE`
— a candidate that models an atomic flash-borrow with the Aave v3 0.09%
premium. It is **arithmetic only**. No flash loan is taken, quoted or
requested; nothing touches a protocol. It exists so the agent has a
zero-capital option to weigh against the others.

### Beyond the specification

Three things the build does that the spec does not require:

- **Executes the selected strategy** (simulated) and recomputes the final
  Health Factor, rather than stopping at a recommendation.
- **Rejects invalid strategies with reasons** — excessive slippage,
  insufficient liquidity, insufficient capital, cannot restore target — and
  runs an **economic viability check** that stands the agent down when a rescue
  would cost more than the liquidation it prevents.
- **Decision trace** — an auditable record of every stage, so the autonomous
  choice can be inspected after the fact rather than taken on trust.

---

## How it works

The system watches a borrow position continuously. When the Health Factor
crosses the intervention trigger, it projects the position forward through a
ladder of price shocks, generates every rescue it knows how to perform, prices
each one against simulated market conditions, rejects the ones that break a
constraint, scores the survivors, and **executes the winner without asking**.

The Strategy Comparison view is a transparency layer over a decision that has
already been made — not a menu the user has to work through while their
position burns.

> **Nothing here touches a blockchain.** There are no flash loans, no signed
> transactions and no wallet connection. Market, gas and DEX data are modelled
> in Python. Every simulated receipt is flagged `simulated: true` and its hash
> is prefixed `0xSIM`. See [What is simulated](#what-is-simulated).

---

## What it does that a liquidation monitor does not

Monitoring a Health Factor and predicting liquidation are table stakes. The
three things this system does beyond that:

1. **Scenario prediction** — simulates 0/-5/-10/-15/-20% price shocks and
   projects the Health Factor trajectory across all of them, sizing the
   intervention each rung would require *before* the market gets there.
2. **Multi-strategy generation and scoring** — for a position at risk it builds
   five distinct interventions, costs each one (gas, slippage, flash-loan
   premium), checks each against liquidity, slippage, capital and target
   constraints, and scores the survivors on a weighted composite.
3. **Autonomous selection and execution** — the agent picks the top-scored
   strategy and runs it. Advisory mode exists to prove the reasoning is
   inspectable, not because the agent needs permission by default.

---

## Routes

| Route | What it is |
| --- | --- |
| `/` | **Landing dashboard** — the control-center entrance. Live system telemetry, the protection pipeline, and a preview of the Health Factor gauge. |
| `/portal` | **Protection portal** — the position-analysis screen. Enter a position, analyze it, watch the agent work. |
| `/portal?demo=1` | The portal with the demo position auto-loaded and analysed. |
| `/portal/position` · `/scenarios` · `/strategies` · `/comparison` · `/history` · `/settings` | The portal's inner pages, unchanged. |

The landing page renders **outside** the boot gate on purpose: a visitor should
be able to read what the system does even when the backend is down. It reports
`SYSTEM OFFLINE` and marks each engine `UNREACHABLE` rather than printing a
reassuring "ONLINE" it cannot vouch for. The portal cannot open without the
backend, so it waits behind the gate.

Nothing on the landing page is decorative telemetry: the engine statuses come
from `GET /api/health`, and the Health Factor preview is the real loaded
position read through the same risk engine the portal uses.

---

## Two ways to start

**1. Analyze your own position.** The dashboard opens on an "Analyze your
position" form: pick a collateral asset, enter the amount, the current price
and your debt, set a target Health Factor and an intervention trigger, then
press **ANALYZE POSITION**. The backend runs the full agent cycle on those
numbers.

**2. Load the demo position.** One button fills the form with 3.3333 ETH at
$3,000 against $5,000 of debt (target 1.50, trigger 1.20) and analyses it. From
there, **Simulate 10% ETH drop** runs the original demo.

Both paths call the same endpoint and the same Python engines. There is no
separate code path for user input -- a user-entered position that happens to
match the demo produces a byte-identical decision, and a test asserts exactly
that.

---

## Quick start

Two terminals. Backend first.

### Backend

```bash
cd backend
python -m venv .venv
```

Activate it — Windows PowerShell:

```bash
.venv\Scripts\Activate.ps1
```

macOS/Linux:

```bash
source .venv/bin/activate
```

Then install and run:

```bash
pip install -r requirements.txt
```

```bash
uvicorn app.main:app --reload --port 8001
```

- API: <http://localhost:8001/api/health>
- Interactive docs: <http://localhost:8001/docs>

No `.env` is required. Copy `backend/.env.example` to `backend/.env` only when
you want Supabase persistence or non-default CORS origins.

### Frontend

```bash
cd frontend
npm install
```

```bash
npm run dev
```

Open <http://localhost:5173> — the landing dashboard. Press **ENTER
PROTECTION PORTAL** to reach the position-analysis screen at `/portal`. The dev
server proxies `/api` to
`http://127.0.0.1:8001`, so there is no CORS setup and no API URL in the
bundle. Override the target with `VITE_API_TARGET` if your backend runs
elsewhere.

### Tests

```bash
cd backend && python -m pytest
```

291 tests: the risk, scenario, strategy and agent-cycle engines, the market-data
service (fully mocked -- no test touches the internet), the asset catalogue,
user-entered positions, and every HTTP endpoint.
Edge cases 1–8 each have named tests — see the map at the top of
`backend/tests/test_strategy_engine.py`.

---

## Demo Mode

Click **Simulate 10% ETH drop** in the sidebar. The browser sends one number
-- the drop percentage -- to `POST /api/demo/simulate-drop`. The backend runs
the entire cycle and returns every intermediate result, including an ordered
trace with the shield state at each stage. The UI replays that trace:

```
ARMED → ALERT → PROTECTING → PROTECTED → ARMED
```

**Nothing about the run is computed in the browser.** The shocked price, the
revalued collateral, the recalculated Health Factor, the risk band, the
candidate set, the rejections, the winning score, the execution result and the
final Health Factor are all fields of that one response. The only client-side
element is the 750 ms pause between stages, so a human can read the transition.

| Step | What happens |
| --- | --- |
| 1 | Position holds at HF 1.250, ETH $3,000. Status **ARMED**. |
| 2 | ETH drops 10% to $2,700. HF falls to 1.125 — below the 1.20 trigger. |
| 3 | Status **ALERT**. Five candidate strategies generated and costed. |
| 4 | Four clear every constraint; one is marked invalid for missing the target. |
| 5 | `Repay debt from wallet` auto-selected on composite score 0.9413. |
| 6 | Status **PROTECTING**. Rescue executes (simulated). |
| 7 | HF recalculated at 1.500. Status **PROTECTED**, then back to **ARMED**; rescue logged to history. |

Switch to **Advisory** on the Settings page and the same run stops at step 5
with a recommendation and a Confirm button. Same engine, same selection — only
the trigger-pull moves.

**Reset position** restores the seed position at any time.

### Decision Trace

The dashboard's Decision Trace panel renders the backend's `decision_trace`
block verbatim -- scenario, risk level, strategies generated, strategies
rejected, the selected strategy, why it won, the execution result and the final
Health Factor -- followed by the stage log with the shield state on every line.
If the panel is wrong, the engine is wrong, which is the property that makes it
worth having.

Verify it independently at any time:

```bash
curl -s -X POST localhost:8001/api/demo/simulate-drop -H "Content-Type: application/json" -d "{\"price_drop_pct\":10}"
```


### Scenario prediction

The Scenarios page projects the position across `Current / -5% / -10% / -15% /
-20%`. Each rung is recomputed by the scenario engine — new price, revalued
collateral, Health Factor, risk band, whether intervention is required, and the
minimum repayment or collateral top-up it would take. The Recharts line marks
three thresholds, all served by the API rather than hard-coded in the chart:
the **target**, the **intervention trigger** (where the agent acts), and the
**liquidation line** at 1.00.

Note the distinction the `requires_intervention` flag draws: a rung can need
intervention while still being solvent, because the agent acts *before* the
liquidation line, not at it.

> Scenario simulation shows how the position could behave under different market
> conditions. These are simulated scenarios, not guaranteed predictions.

## Market data

The current **ETH/USD spot price is real**. It is read from public,
keyless market-data APIs by `backend/app/services/market_data.py` and served
to the frontend through `GET /api/market/eth-price`.

| | |
| --- | --- |
| **Providers** | Coinbase → CoinGecko → Kraken, tried in order |
| **Credentials** | None. All three are free and keyless, so there is no secret that could leak |
| **Timeout** | 5s per provider, then fall through to the next |
| **Caching** | 60s TTL shared by every caller; a forced refresh is floored at 5s |
| **Validation** | Non-numeric, null, zero, negative, NaN, infinite and implausible values are all treated as a failed read |

### What is real and what is not

| Real | Simulated |
| --- | --- |
| Current ETH/USD spot price | Every price derived from it (−5/−10/−15/−20%) |
| The timestamp it was read at | Every projected Health Factor |
| The provider it came from | Every protection strategy and its costing |
| | The rescue execution and its receipt |

**The scenario engine stress-tests a position; it does not forecast.** A −20%
rung is a "what if", not a claim about where ETH is going. Nothing in this
system predicts future prices, and no part of the UI says otherwise.

### How real data flows

```
React  ──►  FastAPI  ──►  market_data.py  ──►  public price API
  ▲                            │
  │                           real ETH/USD spot price
  │                            ▼
  └──── dashboard ◄──── Risk Engine ──► Scenario Engine ──► Strategy Engine ──► Supabase
```

The browser never calls a market API directly. It only ever talks to the
backend, which owns the providers, the timeouts and the rate limiting.

### When the market is unreachable

The application does not crash and does not invent a price. The panel shows
**"Live market data unavailable."**, the price in use is relabelled
**"Demo / manual price"**, and the user carries on with a manually entered
figure — the risk, scenario and strategy engines behave identically either way.
Verified by test and in the browser.

### Refreshing

**Refresh ETH price** on the dashboard re-reads the price, recalculates the
Health Factor and re-runs the scenarios. It is rate-limited server-side, so
holding down the button produces at most one upstream request every five
seconds rather than one per click.

### Demo Mode with live prices

**Simulate 10% ETH drop** never changes the real market price. It takes the
position's current price — the live one, if you analysed with live pricing —
and stress-tests at `price × 0.90`. Verified: with a live price of $2,448.07
the demo ran the cycle at $2,203.

---

### Supported assets

The form's dropdown is served by `GET /api/assets`, so adding an asset is a
backend-only change and the risk parameters can never drift between the two
sides. The browser never chooses a liquidation threshold.

| Asset | Simulated threshold | Aave v3 equivalent | Liquidation penalty |
| --- | --- | --- | --- |
| ETH | 0.625 | 0.825 | 5% |
| BTC | 0.650 | 0.780 | 6% |
| USDC | 0.850 | 0.870 | 4% |
| DAI | 0.800 | 0.820 | 5% |
| SOL | 0.550 | 0.650 | 8% |
| LINK | 0.550 | 0.680 | 7% |
| ARB | 0.450 | 0.550 | 9% |

Every simulated tier is more conservative than its mainnet counterpart, and a
test enforces that ordering: a position that looks safe here would look safer
still on Aave.

**The ETH tier is the one number to know about.** 0.625 is what makes the demo
position report Health Factor 1.25 on $10,000 of collateral against $5,000 of
debt, which is the whole demo narrative. Real Aave v3 ETH is 0.825 — at that
threshold the same position sits at 1.65 and needs no rescue at all. To model
the real market, send `liquidation_threshold` explicitly on the position; the
API honours it over the catalogue default.

Debt is restricted to stablecoins (USDC, DAI) because the risk engine values
debt at $1 per unit. A volatile debt asset would need its own price feed in the
Health Factor denominator, and silently pretending otherwise would be wrong
rather than merely unsupported.

### Validation

Handled at three layers, so a bad value is caught by whichever is closest to
the user: the form (friendly, per-field, focuses the first offender), the
Pydantic schema (422 with the field named), and the risk engine (the authority,
unit-tested).

| Input | Message |
| --- | --- |
| Empty collateral | "Please enter a valid collateral amount." |
| Negative collateral | "Collateral cannot be negative." |
| Zero collateral with debt | "A position with debt must have collateral securing it." |
| Negative debt | "Debt cannot be negative." |
| Zero or negative price | "Asset price must be greater than zero." |
| Target Health Factor at or below 1.00 | "Target Health Factor must be above 1.00 — anything lower offers no protection." |
| Trigger above target | "The trigger cannot be above the target — the agent would act after it was already too late." |
| Unsupported asset | "Unsupported collateral asset. Choose one of: …" |

### The eight-step workflow

The Dashboard shows a progress rail derived from the backend's trace, not from
a client-side script:

```
1 Enter position → 2 Analyze → 3 Current risk → 4 Future scenarios
→ 5 Strategies generated → 6 Best strategy selected
→ 7 Simulated protection → 8 Position protected
```

Steps the engine legitimately never reaches are marked **skipped** rather than
left looking stuck: analysing a safe position completes steps 1-4 and skips
5-8, and a stand-down marks 5-8 skipped with the reason.

### Seeing the edge cases

Every rejection path is reachable from the Settings page without touching code:

| To see | Set on Settings |
| --- | --- |
| Insufficient DEX liquidity | DEX liquidity `5000`, available capital `0` |
| Very high slippage | DEX liquidity `30000`, max pool utilisation `0.95` |
| Uneconomical rescue | Gas price `60`, then set debt to `500` and collateral to `0.3` on the Position page |
| Strategy cannot reach target | Always visible — `Minimal partial repayment` is in every run |
| No rescue required | Reset the position (HF 1.25 is above the trigger) |
| Invalid input | Enter a negative or zero value on the Position page |

---

## Folder structure

```
hack/
├── backend/
│   ├── app/
│   │   ├── main.py                    FastAPI app, CORS, error handling
│   │   ├── config.py                  env-driven settings, no hard-coded secrets
│   │   ├── api/routes.py              HTTP adapter — parse, delegate, serialise
│   │   ├── models/domain.py           dataclasses + enums, zero dependencies
│   │   ├── schemas/api.py             pydantic request/response shapes
│   │   └── services/
│   │       ├── agent_cycle.py         one full cycle: shock -> decide -> execute -> trace
│   │       ├── assets.py              collateral catalogue and market tiers
│   │       ├── market_data.py         REAL ETH/USD price, public keyless APIs
│   │       ├── risk_engine.py         Health Factor, classification, sizing formulas
│   │       ├── scenario_engine.py     price-shock ladder + projections
│   │       ├── strategy_engine.py     generation, costing, scoring, selection
│   │       └── repository.py          Supabase / in-memory persistence
│   ├── tests/                         291 tests across engines and API
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   └── src/
│       ├── api/client.js              the only module that talks to the backend
│       ├── lib/shieldStates.js        presentation for each backend state
│       ├── lib/workflow.js            derives the eight steps from the trace
│       ├── state/ShieldContext.jsx    API calls + trace replay (no logic)
│       ├── components/
│       │   ├── HealthFactorGauge.jsx  the radial shield-arc gauge
│       │   ├── StatusBar.jsx          renders the backend's shield state
│       │   ├── PositionForm.jsx       "Analyze your position" input form
│       │   ├── StepIndicator.jsx      eight-step rail, derived from the trace
│       │   ├── ProtectionModal.jsx    risk alert raised on DANGER/LIQUIDATABLE
│       │   ├── DecisionTrace.jsx      the backend's decision_trace, verbatim
│       │   ├── DemoControls.jsx       demo trigger + replayed stage log
│       │   ├── Shell.jsx, ui.jsx
│       └── pages/
│           ├── Landing.jsx           the control-center entrance at /
│           └── Dashboard, Position, Scenarios, Strategies,
│               Comparison, History, Settings  (the portal, at /portal/*)
├── supabase/schema.sql                tables, constraints, RLS
└── README.md
```

---

## Architecture

```
Frontend (React) → FastAPI → Risk Engine → Scenario Engine → Strategy Engine → Supabase
```

Later, not now:

```
Strategy Engine → Protection Smart Contract → Lending Protocol → DEX / Flash Loan
```

Two rules hold this together:

- **No blockchain logic in the frontend.** The React app imports no web3
  library, signs nothing, and knows nothing about flash loans. Every number on
  screen came out of a Python engine over HTTP.
- **No business logic in the routes.** If a rule cannot be unit-tested without
  starting a web server, it is in the wrong file. The engines are pure and
  import no framework code.
- **No risk parameters in the browser.** Picking BTC changes the liquidation
  threshold because `services/assets.py` says so. The form posts an asset
  symbol; the server resolves the threshold, the penalty and the close factor.
- **No state machine in the browser.** `ShieldState` lives in
  `models/domain.py`; `services/agent_cycle.py` decides which state each stage
  is in. The frontend looks the state up in a presentation table and renders
  it. The single exception is the in-flight `PROTECTING` shown while the
  Advisory confirm request is still open -- the server cannot report "currently
  executing" until it has returned -- and it is commented as such at the call
  site.

### API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Service and engine status |
| POST | `/api/position/analyze` | Health Factor, risk band, liquidation price, headroom |
| POST | `/api/scenario/simulate` | Price-shock ladder with projected interventions |
| POST | `/api/strategies/generate` | Candidates, costed, constraint-checked, scored |
| POST | `/api/strategies/compare` | The same run projected onto comparison columns |
| POST | `/api/rescue/validate` | Pre-flight: would the agent execute, and why/why not |
| POST | `/api/rescue/autoexecute` | Simulated autonomous execution |
| POST | `/api/demo/simulate-drop` | One full agent cycle, server-side: shock, recalc, generate, score, select, execute, trace |
| GET | `/api/history` | Executed rescues, newest first |
| GET | `/api/market/eth-price` | **Real** ETH/USD spot price. `?refresh=true` bypasses the cache |
| GET | `/api/assets` | Collateral catalogue with the simulated market parameters |
| GET | `/api/defaults` | Seed position/preferences/market for the UI bootstrap |

---

## The maths

All formulas live in `backend/app/services/risk_engine.py`, each with its
derivation in the docstring. Nothing is a placeholder or a random number.

**Health Factor**

```
HF = (collateral_value × liquidation_threshold) / debt_value
```

The seed position — $10,000 collateral, $5,000 debt, liquidation threshold
0.625 — reports HF 1.25 exactly, and liquidates at ETH $2,400 (20% below spot).
The 0.625 threshold is the demo market tier; real Aave v3 ETH is 0.825, and it
is a per-position field you can change on the Position page.

**Minimum repayment to reach a target** (externally funded)

```
HF_target = (C × LT) / (D − R)   ⟹   R = D − (C × LT) / HF_target
```

Clamped at zero when the position already meets the target (edge case 6), and
at D because you cannot repay more debt than exists. At $9,000 collateral
against $5,000 debt, restoring HF 1.5 takes exactly $1,250.

**Minimum collateral top-up**

```
HF_target = ((C + ΔC) × LT) / D   ⟹   ΔC = (HF_target × D) / LT − C
```

**Self-funded repayment** (sell collateral to repay — the deleverage routes)

Both sides of the ratio move, so it is a different equation, and structurally
less capital-efficient:

```
HF_target = ((C − R(1+s)) × LT) / (D − R)
R = (C×LT − HF_target×D) / ((1+s)×LT − HF_target)
```

Because the swap cost `s` depends on trade size and trade size depends on `s`,
the strategy engine solves this by fixed-point iteration. It returns "no
solution" when the position is insolvent (collateral worth less than debt),
which is exactly when deleveraging cannot help.

**Economic viability**

```
potential_loss = debt × close_factor × liquidation_bonus
rescue_cost    = gas + slippage + flash_loan_fee
```

If `rescue_cost > potential_loss` the agent returns
`Rescue skipped – economically unviable.` and stands down. Spending $32 to
avoid losing $12 is worse than doing nothing; an agent that executes anyway is
not autonomous, just automatic.

**Cost model** (simulated, all in `strategy_engine.py`)

```
gas       = gas_units × gas_price_gwei × 1e-9 × eth_price
slippage  = pool_fee + trade/(depth + trade)      (constant-product shape)
flash fee = flash_loan_fee_pct × flashed amount
```

**Composite score** — five sub-scores in [0,1], weighted and normalised:
safety (resulting HF, discounted for execution risk), cost (against the loss
prevented), slippage (headroom inside tolerance), liquidity (share of routable
depth consumed), capital (idle funds locked up). Change the weights on the
Settings page and the selection changes with them.

### Risk bands

| Health Factor | Band |
| --- | --- |
| `< 1.00` | LIQUIDATABLE |
| `1.00 – 1.20` | DANGER |
| `1.20 – 1.50` | WARNING |
| `≥ 1.50` | SAFE |

The agent intervenes at or below HF 1.20 and sizes every rescue to restore
exactly 1.50. Both are user settings, and the bands themselves are served from
`GET /api/defaults` so the UI never carries its own copy of the thresholds.

---

## Supabase setup

The app runs **without** Supabase — persistence falls back to an in-process
store and the status bar shows `STORE in-memory`. Set it up when you want the
rescue history to survive a restart.

1. Create a project at [supabase.com](https://supabase.com).
2. Open **SQL Editor → New query**, paste the contents of
   `supabase/schema.sql`, and run it. It is idempotent and seeds the demo user.
3. Copy `backend/.env.example` to `backend/.env`.
4. From **Project Settings → Data API**, copy the Project URL into
   `SUPABASE_URL`.
5. From **Project Settings → API Keys**, copy the **service role** key into
   `SUPABASE_SERVICE_KEY`.
6. Restart the backend. `GET /api/health` should now report
   `"persistence": "supabase"`.

Tables: `users`, `positions`, `scenarios`, `protection_strategies`,
`rescue_transactions`.

**Security notes.** The service role key is server-side only — it bypasses Row
Level Security and must never reach the browser or any `VITE_*` variable. RLS
is enabled on every table with no permissive policies, so anon and
authenticated roles can read and write nothing until you add per-user policies
alongside Supabase Auth. A database constraint enforces that any row marked
`simulated` carries a `0xSIM` hash, so simulated and real receipts can never be
confused. Writes are best-effort: a logging failure never takes down a rescue.

---

## What is simulated

| **Component** | **Status** |
|---|---|
| Health Factor, risk classification, liquidation price | **Real logic**, simplified single-asset model |
| Repayment / top-up / deleverage sizing | **Real formulas** |
| Strategy generation, scoring, selection | **Real logic** |
| Economic viability and constraint checks | **Real logic** |
| ETH/USD spot price | **REAL** — obtained from public market-data APIs |
| Scenario prices (-5% / -10% / -15% / -20%) | **Simulated projections** derived from the real ETH price |
| Gas price | **Simulated** — modeled calculation, no gas oracle |
| DEX liquidity and slippage | **Simulated** — modeled calculation, no live pool query |
| Flash loan | **Simulated** — Aave v3 0.09% premium modeled arithmetically; no real flash loan |
| Blockchain execution | **Simulated** — no transaction signing or broadcasting; uses `0xSIM` hashes |
| Wallet / account abstraction | **Not present** |

### Blockchain Status

The current hackathon MVP does **not** connect to a real blockchain.

There is:

- No real wallet connection
- No smart contract deployment
- No real flash loan
- No real transaction signing
- No real transaction broadcasting
- No real cryptocurrency transfer

The selected protection strategy is executed through a **simulated execution flow** and produces a simulated transaction receipt. :contentReference[oaicite:1]{index=1}

### Real Market Data

The current ETH/USD spot price is real and is obtained through public market-data APIs. The backend tries Coinbase, CoinGecko, and Kraken in order. :contentReference[oaicite:2]{index=2}

The scenario engine then uses that real price to calculate the `-5%`, `-10%`, `-15%`, and `-20%` what-if scenarios. These are stress-test scenarios, not predictions of the future ETH price. :contentReference[oaicite:3]{index=3}

The simplifications in the risk model, stated plainly (they are also in the
module docstring):

- One collateral asset and one debt asset. Real accounts hold baskets, and a
  real Health Factor sums each reserve weighted by its own threshold.
- The debt asset is assumed to be worth exactly $1. A volatile debt asset needs
  its own price feed in the denominator.
- Interest accrual between blocks is ignored; balances are point-in-time.
- Oracle price is assumed equal to spot. Real protocols use a lagging oracle,
  so the protocol's view of your Health Factor can differ from the DEX price
  for a few blocks.

---

## ⛓️ Blockchain Integration

Blockchain technology is planned as the execution layer of the Automated Liquidation Shield.

The purpose of using blockchain is to make the protection process transparent, verifiable, and suitable for automated DeFi transactions.

### Current Implementation

In the current hackathon MVP, blockchain execution is **simulated**.

The system does not connect to a real blockchain, does not require a wallet, and does not transfer real cryptocurrency.

Instead, the system demonstrates the complete execution workflow using a simulated transaction receipt.

### Simulated Blockchain Workflow

The current hackathon MVP demonstrates the blockchain execution flow through simulation. The system does not sign or broadcast real blockchain transactions.

```text
Risk Detection
      ↓
Scenario Analysis
      ↓
Protection Strategy Generation
      ↓
Strategy Comparison
      ↓
User Selects Strategy
      ↓
Strategy Validation
      ↓
Simulated Blockchain Execution
      ↓
Simulated Transaction Receipt
      ↓
Position Recalculation
      ↓
Updated Health Factor
      ↓
Rescue History
```

### How the Simulation Works

1. **Risk Detection**  
   The backend calculates the current Health Factor and determines the position's risk level.

2. **Scenario Analysis**  
   The system evaluates how the position could behave under different ETH price scenarios such as `-5%`, `-10%`, `-15%`, and `-20%`.

3. **Protection Strategy Generation**  
   The backend generates possible protection strategies such as debt repayment, collateral top-up, and deleveraging.

4. **Strategy Comparison**  
   Each strategy is checked against constraints such as available capital, required amount, expected Health Factor, cost, and risk after execution.

5. **User Selects Strategy**  
   The user can select a feasible protection strategy from the available recommendations.

6. **Strategy Validation**  
   The backend validates the selected strategy before execution and checks whether it satisfies the required constraints.

7. **Simulated Blockchain Execution**  
   The selected strategy is processed through the simulated blockchain execution layer.

8. **Simulated Transaction Receipt**  
   The system generates a simulated transaction receipt containing execution information. No real transaction is signed or broadcast.

9. **Position Recalculation**  
   After the simulated execution, the position is recalculated using the updated collateral and debt values.

10. **Updated Health Factor**  
    The system calculates the new Health Factor and displays the updated risk status.

11. **Rescue History**  
    The simulated execution is recorded in the application's rescue history for demonstration purposes.

### Blockchain Execution Status

| Component | Current MVP |
|---|---|
| Blockchain network | Simulated |
| Smart contract | Not deployed |
| Wallet connection | Not implemented |
| Transaction signing | Simulated |
| Transaction broadcasting | Not implemented |
| Real cryptocurrency transfer | No |
| Transaction receipt | Simulated |
| Rescue execution | Simulated |

> **Important:** The blockchain execution layer is simulated for the hackathon demonstration. The core risk analysis, Health Factor calculation, scenario analysis, strategy generation, strategy comparison, and recommendation logic are implemented in the application.

---

## 🔮 Future Real-Blockchain Integration

The simulated execution layer can later be replaced with real blockchain infrastructure.

### Planned Integration

1. **Chainlink Price Feed**  
   Replace the current market-price source with an on-chain Chainlink price feed.

2. **Aave Position Data**  
   Replace the demo position with real Aave account data using `getUserAccountData`.

3. **Real Gas Estimation**  
   Replace the simulated gas calculation with an EIP-1559 gas-fee estimate.

4. **DEX Integration**  
   Replace simulated liquidity and slippage calculations with real Uniswap v3 Quoter and pool-liquidity data.

5. **Protection Smart Contract**  
   Deploy a smart contract capable of executing supported protection strategies atomically.

6. **Wallet Integration**  
   Integrate a Web3 wallet such as MetaMask for user authorization and transaction signing.

7. **Continuous Monitoring**  
   Replace request-based evaluation with a continuously running blockchain monitoring service.

### Future Blockchain Flow

```text
User Wallet
      ↓
React Frontend
      ↓
FastAPI Backend
      ↓
Risk & Strategy Engine
      ↓
Protection Smart Contract
      ↓
DeFi Protocol
      ↓
Blockchain
      ↓
Transaction Confirmation
```

> The current implementation is a hackathon MVP. Real on-chain execution is planned as a future extension and is not used to move real user funds in the current version.

---

## ⚠️ Known Limitations

- **Not investment advice and not audited.** This is a hackathon MVP.

- The demo position lives in browser memory. A page reload resets it to the seed position. Only executed rescues persist.

- The system currently supports a single position and a single user. There is no authentication layer, and the backend writes using a fixed demo user ID.

- The current model supports one collateral asset and one debt asset per position. Real DeFi accounts can contain multiple assets, and a production Health Factor calculation would account for each reserve using its own liquidation threshold.

- Only ETH has a live market price in the current implementation. Other assets use the value entered by the user.

- The live ETH price is a spot-market read rather than a protocol oracle value. A real DeFi protocol may use an oracle price, so its Health Factor can differ from the spot-price calculation for a period of time.

- Scenario analysis uses deterministic instantaneous price shocks. The scenarios do not assign probabilities to future price movements. A production version could incorporate stochastic market models.

- Execution risk is currently represented using a fixed per-strategy discount rather than live mempool or network conditions.

- Interest accrual is not currently modeled. Therefore, the Health Factor changes primarily in response to changes in collateral price.

- The frontend bundle is currently a single large chunk. Recharts contributes significantly to the bundle size, and code-splitting has not been prioritized for the hackathon MVP.

- The demo replays the backend execution trace on a fixed 750 ms interval rather than streaming individual stages as they complete. A production implementation could use Server-Sent Events (SSE) or WebSockets.

---

## 🛠️ Troubleshooting

### "Protection service unreachable"

The backend is not running or is running on a different port.

Check the backend health endpoint:

```text
http://localhost:8001/api/health
```

Make sure the FastAPI backend is running before starting or using the frontend.

### `pip install` fails while building `pydantic-core`

This can occur when using a newer Python version with an older pinned Pydantic version.

The project requirements should use a compatible Pydantic version. If `requirements.txt` has been modified, ensure that Pydantic is compatible with the Python version being used.

### Health says `"persistence": "in-memory"` with Supabase configured

This means the Supabase credentials may be missing, invalid, or the Supabase project may be unreachable.

The backend is designed to fall back to in-memory persistence instead of failing completely.

Check:

- Supabase environment variables
- Backend console logs
- Supabase project availability
- Network connectivity

---


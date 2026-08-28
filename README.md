# Automated Liquidation Shield

<!-- BADGES: the CI badge path is rewritten once the GitHub remote exists. -->
[![CI](https://github.com/OWNER/REPO/actions/workflows/ci.yml/badge.svg)](https://github.com/OWNER/REPO/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-2DD9A8.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-238%20passing-2DD9A8.svg)](#tests)
[![Status](https://img.shields.io/badge/status-prototype%20%C2%B7%20simulated-E8A33D.svg)](#what-is-simulated)

**Autonomous, scenario-driven liquidation protection for a DeFi lending position.**

<!-- TEAM:START — replace every placeholder below before submitting. -->
## Team

| | |
| --- | --- |
| **Team name** | `_TO BE FILLED_` |
| **Institution** | `_TO BE FILLED_` |
| **Problem statement / track** | `_TO BE FILLED_` |

| Name | Role | GitHub |
| --- | --- | --- |
| `_TO BE FILLED_` | `_TO BE FILLED_` | [@handle](https://github.com/handle) |
| `_TO BE FILLED_` | `_TO BE FILLED_` | [@handle](https://github.com/handle) |
| `_TO BE FILLED_` | `_TO BE FILLED_` | [@handle](https://github.com/handle) |
| `_TO BE FILLED_` | `_TO BE FILLED_` | [@handle](https://github.com/handle) |
<!-- TEAM:END -->

## At a glance

| | |
| --- | --- |
| **What it does** | Watches a DeFi borrow position, predicts how it behaves under future price shocks, generates and scores several rescue strategies, and executes the best one autonomously |
| **Stack** | React 19 · Vite · Tailwind v4 · Recharts · FastAPI · Python 3.13+ · Supabase (optional) |
| **Tests** | 238, covering the engines, the API and all eight edge cases |
| **Blockchain** | **None.** Fully simulated — see [What is simulated](#what-is-simulated) |
| **Run it** | [Quick start](#quick-start) — two terminals, no credentials needed |

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
uvicorn app.main:app --reload --port 8000
```

- API: <http://localhost:8000/api/health>
- Interactive docs: <http://localhost:8000/docs>

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
`http://127.0.0.1:8000`, so there is no CORS setup and no API URL in the
bundle. Override the target with `VITE_API_TARGET` if your backend runs
elsewhere.

### Tests

```bash
cd backend && python -m pytest
```

238 tests: the risk, scenario, strategy and agent-cycle engines, the asset
catalogue, user-entered positions, and every HTTP endpoint.
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
curl -s -X POST localhost:8000/api/demo/simulate-drop -H "Content-Type: application/json" -d "{\"price_drop_pct\":10}"
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
│   │       ├── risk_engine.py         Health Factor, classification, sizing formulas
│   │       ├── scenario_engine.py     price-shock ladder + projections
│   │       ├── strategy_engine.py     generation, costing, scoring, selection
│   │       └── repository.py          Supabase / in-memory persistence
│   ├── tests/                         238 tests across engines and API
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

| Component | Status |
| --- | --- |
| Health Factor, risk classification, liquidation price | **Real logic**, simplified single-asset model |
| Repayment / top-up / deleverage sizing | **Real formulas**, derived in the docstrings |
| Strategy generation, scoring, selection | **Real logic** |
| Economic viability and constraint checks | **Real logic** |
| ETH price | Simulated — a number you set, no oracle |
| Gas price | Simulated — `gas_units × gwei × price`, no gas oracle |
| DEX liquidity and slippage | Simulated — constant-product shape, no pool query |
| Flash loan | Simulated — the Aave v3 0.09% premium as arithmetic only |
| Execution | Simulated — nothing signed, nothing broadcast, `0xSIM` hashes |
| Wallet / account abstraction | Not present |

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

## Future blockchain integration

**None of this is required for the current prototype, and none of it is
implemented.** There is no wallet connection, no smart contract, no flash loan
and no transaction of any kind. The prototype is complete and demonstrable
exactly as it stands; this section describes a later phase.

A future version could integrate:

- **Wallet connection** — read a real account's positions instead of a typed form
- **Smart contracts** — a protection contract that performs the rescue atomically
- **Lending protocols** — live Aave v3 reserve data and `getUserAccountData`
- **DEX swaps** — real Uniswap v3 routing and quotes in place of the modelled pool
- **Flash loans / flash liquidity** — a real Aave premium on a real flashed amount
- **Real transaction execution** — signing and broadcasting, with the simulated
  path kept as a dry run

Today the chain half of that pipeline is replaced by one step:

```
Strategy Engine → Simulated Execution → Verification
```

Later it becomes:

```
Strategy Engine → Smart Contract → Lending Protocol → DEX → Flash Liquidity
```

The seams are already isolated. In rough order:

1. **Price feed** — replace `MarketConditions.eth_price` with a Chainlink
   aggregator read. One function, no downstream changes.
2. **Position read** — replace `Position` construction with Aave's
   `getUserAccountData`, and swap `risk_engine.health_factor` for the
   protocol's own figure. The rest of the engine consumes the same interface.
3. **Gas oracle** — replace `estimate_gas_cost` with an EIP-1559 fee estimate.
4. **DEX quoter** — replace `estimate_slippage_pct` and
   `has_sufficient_liquidity` with a Uniswap v3 Quoter call and real pool
   depth. This is the largest fidelity gain: the constant-product shape is a
   stand-in for real tick liquidity.
5. **Protection contract** — a contract that takes a flash loan, repays debt,
   withdraws and swaps collateral, and repays the loan atomically.
   `strategy_engine.apply_strategy` is the call site.
6. **Signing and submission** — a keeper wallet or session key with a spend
   limit, plus private-mempool submission so the rescue is not front-run.
7. **Continuous monitoring** — the agent currently evaluates on request. A real
   deployment needs a block-subscribed worker loop.

None of steps 1–4 change any engine's interface. Steps 5–7 are new
infrastructure, not rewrites.

---

## Known limitations

- **Not investment advice, and not audited.** This is a hackathon MVP.
- The demo position lives in browser memory. A page reload resets it to the
  seed — only executed rescues persist.
- Single position, single user. There is no auth; the backend writes as a fixed
  demo user id.
- One collateral and one debt asset per position. Real accounts hold baskets,
  and a real Health Factor sums each reserve at its own threshold.
- Asset prices are typed in, not fetched. There is no oracle, so nothing stops
  you entering an ETH price of $9.
- Scenarios are deterministic instantaneous shocks with no probability
  attached. A production version would layer on a stochastic path model.
- Execution risk is modelled as a fixed per-strategy discount, not derived from
  live mempool conditions.
- No interest accrual, so a position's Health Factor only moves when the price
  does.
- The frontend bundle is a single 648 kB chunk (194 kB gzipped) — Recharts
  dominates it. Code-splitting was not worth the complexity at this size.
- `npm run lint` reports four warnings: three `set-state-in-effect` from the
  props-to-draft sync in the form pages, and one `only-export-components` for
  the `useShield` hook. Both patterns are intentional and contained.
- The demo replays the backend's trace on a fixed 750 ms beat rather than
  streaming stages as they complete. A production version would stream over
  SSE or a WebSocket; the response shape already supports it. The pacing is
  skipped entirely in a background tab, where browsers clamp timers hard enough
  to freeze the walk mid-rescue.

---

## Troubleshooting

**"Protection service unreachable"** — the backend is not running, or is on a
different port. Check <http://localhost:8000/api/health>.

**`pip install` fails building `pydantic-core`** — you are on Python 3.14 with
a pinned pydantic older than 2.12. `requirements.txt` already pins 2.13.4;
if you edited it, keep pydantic at 2.12 or newer.

**Health says `"persistence": "in-memory"` with Supabase configured** — the
credentials are missing or the project is unreachable. The backend logs a
warning at startup and falls back rather than failing; check the console.

---

## Licence

[MIT](LICENSE). See [SECURITY.md](SECURITY.md) for how credentials are handled
and what the CI pipeline checks.

## Pipeline

`.github/workflows/ci.yml` runs on every push and pull request:

- **Backend** — installs `backend/requirements.txt`, runs the full `pytest`
  suite, and verifies the FastAPI app imports cleanly.
- **Frontend** — `npm ci`, lint, production build.
- **Security** — a blocking secret scan (committed `.env`, populated service
  keys, private keys, Supabase JWTs) plus non-blocking `pip-audit` and
  `npm audit` dependency advisories.

The split is deliberate: a red light tells you which of the three broke.

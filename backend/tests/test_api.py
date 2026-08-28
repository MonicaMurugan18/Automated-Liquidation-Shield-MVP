"""API-level tests: every endpoint in the brief, plus the edge cases as they
surface over HTTP."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.repository import reset_repository

client = TestClient(app)

DROPPED = {"collateral_price": 2700.0}       # -10%, HF 1.125 -> needs rescue
THIN_POOL = {"dex_liquidity_usd": 5000.0}
EXPENSIVE_GAS = {"gas_price_gwei": 60.0}
SMALL_POSITION = {"collateral_amount": 0.3, "debt_amount": 500.0, "collateral_price": 3000.0}


@pytest.fixture(autouse=True)
def _clean_repository():
    reset_repository()
    yield
    reset_repository()


# ---------------------------------------------------------------------------
# GET /api/health
# ---------------------------------------------------------------------------

def test_health_endpoint():
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["engines"]["blockchain"] == "simulated"


def test_root_advertises_simulation():
    assert client.get("/").json()["blockchain"] == "simulated"


# ---------------------------------------------------------------------------
# POST /api/position/analyze
# ---------------------------------------------------------------------------

def test_analyze_defaults_to_the_seed_position():
    r = client.post("/api/position/analyze", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["assessment"]["health_factor"] == pytest.approx(1.25, abs=1e-4)
    assert body["assessment"]["risk_level"] == "WARNING"
    assert body["assessment"]["liquidation_price"] == pytest.approx(2400.0, abs=0.01)
    assert body["assessment"]["requires_action"] is False


def test_analyze_after_a_price_drop_requires_action():
    r = client.post("/api/position/analyze", json={"position": DROPPED})
    body = r.json()["assessment"]
    assert body["health_factor"] == pytest.approx(1.125, abs=1e-4)
    assert body["risk_level"] == "DANGER"
    assert body["requires_action"] is True


def test_analyze_rejects_negative_collateral():
    """Edge case 8, caught by the schema before it reaches the engine."""
    r = client.post("/api/position/analyze", json={"position": {"collateral_amount": -1}})
    assert r.status_code == 422


def test_analyze_rejects_a_zero_price():
    r = client.post("/api/position/analyze", json={"position": {"collateral_price": 0}})
    assert r.status_code == 422


def test_analyze_rejects_a_target_below_the_liquidation_line():
    r = client.post(
        "/api/position/analyze",
        json={"preferences": {"target_health_factor": 0.9}},
    )
    assert r.status_code == 422


def test_analyze_rejects_unknown_fields():
    r = client.post("/api/position/analyze", json={"position": {"leverage": 10}})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/scenario/simulate
# ---------------------------------------------------------------------------

def test_scenario_ladder_matches_the_brief():
    r = client.post("/api/scenario/simulate", json={})
    assert r.status_code == 200
    scenarios = r.json()["scenarios"]

    assert [s["label"] for s in scenarios] == ["Current", "-5%", "-10%", "-15%", "-20%"]
    assert [s["new_price"] for s in scenarios] == [3000.0, 2850.0, 2700.0, 2550.0, 2400.0]
    assert [s["health_factor"] for s in scenarios] == pytest.approx(
        [1.25, 1.1875, 1.125, 1.0625, 1.0], abs=1e-4
    )
    assert all("intervention_summary" in s for s in scenarios)


def test_scenario_accepts_a_custom_ladder_and_finds_the_break():
    r = client.post("/api/scenario/simulate", json={"price_drops": [0, 25, 40]})
    body = r.json()
    assert body["first_breaking_scenario"]["label"] == "-25%"
    assert "liquidates" in body["summary"]


def test_scenario_rejects_an_impossible_drop():
    r = client.post("/api/scenario/simulate", json={"price_drops": [150]})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/strategies/generate
# ---------------------------------------------------------------------------

def test_generate_returns_scored_candidates_with_one_selected():
    r = client.post("/api/strategies/generate", json={"position": DROPPED})
    assert r.status_code == 200
    body = r.json()

    assert len(body["strategies"]) == 5
    assert body["selected_strategy"] is not None
    assert sum(1 for s in body["strategies"] if s["selected"]) == 1
    assert body["selected_strategy"]["resulting_health_factor"] >= 1.5


def test_generate_returns_no_candidates_for_a_safe_position():
    """Edge case 1: nothing to do, and the API says so rather than inventing
    a strategy."""
    r = client.post("/api/strategies/generate", json={})
    body = r.json()
    assert body["strategies"] == []
    assert body["selected_strategy"] is None


def test_generate_marks_the_undersized_candidate_invalid():
    """Edge case 7 visible over HTTP."""
    r = client.post("/api/strategies/generate", json={"position": DROPPED})
    partial = next(
        s for s in r.json()["strategies"] if s["strategy_type"] == "PARTIAL_DELEVERAGE"
    )
    assert partial["status"] == "INVALID_CANNOT_REACH_TARGET"
    assert partial["is_executable"] is False


def test_generate_rejects_thin_liquidity():
    """Edge case 4 visible over HTTP."""
    r = client.post(
        "/api/strategies/generate",
        json={"position": DROPPED, "market": THIN_POOL},
    )
    swap = next(
        s for s in r.json()["strategies"] if s["strategy_type"] == "COLLATERAL_SWAP"
    )
    assert swap["status"] == "REJECTED_INSUFFICIENT_LIQUIDITY"


def test_generate_rejects_high_slippage():
    """Edge case 3 visible over HTTP."""
    r = client.post(
        "/api/strategies/generate",
        json={
            "position": DROPPED,
            "market": {"dex_liquidity_usd": 30000.0, "max_pool_utilisation": 0.95},
        },
    )
    swap = next(
        s for s in r.json()["strategies"] if s["strategy_type"] == "COLLATERAL_SWAP"
    )
    assert swap["status"] == "REJECTED_HIGH_SLIPPAGE"


# ---------------------------------------------------------------------------
# POST /api/strategies/compare
# ---------------------------------------------------------------------------

def test_compare_returns_the_full_matrix_and_the_weights():
    r = client.post("/api/strategies/compare", json={"position": DROPPED})
    assert r.status_code == 200
    body = r.json()

    assert len(body["rows"]) == 5
    assert sum(1 for row in body["rows"] if row["selected"]) == 1
    assert body["weights"] == pytest.approx(
        {"safety": 0.40, "cost": 0.25, "slippage": 0.15, "liquidity": 0.10, "capital": 0.10}
    )
    for row in body["rows"]:
        assert {
            "resulting_health_factor", "required_capital", "slippage_pct",
            "gas_cost", "flash_loan_fee", "total_cost", "score",
        } <= set(row)


def test_compare_explanation_names_the_winner():
    body = client.post("/api/strategies/compare", json={"position": DROPPED}).json()
    assert body["selected_strategy"]["name"] in body["explanation"]


# ---------------------------------------------------------------------------
# POST /api/rescue/validate
# ---------------------------------------------------------------------------

def test_validate_approves_a_viable_rescue():
    r = client.post("/api/rescue/validate", json={"position": DROPPED})
    body = r.json()
    assert body["can_execute"] is True
    assert body["economics"]["net_benefit"] > 0


def test_validate_declines_a_safe_position():
    body = client.post("/api/rescue/validate", json={}).json()
    assert body["can_execute"] is False
    assert body["execution_status"] == "NO_ACTION_REQUIRED"
    assert body["shield_state"] == "ARMED"


def test_validate_declines_an_uneconomical_rescue():
    """Edge case 5 visible over HTTP."""
    body = client.post(
        "/api/rescue/validate",
        json={"position": SMALL_POSITION, "market": EXPENSIVE_GAS},
    ).json()
    assert body["can_execute"] is False
    assert body["execution_status"] == "SKIPPED_UNECONOMICAL"
    assert "economically unviable" in body["reason"]
    assert body["economics"]["net_benefit"] < 0


def test_validate_declines_when_liquidity_is_insufficient():
    body = client.post(
        "/api/rescue/validate",
        json={
            "position": DROPPED,
            "market": THIN_POOL,
            "preferences": {"available_capital": 0.0},
        },
    ).json()
    assert body["can_execute"] is False
    assert "insufficient liquidity" in body["reason"]


# ---------------------------------------------------------------------------
# POST /api/rescue/autoexecute
# ---------------------------------------------------------------------------

def test_autoexecute_runs_without_confirmation_in_autonomous_mode():
    """Edge case 2 and the headline behaviour: the agent acts on its own."""
    r = client.post("/api/rescue/autoexecute", json={"position": DROPPED})
    assert r.status_code == 200
    body = r.json()

    assert body["executed"] is True
    assert body["simulated"] is True
    assert body["execution_status"] == "EXECUTED"
    # The rescue has landed by the time the response returns, so the state is
    # PROTECTED -- PROTECTING is the in-flight state, reported mid-trace.
    assert body["shield_state"] == "PROTECTED"
    assert body["assessment_before"]["health_factor"] == pytest.approx(1.125, abs=1e-4)
    assert body["assessment_after"]["health_factor"] >= 1.5
    assert body["assessment_after"]["risk_level"] == "SAFE"


def test_executed_transaction_is_flagged_as_simulated():
    body = client.post("/api/rescue/autoexecute", json={"position": DROPPED}).json()
    tx = body["transaction"]
    assert tx["simulated"] is True
    assert tx["tx_hash"].startswith("0xSIM")
    assert tx["mode"] == "AUTONOMOUS"


def test_advisory_mode_holds_until_confirmed():
    payload = {
        "position": DROPPED,
        "preferences": {"mode": "ADVISORY"},
    }
    held = client.post("/api/rescue/autoexecute", json=payload).json()
    assert held["executed"] is False
    assert held["execution_status"] == "AWAITING_CONFIRMATION"
    assert held["shield_state"] == "ALERT"
    assert held["selected_strategy"] is not None

    confirmed = client.post(
        "/api/rescue/autoexecute", json={**payload, "confirm": True}
    ).json()
    assert confirmed["executed"] is True
    assert confirmed["transaction"]["mode"] == "ADVISORY"


def test_autoexecute_does_nothing_for_a_safe_position():
    body = client.post("/api/rescue/autoexecute", json={}).json()
    assert body["executed"] is False
    assert body["execution_status"] == "NO_ACTION_REQUIRED"
    assert body["transaction"] is None


def test_autoexecute_skips_an_uneconomical_rescue():
    body = client.post(
        "/api/rescue/autoexecute",
        json={"position": SMALL_POSITION, "market": EXPENSIVE_GAS},
    ).json()
    assert body["executed"] is False
    assert body["execution_status"] == "SKIPPED_UNECONOMICAL"
    assert body["shield_state"] == "SKIPPED"


# ---------------------------------------------------------------------------
# GET /api/history
# ---------------------------------------------------------------------------

def test_history_starts_empty_and_records_executed_rescues():
    assert client.get("/api/history").json()["transactions"] == []

    client.post("/api/rescue/autoexecute", json={"position": DROPPED})
    client.post("/api/rescue/autoexecute", json={"position": {"collateral_price": 2600.0}})

    transactions = client.get("/api/history").json()["transactions"]
    assert len(transactions) == 2
    assert all(t["simulated"] is True for t in transactions)
    # Newest first.
    assert transactions[0]["collateral_price"] == 2600.0


def test_skipped_rescues_are_not_written_to_history():
    client.post(
        "/api/rescue/autoexecute",
        json={"position": SMALL_POSITION, "market": EXPENSIVE_GAS},
    )
    assert client.get("/api/history").json()["transactions"] == []


def test_history_respects_the_limit_parameter():
    for price in (2700.0, 2650.0, 2600.0):
        client.post("/api/rescue/autoexecute", json={"position": {"collateral_price": price}})
    assert len(client.get("/api/history?limit=2").json()["transactions"]) == 2


def test_history_rejects_an_out_of_range_limit():
    assert client.get("/api/history?limit=0").status_code == 422


# ---------------------------------------------------------------------------
# GET /api/defaults
# ---------------------------------------------------------------------------

def test_defaults_bootstraps_the_frontend():
    body = client.get("/api/defaults").json()
    assert body["position"]["collateral_value"] == pytest.approx(10_000.0, abs=0.01)
    assert body["position"]["debt_amount"] == 5_000.0
    assert body["preferences"]["mode"] == "AUTONOMOUS"
    assert body["risk_bands"] == {"liquidatable": 1.0, "danger": 1.20, "warning": 1.50}
    assert body["modes"] == ["AUTONOMOUS", "ADVISORY"]


# ---------------------------------------------------------------------------
# The demo flow, end to end
# ---------------------------------------------------------------------------

def test_demo_flow_armed_to_protecting_to_safe():
    """The exact sequence the Demo Mode button drives in the UI."""
    # 1. ARMED -- healthy position, no action.
    before = client.post("/api/position/analyze", json={}).json()["assessment"]
    assert before["health_factor"] == pytest.approx(1.25, abs=1e-4)
    assert before["requires_action"] is False

    # 2. Simulate -10% -- ALERT.
    dropped = client.post("/api/position/analyze", json={"position": DROPPED}).json()
    assert dropped["assessment"]["requires_action"] is True
    assert dropped["assessment"]["risk_level"] == "DANGER"

    # 3. Generate and score.
    strategies = client.post(
        "/api/strategies/generate", json={"position": DROPPED}
    ).json()
    assert strategies["selected_strategy"] is not None

    # 4. PROTECTING -- autonomous execution.
    rescue = client.post("/api/rescue/autoexecute", json={"position": DROPPED}).json()
    assert rescue["executed"] is True
    assert rescue["assessment_after"]["risk_level"] == "SAFE"

    # 5. Back to ARMED -- the protected position needs nothing further.
    settled = client.post(
        "/api/position/analyze",
        json={
            "position": {
                "collateral_amount": rescue["position_after"]["collateral_amount"],
                "debt_amount": rescue["position_after"]["debt_amount"],
                "collateral_price": rescue["position_after"]["collateral_price"],
            }
        },
    ).json()
    assert settled["assessment"]["requires_action"] is False

    # 6. The rescue is in the history.
    assert len(client.get("/api/history").json()["transactions"]) == 1


# ---------------------------------------------------------------------------
# POST /api/demo/simulate-drop -- the full cycle, server-side
# ---------------------------------------------------------------------------

def test_simulate_drop_applies_the_shock_on_the_server():
    """The client sends only a percentage. Everything else comes back."""
    r = client.post("/api/demo/simulate-drop", json={"price_drop_pct": 10})
    assert r.status_code == 200
    body = r.json()

    assert body["price_before"] == 3000.0
    assert body["price_after"] == 2700.0
    assert body["assessment_before"]["health_factor"] == pytest.approx(1.25, abs=1e-4)
    assert body["assessment_shocked"]["health_factor"] == pytest.approx(1.125, abs=1e-4)
    assert body["assessment_shocked"]["risk_level"] == "DANGER"
    assert body["assessment_shocked"]["collateral_value"] == pytest.approx(9000.0, abs=0.01)


def test_simulate_drop_returns_the_full_state_walk():
    body = client.post("/api/demo/simulate-drop", json={"price_drop_pct": 10}).json()
    states = [step["shield_state"] for step in body["trace"]]

    assert states[0] == "ARMED"
    assert states[-1] == "ARMED"
    for earlier, later in (("ALERT", "PROTECTING"), ("PROTECTING", "PROTECTED")):
        assert states.index(earlier) < states.index(later)


def test_simulate_drop_executes_and_reports_the_final_health_factor():
    body = client.post("/api/demo/simulate-drop", json={"price_drop_pct": 10}).json()

    assert body["executed"] is True
    assert body["simulated"] is True
    assert body["execution_status"] == "EXECUTED"
    assert body["assessment_final"]["health_factor"] >= 1.5
    assert body["assessment_final"]["risk_level"] == "SAFE"
    assert body["position_final"]["debt_amount"] < body["position_shocked"]["debt_amount"]


def test_simulate_drop_returns_the_decision_trace_panel_payload():
    body = client.post("/api/demo/simulate-drop", json={"price_drop_pct": 10}).json()
    trace = body["decision_trace"]

    assert trace["scenario"] == "ETH -10%"
    assert trace["risk_level"] == "DANGER"
    assert trace["strategies_generated"] == 5
    assert trace["strategies_rejected"] == 1
    assert trace["selected"] == "Repay debt from wallet"
    assert trace["execution"] == "SIMULATED SUCCESS"
    assert trace["final_health_factor"] == pytest.approx(1.5, abs=1e-4)
    assert trace["mode"] == "AUTONOMOUS"


def test_simulate_drop_includes_the_scenario_ladder_and_candidates():
    body = client.post("/api/demo/simulate-drop", json={"price_drop_pct": 10}).json()
    assert len(body["scenarios"]) == 5
    assert len(body["strategies"]) == 5
    assert sum(1 for s in body["strategies"] if s["selected"]) == 1


def test_simulate_drop_holds_in_advisory_mode():
    payload = {"price_drop_pct": 10, "preferences": {"mode": "ADVISORY"}}
    held = client.post("/api/demo/simulate-drop", json=payload).json()

    assert held["executed"] is False
    assert held["execution_status"] == "AWAITING_CONFIRMATION"
    assert held["shield_state"] == "ALERT"
    assert held["decision_trace"]["execution"] == "AWAITING CONFIRMATION"
    assert "PROTECTING" not in [s["shield_state"] for s in held["trace"]]

    confirmed = client.post(
        "/api/demo/simulate-drop", json={**payload, "confirm": True}
    ).json()
    assert confirmed["executed"] is True
    assert confirmed["transaction"]["mode"] == "ADVISORY"


def test_simulate_drop_does_nothing_when_the_trigger_is_not_breached():
    body = client.post("/api/demo/simulate-drop", json={"price_drop_pct": 2}).json()

    assert body["executed"] is False
    assert body["execution_status"] == "NO_ACTION_REQUIRED"
    assert body["strategies"] == []
    assert {s["shield_state"] for s in body["trace"]} == {"ARMED"}


def test_simulate_drop_stands_down_when_nothing_is_viable():
    body = client.post(
        "/api/demo/simulate-drop",
        json={
            "price_drop_pct": 10,
            "market": THIN_POOL,
            "preferences": {"available_capital": 0.0},
        },
    ).json()

    assert body["executed"] is False
    assert body["shield_state"] == "SKIPPED"
    assert body["decision_trace"]["execution"] == "STOOD DOWN"
    assert "insufficient liquidity" in body["explanation"]


def test_simulate_drop_writes_history_only_when_it_executes():
    client.post("/api/demo/simulate-drop", json={"price_drop_pct": 10})
    assert len(client.get("/api/history").json()["transactions"]) == 1

    client.post("/api/demo/simulate-drop", json={"price_drop_pct": 2})
    assert len(client.get("/api/history").json()["transactions"]) == 1


def test_simulate_drop_rejects_an_impossible_drop():
    assert client.post("/api/demo/simulate-drop", json={"price_drop_pct": 150}).status_code == 422
    assert client.post("/api/demo/simulate-drop", json={"price_drop_pct": -5}).status_code == 422


def test_simulate_drop_rejects_an_invalid_position():
    r = client.post(
        "/api/demo/simulate-drop",
        json={"price_drop_pct": 10, "position": {"collateral_amount": -2}},
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Scenario thresholds -- the lines the chart marks come from the backend
# ---------------------------------------------------------------------------

def test_scenario_response_carries_the_chart_thresholds():
    body = client.post("/api/scenario/simulate", json={}).json()
    assert body["thresholds"] == {
        "liquidation": 1.0,
        "intervention_trigger": 1.20,
        "target": 1.50,
    }


def test_scenario_thresholds_follow_the_users_preferences():
    body = client.post(
        "/api/scenario/simulate",
        json={"preferences": {"target_health_factor": 2.0, "trigger_health_factor": 1.6}},
    ).json()
    assert body["thresholds"]["intervention_trigger"] == 1.6
    assert body["thresholds"]["target"] == 2.0


def test_scenarios_expose_the_intervention_flag_over_http():
    scenarios = client.post("/api/scenario/simulate", json={}).json()["scenarios"]
    assert scenarios[0]["requires_intervention"] is False   # Current, HF 1.250
    assert scenarios[1]["requires_intervention"] is True    # -5%, HF 1.1875
    assert all("requires_intervention" in s for s in scenarios)


def test_strategies_expose_score_100_and_safety_level_over_http():
    rows = client.post("/api/strategies/generate", json={"position": DROPPED}).json()["strategies"]
    viable = [r for r in rows if r["is_executable"]]
    rejected = [r for r in rows if not r["is_executable"]]

    assert all(isinstance(r["score_100"], int) for r in rows)
    assert all(r["safety_level"] in ("HIGH", "MEDIUM", "LOW") for r in viable)
    assert all(r["safety_level"] is None and r["score_100"] == 0 for r in rejected)
    # The selected strategy is the top scorer on the 0-100 scale too.
    selected = next(r for r in rows if r["selected"])
    assert selected["score_100"] == max(r["score_100"] for r in rows)


def test_decision_trace_exposes_risk_transition_and_final_status_over_http():
    trace = client.post("/api/demo/simulate-drop", json={"price_drop_pct": 10}).json()[
        "decision_trace"
    ]
    assert trace["risk_level_before"] == "WARNING"
    assert trace["risk_level"] == "DANGER"
    assert trace["final_status"] == "PROTECTED"

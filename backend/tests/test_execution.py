"""Settlement layer tests.

Two jobs here. First, that a receipt carries everything the Rescue History and
the dashboard need. Second -- and more important -- that a simulated execution
can never be mistaken for a real one. A demo that fakes a confirmation is
worse than one that admits it is a simulation.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.domain import MarketConditions, Position, ProtectionMode, RiskPreferences
from app.services import execution, risk_engine, strategy_engine
from app.services.repository import reset_repository

client = TestClient(app)

PREFS = RiskPreferences()
# HF 1.125 -- below the trigger, the agent acts on its own.
RISKY = Position().with_price(2700.0)
# HF 1.25 -- below target, above the trigger: options offered, nothing auto-run.
WATCHFUL = Position()


@pytest.fixture(autouse=True)
def _clean():
    reset_repository()
    yield
    reset_repository()


def _receipt(position=RISKY):
    market = MarketConditions(eth_price=position.collateral_price)
    decision = strategy_engine.evaluate(position, PREFS, market)
    strategy = decision.selected_strategy or strategy_engine.select_best(decision.strategies)
    after = strategy_engine.apply_strategy(position, strategy)
    hf_after = risk_engine.health_factor(after)
    return execution.get_settlement().execute(
        position=position,
        strategy=strategy,
        health_factor_before=decision.assessment.health_factor,
        health_factor_after=hf_after,
        risk_before=decision.assessment.risk_level.value,
        risk_after=risk_engine.classify_risk(hf_after).value,
        mode="AUTONOMOUS",
        reason=decision.explanation,
    )


# ---------------------------------------------------------------------------
# Nothing here may look like a real transaction
# ---------------------------------------------------------------------------

def test_a_simulated_hash_is_not_a_valid_transaction_hash():
    """0xSIM… cannot be confused with a real 32-byte hash: it is not hex."""
    r = _receipt()
    assert r.tx_hash.startswith("0xSIMULATED")
    body = r.tx_hash[2:]
    assert not all(c in "0123456789abcdefABCDEF" for c in body)


def test_the_receipt_declares_itself_simulated_three_ways():
    r = _receipt()
    assert r.simulated is True
    assert r.settlement == "SIMULATED"
    assert r.network == "simulated"


def test_no_block_number_or_confirmation_is_invented():
    """Fabricating a block height or confirmation count is the exact dishonesty
    this layer exists to avoid."""
    d = _receipt().to_dict()
    for forbidden in ("block_number", "block_hash", "confirmations", "gas_used", "nonce"):
        assert forbidden not in d


def test_the_settlement_layer_reports_what_it_is():
    described = execution.describe()
    assert described["settlement"] == "SIMULATED"
    assert described["signs_transactions"] is False
    assert described["uses_real_funds"] is False


def test_health_endpoint_advertises_simulated_settlement():
    engines = client.get("/api/health").json()["engines"]
    assert engines["blockchain"] == "simulated"
    assert engines["settlement"] == "SIMULATED"


# ---------------------------------------------------------------------------
# The receipt carries what the history and dashboard need
# ---------------------------------------------------------------------------

def test_the_receipt_has_every_required_field():
    d = _receipt().to_dict()
    for key in (
        "tx_hash", "executed_at", "strategy_type", "strategy_name",
        "action", "action_amount", "health_factor_before",
        "health_factor_after", "risk_before", "risk_after",
        "status", "status_label", "reason",
    ):
        assert key in d and d[key] not in (None, ""), key


def test_status_is_success_on_a_completed_execution():
    assert _receipt().status == execution.STATUS_SUCCESS


def test_health_factors_come_from_the_risk_engine_not_the_settlement_layer():
    """The settlement layer must not do its own arithmetic, or it could
    disagree with the engine that is supposed to be authoritative."""
    market = MarketConditions(eth_price=RISKY.collateral_price)
    decision = strategy_engine.evaluate(RISKY, PREFS, market)
    after = strategy_engine.apply_strategy(RISKY, decision.selected_strategy)
    expected = risk_engine.health_factor(after)

    r = _receipt()
    assert r.health_factor_before == pytest.approx(decision.assessment.health_factor, abs=1e-4)
    assert r.health_factor_after == pytest.approx(expected, abs=1e-4)


def test_every_hash_is_unique():
    assert len({_receipt().tx_hash for _ in range(20)}) == 20


# ---------------------------------------------------------------------------
# The autonomous path, end to end
# ---------------------------------------------------------------------------

def test_autonomous_execution_writes_a_receipt_to_history():
    body = client.post(
        "/api/rescue/autoexecute", json={"position": {"collateral_price": 2700}}
    ).json()

    assert body["executed"] is True
    tx = body["transaction"]
    assert tx["status"] == "SUCCESS"
    assert tx["settlement"] == "SIMULATED"
    assert tx["health_factor_after"] > tx["health_factor_before"]

    history = client.get("/api/history").json()["transactions"]
    assert len(history) == 1
    assert history[0]["tx_hash"] == tx["tx_hash"]


def test_the_recorded_health_factors_match_the_response():
    body = client.post(
        "/api/rescue/autoexecute", json={"position": {"collateral_price": 2700}}
    ).json()
    tx = client.get("/api/history").json()["transactions"][0]

    assert tx["health_factor_before"] == pytest.approx(
        body["assessment_before"]["health_factor"], abs=1e-4
    )
    assert tx["health_factor_after"] == pytest.approx(
        body["assessment_after"]["health_factor"], abs=1e-4
    )


# ---------------------------------------------------------------------------
# "Execute Protection" below the trigger -- the user opting in early
# ---------------------------------------------------------------------------

def test_the_agent_does_not_act_on_its_own_below_the_trigger():
    body = client.post("/api/rescue/autoexecute", json={}).json()
    assert body["executed"] is False
    assert body["execution_status"] == "NO_ACTION_REQUIRED"
    assert client.get("/api/history").json()["transactions"] == []


def test_but_the_user_can_execute_protection_early():
    """Regression: options are generated at WARNING but none is selected, so
    the button used to do nothing at exactly the point a cautious user would
    press it."""
    body = client.post("/api/rescue/autoexecute", json={"confirm": True}).json()

    assert body["executed"] is True
    assert body["selected_strategy"] is not None
    assert body["assessment_after"]["health_factor"] >= PREFS.target_health_factor - 1e-6
    assert body["transaction"]["user_initiated"] is True
    assert body["explanation"].startswith("User-initiated:")
    assert len(client.get("/api/history").json()["transactions"]) == 1


def test_an_agent_execution_is_not_marked_user_initiated():
    body = client.post(
        "/api/rescue/autoexecute",
        json={"position": {"collateral_price": 2700}, "confirm": False},
    ).json()
    assert body["transaction"]["user_initiated"] is False


def test_confirming_above_target_still_executes_nothing():
    """Nothing to protect against: a rescue would move the position no closer
    to the target it already exceeds."""
    body = client.post(
        "/api/rescue/autoexecute",
        json={"position": {"debt_amount": 2000}, "confirm": True},
    ).json()
    assert body["executed"] is False
    assert "no viable strategy" in body["explanation"].lower()


# ---------------------------------------------------------------------------
# No viable strategy
# ---------------------------------------------------------------------------

NOTHING_WORKS = {
    "position": {"collateral_price": 2700},
    "market": {"dex_liquidity_usd": 200000, "max_pool_utilisation": 0.01},
    "preferences": {"available_capital": 0.0},
}


def test_no_viable_strategy_executes_nothing_and_says_why():
    body = client.post(
        "/api/rescue/autoexecute", json={**NOTHING_WORKS, "confirm": True}
    ).json()

    assert body["executed"] is False
    assert body["transaction"] is None
    assert "no viable strategy" in body["explanation"].lower()
    assert body["strategies"], "the rejected candidates are still reported"
    assert all(not s["is_executable"] for s in body["strategies"])


def test_a_failed_execution_leaves_no_trace_in_history():
    client.post("/api/rescue/autoexecute", json={**NOTHING_WORKS, "confirm": True})
    assert client.get("/api/history").json()["transactions"] == []


def test_every_rejected_candidate_still_carries_its_reason():
    body = client.post("/api/rescue/autoexecute", json=NOTHING_WORKS).json()
    for s in body["strategies"]:
        assert s["rejection_reason"], s["name"]


# ---------------------------------------------------------------------------
# Advisory mode still gates on confirmation
# ---------------------------------------------------------------------------

def test_advisory_mode_holds_until_confirmed():
    payload = {
        "position": {"collateral_price": 2700},
        "preferences": {"mode": ProtectionMode.ADVISORY.value},
    }
    held = client.post("/api/rescue/autoexecute", json=payload).json()
    assert held["executed"] is False
    assert client.get("/api/history").json()["transactions"] == []

    done = client.post("/api/rescue/autoexecute", json={**payload, "confirm": True}).json()
    assert done["executed"] is True
    assert done["transaction"]["mode"] == "ADVISORY"


# ---------------------------------------------------------------------------
# The user naming a specific strategy
# ---------------------------------------------------------------------------

RISKY_BODY = {"position": {"collateral_price": 2700}}


def test_the_user_can_execute_a_specific_strategy():
    body = client.post(
        "/api/rescue/autoexecute",
        json={**RISKY_BODY, "confirm": True, "strategy_type": "ADD_COLLATERAL"},
    ).json()

    assert body["executed"] is True
    assert body["selected_strategy"]["strategy_type"] == "ADD_COLLATERAL"
    assert body["transaction"]["strategy_type"] == "ADD_COLLATERAL"
    assert body["transaction"]["user_initiated"] is True


def test_choosing_a_strategy_overrides_the_agents_pick():
    auto = client.post("/api/rescue/autoexecute", json=RISKY_BODY).json()
    assert auto["selected_strategy"]["strategy_type"] == "REPAY_DEBT"

    chosen = client.post(
        "/api/rescue/autoexecute",
        json={**RISKY_BODY, "confirm": True, "strategy_type": "FLASH_LOAN_DELEVERAGE"},
    ).json()
    assert chosen["selected_strategy"]["strategy_type"] == "FLASH_LOAN_DELEVERAGE"


def test_choosing_a_strategy_does_not_bypass_validation():
    """Naming a rejected candidate must not be a way round the constraints."""
    r = client.post(
        "/api/rescue/autoexecute",
        json={**RISKY_BODY, "confirm": True, "strategy_type": "PARTIAL_DELEVERAGE"},
    )
    assert r.status_code == 422
    assert "cannot run" in r.json()["detail"]
    assert client.get("/api/history").json()["transactions"] == []


def test_an_unknown_strategy_name_is_rejected():
    r = client.post(
        "/api/rescue/autoexecute",
        json={**RISKY_BODY, "confirm": True, "strategy_type": "SELL_EVERYTHING"},
    )
    assert r.status_code == 422
    assert "not among the strategies" in r.json()["detail"]


def test_a_user_chosen_strategy_still_lands_at_or_above_target():
    body = client.post(
        "/api/rescue/autoexecute",
        json={**RISKY_BODY, "confirm": True, "strategy_type": "COLLATERAL_SWAP"},
    ).json()
    assert body["assessment_after"]["health_factor"] >= PREFS.target_health_factor - 1e-6


# ---------------------------------------------------------------------------
# The receipt fields the UI prints
# ---------------------------------------------------------------------------

def test_the_receipt_reports_risk_before_and_after():
    tx = client.post("/api/rescue/autoexecute", json=RISKY_BODY).json()["transaction"]
    assert tx["risk_before"] == "DANGER"
    assert tx["risk_after"] == "SAFE"


def test_the_status_label_is_the_one_the_ui_shows():
    tx = client.post("/api/rescue/autoexecute", json=RISKY_BODY).json()["transaction"]
    assert tx["status_label"] == "SIMULATED SUCCESS"


def test_the_action_line_names_the_move_and_the_amount():
    tx = client.post("/api/rescue/autoexecute", json=RISKY_BODY).json()["transaction"]
    assert tx["action"].startswith("Repay debt $")
    assert f"{tx['action_amount']:,.2f}" in tx["action"]


def test_the_hash_cannot_be_looked_up_on_an_explorer():
    tx = client.post("/api/rescue/autoexecute", json=RISKY_BODY).json()["transaction"]
    assert tx["tx_hash"].startswith("0xSIMULATED")
    assert not all(c in "0123456789abcdef" for c in tx["tx_hash"][2:].lower())

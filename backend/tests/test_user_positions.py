"""User-entered positions: the asset catalogue, parameter resolution, and the
guarantee that a hand-typed position goes through exactly the same engines as
the demo one."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.domain import MarketConditions, Position, RiskPreferences, ValidationError
from app.schemas.api import PositionIn
from app.services import agent_cycle, assets, risk_engine
from app.services.repository import reset_repository

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clean_repository():
    reset_repository()
    yield
    reset_repository()


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------

def test_catalogue_covers_the_assets_the_form_offers():
    symbols = {a["symbol"] for a in assets.catalogue()}
    assert {"ETH", "BTC", "USDC"} <= symbols
    assert assets.DEFAULT_ASSET in symbols


def test_every_asset_has_sane_market_parameters():
    for spec in assets.ASSETS.values():
        assert 0 < spec.liquidation_threshold <= 1
        assert 0 <= spec.liquidation_bonus < 1
        assert 0 < spec.close_factor <= 1
        assert spec.reference_price > 0


def test_simulated_tiers_are_never_looser_than_the_real_market():
    """A position that looks safe here must look at least as safe on mainnet.
    If this ever inverts, the simulator is flattering the user."""
    for spec in assets.ASSETS.values():
        assert spec.liquidation_threshold <= spec.real_world_threshold


def test_only_stablecoins_can_be_borrowed():
    """The risk engine values debt at $1 per unit, so anything else would be
    silently wrong rather than merely unsupported."""
    assert assets.DEBT_ASSETS
    for symbol in assets.DEBT_ASSETS:
        assert assets.ASSETS[symbol].is_stable


def test_unknown_asset_is_rejected_with_a_readable_message():
    with pytest.raises(ValidationError) as exc:
        assets.get("DOGE")
    assert "not a supported collateral asset" in str(exc.value)


def test_lookup_is_case_insensitive():
    assert assets.get("eth").symbol == "ETH"
    assert assets.get(" btc ").symbol == "BTC"


def test_assets_endpoint_serves_the_form():
    body = client.get("/api/assets").json()
    assert body["default_collateral_asset"] == "ETH"
    assert body["default_debt_asset"] in body["debt_assets"]
    eth = next(a for a in body["assets"] if a["symbol"] == "ETH")
    assert eth["liquidation_threshold"] == 0.625
    assert eth["real_world_threshold"] == 0.825


# ---------------------------------------------------------------------------
# Parameter resolution: the browser never picks a risk parameter
# ---------------------------------------------------------------------------

def test_threshold_is_resolved_from_the_asset_when_omitted():
    position = PositionIn(collateral_asset="BTC", collateral_amount=1.0).to_domain()
    spec = assets.get("BTC")
    assert position.liquidation_threshold == spec.liquidation_threshold
    assert position.liquidation_bonus == spec.liquidation_bonus
    assert position.close_factor == spec.close_factor


def test_an_explicit_threshold_still_wins():
    """So a user can model the real Aave market instead of the simulated one."""
    position = PositionIn(collateral_asset="ETH", liquidation_threshold=0.825).to_domain()
    assert position.liquidation_threshold == 0.825


def test_the_same_asset_always_resolves_the_same_parameters():
    a = PositionIn(collateral_asset="ETH").to_domain()
    b = PositionIn(collateral_asset="eth", collateral_amount=99.0).to_domain()
    assert a.liquidation_threshold == b.liquidation_threshold


# ---------------------------------------------------------------------------
# Health Factor actually changes with the entered values
# ---------------------------------------------------------------------------

def _analyze(position, preferences=None):
    payload = {"position": position}
    if preferences:
        payload["preferences"] = preferences
    r = client.post("/api/position/analyze", json=payload)
    assert r.status_code == 200, r.text
    return r.json()["assessment"]


def test_health_factor_tracks_the_entered_collateral():
    small = _analyze({"collateral_amount": 2.0, "collateral_price": 3000, "debt_amount": 5000})
    large = _analyze({"collateral_amount": 5.0, "collateral_price": 3000, "debt_amount": 5000})
    assert large["health_factor"] > small["health_factor"]
    # 5 ETH * 3000 * 0.625 / 5000
    assert large["health_factor"] == pytest.approx(1.875, abs=1e-4)


def test_health_factor_tracks_the_entered_debt():
    light = _analyze({"collateral_amount": 3.0, "collateral_price": 3000, "debt_amount": 2000})
    heavy = _analyze({"collateral_amount": 3.0, "collateral_price": 3000, "debt_amount": 6000})
    assert light["health_factor"] > heavy["health_factor"]


def test_health_factor_tracks_the_entered_price():
    cheap = _analyze({"collateral_amount": 3.0, "collateral_price": 1500, "debt_amount": 5000})
    dear = _analyze({"collateral_amount": 3.0, "collateral_price": 4500, "debt_amount": 5000})
    assert dear["health_factor"] > cheap["health_factor"]


def test_a_btc_position_uses_the_btc_threshold():
    body = client.post(
        "/api/position/analyze",
        json={
            "position": {
                "collateral_asset": "BTC",
                "collateral_amount": 0.5,
                "collateral_price": 60_000,
                "debt_amount": 10_000,
            }
        },
    ).json()
    spec = assets.get("BTC")
    assert body["position"]["liquidation_threshold"] == spec.liquidation_threshold
    # 0.5 * 60,000 * 0.65 / 10,000
    assert body["assessment"]["health_factor"] == pytest.approx(1.95, abs=1e-4)


def test_the_entered_target_and_trigger_are_honoured():
    position = {"collateral_amount": 3.0, "collateral_price": 3000, "debt_amount": 5000}
    lenient = _analyze(position, {"target_health_factor": 1.2, "trigger_health_factor": 1.05})
    strict = _analyze(position, {"target_health_factor": 2.5, "trigger_health_factor": 2.0})
    assert lenient["requires_action"] is False
    assert strict["requires_action"] is True


# ---------------------------------------------------------------------------
# Gas is paid in ETH regardless of the collateral asset
# ---------------------------------------------------------------------------

def test_gas_is_not_costed_at_the_collateral_price():
    """A BTC position must not be charged BTC-priced gas. This was a real bug:
    the market's ETH price used to default to the collateral price."""
    btc = client.post(
        "/api/strategies/generate",
        json={
            "position": {
                "collateral_asset": "BTC",
                "collateral_amount": 0.2,
                "collateral_price": 60_000,
                "debt_amount": 7_000,
            },
            "preferences": {"available_capital": 20_000},
        },
    ).json()
    assert btc["market"]["eth_price"] == 3000.0
    repay = next(s for s in btc["strategies"] if s["strategy_type"] == "REPAY_DEBT")
    # 180,000 gas * 20 gwei * $3,000 = $10.80, not $216 at the BTC price.
    assert repay["gas_cost"] == pytest.approx(10.80, abs=0.01)


def test_a_btc_shock_does_not_reprice_gas():
    result = agent_cycle.run_cycle(
        Position(
            collateral_asset="BTC",
            collateral_amount=0.2,
            collateral_price=60_000,
            debt_amount=7_000,
            liquidation_threshold=0.65,
        ),
        RiskPreferences(available_capital=20_000),
        MarketConditions(eth_price=3000.0),
        price_drop_pct=10.0,
    )
    assert result.market.eth_price == 3000.0
    assert result.price_after == pytest.approx(54_000.0)


# ---------------------------------------------------------------------------
# Analyze == run the cycle at 0%, on the same engines as the demo
# ---------------------------------------------------------------------------

def test_analysing_at_zero_percent_applies_no_shock():
    body = client.post(
        "/api/demo/simulate-drop",
        json={
            "price_drop_pct": 0,
            "position": {"collateral_amount": 4.0, "collateral_price": 2000, "debt_amount": 5000},
        },
    ).json()

    assert body["price_before"] == body["price_after"] == 2000.0
    assert body["assessment_before"]["health_factor"] == body["assessment_shocked"]["health_factor"]
    assert body["decision_trace"]["scenario"] == "ETH at entered price"


def test_a_risky_user_position_is_rescued_without_a_price_shock():
    """Steps 3-8 of the user workflow, on a position the user typed."""
    body = client.post(
        "/api/demo/simulate-drop",
        json={
            "price_drop_pct": 0,
            # 4 ETH at $2,000 = $8,000 against $5,000 -> HF 1.0
            "position": {"collateral_amount": 4.0, "collateral_price": 2000, "debt_amount": 5000},
        },
    ).json()

    assert body["assessment_shocked"]["health_factor"] == pytest.approx(1.0, abs=1e-4)
    assert body["executed"] is True
    assert body["assessment_final"]["health_factor"] >= 1.5
    assert [s["shield_state"] for s in body["trace"]][-1] == "ARMED"
    assert "PROTECTED" in [s["shield_state"] for s in body["trace"]]


def test_a_safe_user_position_generates_no_strategies():
    body = client.post(
        "/api/demo/simulate-drop",
        json={
            "price_drop_pct": 0,
            "position": {"collateral_amount": 10.0, "collateral_price": 3000, "debt_amount": 5000},
        },
    ).json()

    assert body["assessment_shocked"]["risk_level"] == "SAFE"
    assert body["strategies"] == []
    assert body["executed"] is False
    assert body["decision_trace"]["execution"] == "NOT REQUIRED"


def test_scenarios_are_generated_for_a_user_position():
    body = client.post(
        "/api/demo/simulate-drop",
        json={
            "price_drop_pct": 0,
            "position": {
                "collateral_asset": "BTC",
                "collateral_amount": 0.5,
                "collateral_price": 60_000,
                "debt_amount": 15_000,
            },
        },
    ).json()

    scenarios = body["scenarios"]
    assert [s["label"] for s in scenarios] == ["Current", "-5%", "-10%", "-15%", "-20%"]
    assert [s["new_price"] for s in scenarios] == [60_000, 57_000, 54_000, 51_000, 48_000]
    # Strictly falling Health Factor, recomputed per rung.
    hfs = [s["health_factor"] for s in scenarios]
    assert all(a > b for a, b in zip(hfs, hfs[1:]))


def test_user_positions_and_the_demo_share_one_code_path():
    """The demo position, sent as if a user had typed it, produces byte-for-byte
    the same decision as the built-in demo run."""
    typed = client.post(
        "/api/demo/simulate-drop",
        json={
            "price_drop_pct": 10,
            "position": {
                "collateral_asset": "ETH",
                "collateral_amount": 10_000 / 3_000,
                "collateral_price": 3000,
                "debt_amount": 5000,
            },
        },
    ).json()
    builtin = client.post("/api/demo/simulate-drop", json={"price_drop_pct": 10}).json()

    for key in ("decision_trace", "assessment_shocked", "assessment_final"):
        assert typed[key] == builtin[key]


# ---------------------------------------------------------------------------
# Validation, with messages a beginner can act on
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "position",
    [
        {"collateral_amount": -1},                      # negative collateral
        {"debt_amount": -1},                            # negative debt
        {"collateral_price": 0},                        # zero price
        {"collateral_price": -3000},                    # negative price
        {"collateral_amount": 0, "debt_amount": 5000},  # debt with no collateral
        {"collateral_asset": "DOGE"},                   # unsupported asset
        {"debt_asset": "ETH"},                          # non-stable debt
    ],
)
def test_invalid_user_input_is_rejected(position):
    r = client.post("/api/position/analyze", json={"position": position})
    assert r.status_code == 422, r.text


@pytest.mark.parametrize(
    "preferences",
    [
        {"target_health_factor": 1.0},
        {"target_health_factor": 0.5},
        {"trigger_health_factor": 1.0},
        {"target_health_factor": 1.2, "trigger_health_factor": 1.5},  # trigger above target
    ],
)
def test_invalid_targets_are_rejected(preferences):
    r = client.post("/api/position/analyze", json={"preferences": preferences})
    assert r.status_code == 422, r.text


def test_zero_collateral_with_no_debt_is_allowed():
    """An empty position is odd but not invalid, and must not 500."""
    r = client.post(
        "/api/position/analyze",
        json={"position": {"collateral_amount": 0, "debt_amount": 0}},
    )
    assert r.status_code == 200
    assert r.json()["assessment"]["requires_action"] is False


def test_debt_with_no_collateral_names_the_field_to_fix():
    r = client.post(
        "/api/position/analyze",
        json={"position": {"collateral_amount": 0, "debt_amount": 1000}},
    )
    assert r.status_code == 422
    assert "collateral" in r.text.lower()


def test_the_engine_rejects_the_same_case_the_schema_does():
    """Belt and braces: the rule holds even if a caller bypasses the schema."""
    with pytest.raises(ValidationError):
        risk_engine.health_factor(Position(collateral_amount=0.0, debt_amount=1000.0))


# ---------------------------------------------------------------------------
# Collateral expressed in dollars instead of units
# ---------------------------------------------------------------------------

def test_collateral_value_is_converted_to_units_server_side():
    """The friendly input is dollars; the engine still holds units, because
    only a quantity re-values itself when the price moves."""
    position = PositionIn(collateral_value=10_000.0, collateral_price=2_500.0).to_domain()
    assert position.collateral_amount == pytest.approx(4.0)
    assert position.collateral_value == pytest.approx(10_000.0)


def test_value_and_amount_inputs_agree():
    by_value = PositionIn(collateral_value=10_000.0, collateral_price=2_500.0).to_domain()
    by_amount = PositionIn(collateral_amount=4.0, collateral_price=2_500.0).to_domain()
    assert by_value.collateral_amount == pytest.approx(by_amount.collateral_amount)
    assert risk_engine.health_factor(by_value) == pytest.approx(
        risk_engine.health_factor(by_amount)
    )


def test_a_dollar_position_still_re_values_under_a_price_shock():
    """The whole reason for converting: $10,000 entered at $2,500 must become
    $9,000 after a 10% drop, not stay frozen at $10,000."""
    body = client.post(
        "/api/demo/simulate-drop",
        json={
            "price_drop_pct": 10,
            "position": {"collateral_value": 10_000, "collateral_price": 2_500,
                         "debt_amount": 6_000},
        },
    ).json()

    assert body["assessment_before"]["collateral_value"] == pytest.approx(10_000.0, abs=0.01)
    assert body["assessment_shocked"]["collateral_value"] == pytest.approx(9_000.0, abs=0.01)


def test_supplying_both_amount_and_value_is_rejected():
    """Two sources of truth would disagree the moment the price moved."""
    r = client.post(
        "/api/position/analyze",
        json={"position": {"collateral_amount": 4, "collateral_value": 10_000,
                           "collateral_price": 2_500}},
    )
    assert r.status_code == 422
    assert "not both" in r.text


def test_zero_collateral_value_with_debt_is_rejected():
    r = client.post(
        "/api/position/analyze",
        json={"position": {"collateral_value": 0, "debt_amount": 5_000}},
    )
    assert r.status_code == 422
    assert "collateral" in r.text.lower()


def test_omitting_both_falls_back_to_the_seed_holding():
    assert PositionIn().to_domain().collateral_value == pytest.approx(10_000.0, abs=0.01)


def test_health_factor_tracks_the_entered_collateral_value():
    def hf(value):
        return client.post(
            "/api/position/analyze",
            json={"position": {"collateral_value": value, "collateral_price": 2_500,
                               "debt_amount": 5_000}},
        ).json()["assessment"]["health_factor"]

    assert hf(20_000) > hf(10_000) > hf(6_000)
    # 10,000 * 0.625 / 5,000
    assert hf(10_000) == pytest.approx(1.25, abs=1e-4)

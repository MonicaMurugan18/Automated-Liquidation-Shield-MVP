"""Market data tests.

Every test here mocks the network with `httpx.MockTransport`. Nothing in this
file touches the internet: a test suite that depends on a live third-party API
fails for reasons that have nothing to do with the code, which makes it useless
as a gate.
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import market_data
from app.services.market_data import MarketDataUnavailable

client = TestClient(app)

COINBASE_OK = {"data": {"base": "ETH", "currency": "USD", "amount": "3421.87"}}
COINGECKO_OK = {"ethereum": {"usd": 3399.5}}
KRAKEN_OK = {"result": {"XETHZUSD": {"c": ["3410.10", "0.5"]}}}


@pytest.fixture(autouse=True)
def _cold_cache():
    """Every test starts with no cached price and leaves none behind."""
    market_data.reset_cache()
    yield
    market_data.reset_cache()


def mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def responder(mapping, default=None):
    """Route by URL host so provider fallback order can be exercised."""

    def handler(request: httpx.Request) -> httpx.Response:
        for fragment, response in mapping.items():
            if fragment in str(request.url):
                if isinstance(response, Exception):
                    raise response
                return response
        if default is None:
            return httpx.Response(404)
        return default

    return handler


# ---------------------------------------------------------------------------
# 1. Successful live retrieval
# ---------------------------------------------------------------------------

def test_fetches_a_live_price_from_the_first_provider():
    with mock_client(responder({"coinbase": httpx.Response(200, json=COINBASE_OK)})) as c:
        price = market_data.fetch_price(client=c)

    assert price.asset == "ETH"
    assert price.currency == "USD"
    assert price.price == pytest.approx(3421.87)
    assert price.source == "Coinbase"
    assert price.is_live is True
    assert price.timestamp.endswith("+00:00")


def test_the_price_is_not_the_hard_coded_demo_number():
    """Guards against quietly reverting to a constant."""
    with mock_client(responder({"coinbase": httpx.Response(200, json=COINBASE_OK)})) as c:
        price = market_data.fetch_price(client=c)
    assert price.price != 3000.0


def test_falls_through_to_the_second_provider():
    handler = responder(
        {
            "coinbase": httpx.Response(500),
            "coingecko": httpx.Response(200, json=COINGECKO_OK),
        }
    )
    with mock_client(handler) as c:
        price = market_data.fetch_price(client=c)

    assert price.source == "CoinGecko"
    assert price.price == pytest.approx(3399.5)


def test_falls_through_to_the_third_provider():
    handler = responder(
        {
            "coinbase": httpx.Response(503),
            "coingecko": httpx.Response(429),
            "kraken": httpx.Response(200, json=KRAKEN_OK),
        }
    )
    with mock_client(handler) as c:
        price = market_data.fetch_price(client=c)

    assert price.source == "Kraken"
    assert price.price == pytest.approx(3410.10)


# ---------------------------------------------------------------------------
# 2. Invalid API response
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "payload",
    [
        {},                                    # empty
        {"data": {}},                          # missing amount
        {"unexpected": "shape"},               # different schema entirely
        {"data": {"amount": "not-a-number"}},  # non-numeric
        {"data": {"amount": None}},            # null
    ],
)
def test_malformed_responses_are_rejected(payload):
    handler = responder({"coinbase": httpx.Response(200, json=payload)}, default=httpx.Response(500))
    with mock_client(handler) as c, pytest.raises(MarketDataUnavailable):
        market_data.fetch_price(client=c)


def test_non_json_body_is_rejected():
    handler = responder(
        {"coinbase": httpx.Response(200, text="<html>rate limited</html>")},
        default=httpx.Response(500),
    )
    with mock_client(handler) as c, pytest.raises(MarketDataUnavailable):
        market_data.fetch_price(client=c)


def test_a_malformed_first_provider_does_not_block_the_others():
    handler = responder(
        {
            "coinbase": httpx.Response(200, json={"garbage": True}),
            "coingecko": httpx.Response(200, json=COINGECKO_OK),
        }
    )
    with mock_client(handler) as c:
        price = market_data.fetch_price(client=c)
    assert price.source == "CoinGecko"


# ---------------------------------------------------------------------------
# 3. Timeout
# ---------------------------------------------------------------------------

def test_a_timeout_is_handled_not_raised():
    handler = responder({"": httpx.ConnectTimeout("timed out")})
    with mock_client(handler) as c, pytest.raises(MarketDataUnavailable) as exc:
        market_data.fetch_price(client=c)
    assert "unavailable" in str(exc.value).lower()


def test_a_timeout_on_one_provider_falls_through():
    handler = responder(
        {
            "coinbase": httpx.ConnectTimeout("timed out"),
            "coingecko": httpx.Response(200, json=COINGECKO_OK),
        }
    )
    with mock_client(handler) as c:
        price = market_data.fetch_price(client=c)
    assert price.source == "CoinGecko"


# ---------------------------------------------------------------------------
# 4. API unavailable
# ---------------------------------------------------------------------------

def test_every_provider_down_raises_a_displayable_error():
    handler = responder({"": httpx.ConnectError("no route to host")})
    with mock_client(handler) as c, pytest.raises(MarketDataUnavailable) as exc:
        market_data.fetch_price(client=c)
    assert str(exc.value).startswith("Live market data unavailable.")


def test_all_providers_returning_errors_raises():
    handler = responder({}, default=httpx.Response(500))
    with mock_client(handler) as c, pytest.raises(MarketDataUnavailable):
        market_data.fetch_price(client=c)


# ---------------------------------------------------------------------------
# 5. Negative / invalid price
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [0, -1, -3000.5, float("nan"), float("inf")])
def test_invalid_prices_are_rejected(bad):
    with pytest.raises(MarketDataUnavailable):
        market_data.validate_price(bad, "TestProvider")


@pytest.mark.parametrize("absurd", [0.5, 5_000_000])
def test_implausible_prices_are_rejected(absurd):
    """A provider answering with something wildly out of band is treated as a
    failure. A bad price would silently corrupt every Health Factor."""
    with pytest.raises(MarketDataUnavailable):
        market_data.validate_price(absurd, "TestProvider")


def test_a_negative_price_from_the_wire_is_not_served():
    handler = responder(
        {"coinbase": httpx.Response(200, json={"data": {"amount": "-3000"}})},
        default=httpx.Response(500),
    )
    with mock_client(handler) as c, pytest.raises(MarketDataUnavailable):
        market_data.fetch_price(client=c)


@pytest.mark.parametrize("good", [1.0, 3421.87, 999_999.0])
def test_plausible_prices_are_accepted(good):
    assert market_data.validate_price(good, "TestProvider") == pytest.approx(good)


def test_a_numeric_string_is_accepted():
    assert market_data.validate_price("3421.87", "Coinbase") == pytest.approx(3421.87)


# ---------------------------------------------------------------------------
# Caching -- do not hammer a public API
# ---------------------------------------------------------------------------

def test_a_second_call_is_served_from_cache():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, json=COINBASE_OK)

    with mock_client(handler) as c:
        first = market_data.fetch_price(client=c)
        second = market_data.fetch_price(client=c)

    assert calls["n"] == 1
    assert first.price == second.price
    assert second.age_seconds >= 0


def test_a_forced_refresh_is_floored_by_the_minimum_interval():
    """Leaning on the refresh button must not produce a request per click."""
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, json=COINBASE_OK)

    with mock_client(handler) as c:
        market_data.fetch_price(client=c)
        for _ in range(10):
            market_data.fetch_price(client=c, force=True)

    assert calls["n"] == 1


def test_cached_price_is_none_before_any_fetch():
    assert market_data.cached_price() is None


def test_cached_price_reports_the_last_read():
    with mock_client(responder({"coinbase": httpx.Response(200, json=COINBASE_OK)})) as c:
        market_data.fetch_price(client=c)
    cached = market_data.cached_price()
    assert cached is not None
    assert cached.price == pytest.approx(3421.87)


# ---------------------------------------------------------------------------
# The HTTP endpoint
# ---------------------------------------------------------------------------

def test_endpoint_returns_a_live_price(monkeypatch):
    stub = market_data.MarketPrice(
        asset="ETH",
        currency="USD",
        price=3421.87,
        timestamp="2026-08-28T12:00:00+00:00",
        source="Coinbase",
    )
    monkeypatch.setattr(market_data, "fetch_price", lambda **kw: stub)

    body = client.get("/api/market/eth-price").json()
    assert body["asset"] == "ETH"
    assert body["currency"] == "USD"
    assert body["price"] == pytest.approx(3421.87)
    assert body["source"] == "Coinbase"
    assert body["is_live"] is True
    assert body["is_simulated"] is False
    assert "timestamp" in body


def test_endpoint_returns_503_when_the_market_is_unreachable(monkeypatch):
    def boom(**kw):
        raise MarketDataUnavailable("Live market data unavailable. All providers failed.")

    monkeypatch.setattr(market_data, "fetch_price", boom)

    response = client.get("/api/market/eth-price")
    assert response.status_code == 503
    assert "unavailable" in response.json()["detail"].lower()


def test_endpoint_passes_the_refresh_flag_through(monkeypatch):
    seen = {}

    def spy(**kw):
        seen.update(kw)
        return market_data.MarketPrice(
            asset="ETH", currency="USD", price=3000.0,
            timestamp="2026-08-28T12:00:00+00:00", source="Coinbase",
        )

    monkeypatch.setattr(market_data, "fetch_price", spy)

    client.get("/api/market/eth-price")
    assert seen["force"] is False
    client.get("/api/market/eth-price?refresh=true")
    assert seen["force"] is True


# ---------------------------------------------------------------------------
# 6. Scenario calculations run off the real current price
# ---------------------------------------------------------------------------

def test_scenarios_are_derived_from_whatever_price_is_supplied():
    """The ladder is arithmetic on the base price, so a real price in means
    real-price-derived scenarios out. Nothing is pinned to 3000."""
    live = 3421.87
    body = client.post(
        "/api/scenario/simulate",
        json={"position": {"collateral_amount": 3.0, "collateral_price": live,
                           "debt_amount": 5000}},
    ).json()

    # The API rounds to cents, so compare at that precision.
    prices = [s["new_price"] for s in body["scenarios"]]
    assert prices == pytest.approx(
        [live, live * 0.95, live * 0.90, live * 0.85, live * 0.80], abs=0.01
    )


def test_the_full_cycle_runs_off_a_real_looking_price():
    live = 2411.44
    body = client.post(
        "/api/demo/simulate-drop",
        json={"price_drop_pct": 10,
              "position": {"collateral_amount": 3.0, "collateral_price": live,
                           "debt_amount": 5000}},
    ).json()

    assert body["price_before"] == pytest.approx(live, abs=0.01)
    assert body["price_after"] == pytest.approx(live * 0.90, abs=0.01)
    assert body["decision_trace"]["scenario"] == "ETH -10%"


# ---------------------------------------------------------------------------
# 7. Manual / demo fallback
# ---------------------------------------------------------------------------

def test_analysis_still_works_with_a_manual_price_when_the_market_is_down(monkeypatch):
    """The whole point of the fallback: market data failing must not stop the
    user analysing a position."""
    def boom(**kw):
        raise MarketDataUnavailable("Live market data unavailable.")

    monkeypatch.setattr(market_data, "fetch_price", boom)

    assert client.get("/api/market/eth-price").status_code == 503

    manual = client.post(
        "/api/position/analyze",
        json={"position": {"collateral_amount": 4.0, "collateral_price": 2000,
                           "debt_amount": 5000}},
    )
    assert manual.status_code == 200
    assert manual.json()["assessment"]["health_factor"] == pytest.approx(1.0, abs=1e-4)


def test_market_failure_does_not_affect_any_other_endpoint(monkeypatch):
    def boom(**kw):
        raise MarketDataUnavailable("Live market data unavailable.")

    monkeypatch.setattr(market_data, "fetch_price", boom)

    for path, payload in [
        ("/api/scenario/simulate", {}),
        ("/api/strategies/generate", {"position": {"collateral_price": 2700}}),
        ("/api/demo/simulate-drop", {"price_drop_pct": 10}),
    ]:
        assert client.post(path, json=payload).status_code == 200, path
    assert client.get("/api/health").status_code == 200

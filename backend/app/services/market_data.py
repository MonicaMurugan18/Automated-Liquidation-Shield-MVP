"""Market data: the one place that talks to the outside world for a price.

This is the only module in the project that reads REAL data. Everything
downstream of it -- risk, scenarios, strategies, execution -- remains a
simulation. What this module provides is an honest starting point: the actual
ETH/USD price right now, instead of a number someone typed.

WHAT IS REAL AND WHAT IS NOT
----------------------------
  REAL       the current ETH/USD spot price and the timestamp it was read at
  SIMULATED  every price derived from it (-5%, -10%, -15%, -20%), every Health
             Factor projected from those, every strategy, every execution

A scenario price is a stress test, not a forecast. Nothing here predicts where
ETH will actually go, and no part of the system should ever say otherwise.

PROVIDERS
---------
Three free, keyless, public endpoints, tried in order. None requires
registration, so no credential ever exists to leak -- the "never expose API
credentials to the frontend" requirement is satisfied by there being none.
Falling through the list means a single provider outage does not take the
feature down.

RATE LIMITING
-------------
Successful reads are cached for CACHE_TTL_SECONDS. Every caller -- the
dashboard, a refresh click, a scenario run -- shares that cache, so a burst of
activity produces at most one upstream request per TTL window. `force=True`
bypasses the cache for an explicit user-initiated refresh, and even that is
floored by MIN_REFRESH_SECONDS so a user leaning on the button cannot hammer a
public API on our behalf.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# --- tuning ----------------------------------------------------------------

REQUEST_TIMEOUT_SECONDS = 5.0
CACHE_TTL_SECONDS = 60.0
MIN_REFRESH_SECONDS = 5.0

#: Sanity band for a returned price. A provider that answers with 0, a
#: negative number, or something absurd is treated as a failed read rather
#: than trusted -- a garbage price would silently corrupt every Health Factor
#: downstream, which is far worse than showing "unavailable".
MIN_PLAUSIBLE_PRICE = 1.0
MAX_PLAUSIBLE_PRICE = 1_000_000.0


class MarketDataUnavailable(RuntimeError):
    """Raised when no provider returned a usable price.

    Callers are expected to catch this and fall back to a manual price, not to
    crash. The API surfaces it as a 503 with a message fit for display.
    """


@dataclass(frozen=True)
class MarketPrice:
    asset: str
    currency: str
    price: float
    timestamp: str
    source: str
    is_live: bool = True
    #: Seconds since this price was actually fetched upstream. 0 on a fresh
    #: read, up to CACHE_TTL_SECONDS when served from cache.
    age_seconds: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["age_seconds"] = round(self.age_seconds, 1)
        d["price"] = round(self.price, 2)
        return d


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Provider:
    name: str
    url: str
    parse: Callable[[Any], Any]


# Parsers locate the value and nothing else. They deliberately do NOT convert
# it: validate_price owns every numeric check, so a provider that answers with
# a string, a null or a nonsense number fails the same way through one path.

def _parse_coinbase(payload: Any) -> Any:
    # {"data": {"base": "ETH", "currency": "USD", "amount": "3000.25"}}
    return payload["data"]["amount"]


def _parse_coingecko(payload: Any) -> Any:
    # {"ethereum": {"usd": 3000.25}}
    return payload["ethereum"]["usd"]


def _parse_kraken(payload: Any) -> Any:
    # {"result": {"XETHZUSD": {"c": ["3000.25", "0.1"]}}}
    pair = next(iter(payload["result"].values()))
    return pair["c"][0]


PROVIDERS: List[Provider] = [
    Provider(
        name="Coinbase",
        url="https://api.coinbase.com/v2/prices/ETH-USD/spot",
        parse=_parse_coinbase,
    ),
    Provider(
        name="CoinGecko",
        url="https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd",
        parse=_parse_coingecko,
    ),
    Provider(
        name="Kraken",
        url="https://api.kraken.com/0/public/Ticker?pair=ETHUSD",
        parse=_parse_kraken,
    ),
]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_price(value: Any, provider: str) -> float:
    """Reject anything that is not a plausible spot price.

    Deliberately strict. A provider that changes its response shape, returns a
    string, or answers with zero must look like a failure, because a bad price
    propagates silently into every Health Factor the system reports.
    """
    try:
        price = float(value)
    except (TypeError, ValueError) as exc:
        raise MarketDataUnavailable(
            f"{provider} returned a non-numeric price: {value!r}"
        ) from exc

    if math.isnan(price) or math.isinf(price):
        raise MarketDataUnavailable(f"{provider} returned a non-finite price.")
    if price <= 0:
        raise MarketDataUnavailable(f"{provider} returned a non-positive price: {price}")
    if not MIN_PLAUSIBLE_PRICE <= price <= MAX_PLAUSIBLE_PRICE:
        raise MarketDataUnavailable(
            f"{provider} returned an implausible price: {price}"
        )
    return price


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_cached: Optional[MarketPrice] = None
_cached_at: float = 0.0
_last_upstream_call: float = 0.0


def reset_cache() -> None:
    """Test hook, and the way to force a genuinely cold read."""
    global _cached, _cached_at, _last_upstream_call
    with _lock:
        _cached = None
        _cached_at = 0.0
        _last_upstream_call = 0.0


def cached_price() -> Optional[MarketPrice]:
    """The cached price with its current age, or None if nothing is cached."""
    with _lock:
        if _cached is None:
            return None
        from dataclasses import replace

        return replace(_cached, age_seconds=time.monotonic() - _cached_at)


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def _fetch_from(provider: Provider, client: httpx.Client) -> MarketPrice:
    """One provider, one attempt. Raises MarketDataUnavailable on any problem."""
    try:
        response = client.get(provider.url)
        response.raise_for_status()
        payload = response.json()
    except httpx.TimeoutException as exc:
        raise MarketDataUnavailable(f"{provider.name} timed out.") from exc
    except httpx.HTTPStatusError as exc:
        raise MarketDataUnavailable(
            f"{provider.name} returned HTTP {exc.response.status_code}."
        ) from exc
    except httpx.HTTPError as exc:
        raise MarketDataUnavailable(f"{provider.name} is unreachable: {exc}") from exc
    except ValueError as exc:  # json() on a non-JSON body
        raise MarketDataUnavailable(f"{provider.name} returned invalid JSON.") from exc

    try:
        raw = provider.parse(payload)
    except (KeyError, IndexError, TypeError, ValueError, StopIteration) as exc:
        raise MarketDataUnavailable(
            f"{provider.name} returned an unexpected response shape."
        ) from exc

    price = validate_price(raw, provider.name)
    return MarketPrice(
        asset="ETH",
        currency="USD",
        price=price,
        timestamp=datetime.now(timezone.utc).isoformat(),
        source=provider.name,
        is_live=True,
        age_seconds=0.0,
    )


def fetch_price(
    *,
    client: Optional[httpx.Client] = None,
    force: bool = False,
) -> MarketPrice:
    """Current ETH/USD, from cache when warm and upstream when not.

    `client` is injected by the tests so no unit test ever touches the network.
    `force` bypasses the TTL for a user-initiated refresh, subject to
    MIN_REFRESH_SECONDS.

    Raises MarketDataUnavailable when every provider fails. Callers must treat
    that as "fall back to a manual price", never as fatal.
    """
    global _cached, _cached_at, _last_upstream_call

    now = time.monotonic()
    with _lock:
        cached, cached_at, last_call = _cached, _cached_at, _last_upstream_call

    if cached is not None:
        age = now - cached_at
        fresh_enough = age < CACHE_TTL_SECONDS
        too_soon_to_refresh = force and (now - last_call) < MIN_REFRESH_SECONDS
        if fresh_enough or too_soon_to_refresh:
            from dataclasses import replace

            return replace(cached, age_seconds=age)

    owns_client = client is None
    client = client or httpx.Client(
        timeout=REQUEST_TIMEOUT_SECONDS,
        headers={"User-Agent": "automated-liquidation-shield/0.1 (hackathon prototype)"},
        follow_redirects=True,
    )

    failures: List[str] = []
    try:
        for provider in PROVIDERS:
            try:
                price = _fetch_from(provider, client)
            except MarketDataUnavailable as exc:
                logger.warning("Market data: %s", exc)
                failures.append(str(exc))
                continue

            with _lock:
                _cached = price
                _cached_at = time.monotonic()
                _last_upstream_call = time.monotonic()
            return price
    finally:
        if owns_client:
            client.close()

    with _lock:
        _last_upstream_call = time.monotonic()

    message = "Live market data unavailable."
    if failures:
        message = f"{message} Tried {len(PROVIDERS)} providers: " + " ".join(failures)
    raise MarketDataUnavailable(message)

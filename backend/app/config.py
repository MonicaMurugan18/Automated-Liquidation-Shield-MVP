"""Application configuration.

Every secret is read from the environment. Nothing is hard-coded, and the app
starts cleanly with no credentials at all -- in that case persistence falls
back to an in-memory store so the demo always runs.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import List, Optional

from dotenv import load_dotenv

# Load .env from the backend directory if present. Real deployments set these
# in the process environment instead.
load_dotenv()


class Settings:
    app_name: str = "Automated Liquidation Shield"
    api_prefix: str = "/api"

    # --- Supabase (optional) -------------------------------------------------
    supabase_url: Optional[str] = os.getenv("SUPABASE_URL") or None
    supabase_key: Optional[str] = os.getenv("SUPABASE_SERVICE_KEY") or None
    demo_user_id: str = os.getenv("DEMO_USER_ID", "00000000-0000-0000-0000-000000000001")

    # --- CORS ---------------------------------------------------------------
    cors_origins: List[str] = [
        o.strip()
        for o in os.getenv(
            "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
        ).split(",")
        if o.strip()
    ]

    # --- Simulated market defaults ------------------------------------------
    # These seed MarketConditions when a request does not override them. They
    # are the seam that a live gas oracle / DEX quoter replaces later.
    default_eth_price: float = float(os.getenv("DEFAULT_ETH_PRICE", "3000"))
    default_gas_price_gwei: float = float(os.getenv("DEFAULT_GAS_PRICE_GWEI", "20"))
    default_dex_liquidity_usd: float = float(
        os.getenv("DEFAULT_DEX_LIQUIDITY_USD", "2000000")
    )

    # Demo loan: five ETH is a visible, realistic holding for the walkthrough
    # and the debt is sized to remain protectable with the default wallet.
    demo_collateral_amount: float = float(os.getenv("DEMO_COLLATERAL_AMOUNT", "5"))
    demo_debt_amount: float = float(os.getenv("DEMO_DEBT_AMOUNT", "5800"))

    @property
    def supabase_enabled(self) -> bool:
        return bool(self.supabase_url and self.supabase_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()

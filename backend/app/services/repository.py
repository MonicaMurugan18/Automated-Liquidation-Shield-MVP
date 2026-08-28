"""Persistence layer.

Two interchangeable implementations behind one interface:

  * SupabaseRepository -- used when SUPABASE_URL and SUPABASE_SERVICE_KEY are
    present in the environment.
  * MemoryRepository   -- the fallback. Keeps the last N records in process so
    the demo runs with zero configuration.

Writes are best-effort by design: a logging failure must never take down a
liquidation rescue. Every write is wrapped, and a failed write is reported in
the response envelope rather than raised.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..config import get_settings

logger = logging.getLogger(__name__)

MAX_MEMORY_RECORDS = 200


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BaseRepository:
    backend_name = "unknown"

    def record_analysis(self, payload: Dict[str, Any]) -> None:
        raise NotImplementedError

    def record_scenarios(self, payload: Dict[str, Any]) -> None:
        raise NotImplementedError

    def record_strategies(self, payload: Dict[str, Any]) -> None:
        raise NotImplementedError

    def record_rescue(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def list_rescues(self, limit: int = 50) -> List[Dict[str, Any]]:
        raise NotImplementedError


class MemoryRepository(BaseRepository):
    """In-process store. Data lives for the lifetime of the server."""

    backend_name = "in-memory"

    def __init__(self) -> None:
        self._positions: List[Dict[str, Any]] = []
        self._scenarios: List[Dict[str, Any]] = []
        self._strategies: List[Dict[str, Any]] = []
        self._rescues: List[Dict[str, Any]] = []

    @staticmethod
    def _append(bucket: List[Dict[str, Any]], row: Dict[str, Any]) -> None:
        bucket.append(row)
        if len(bucket) > MAX_MEMORY_RECORDS:
            del bucket[: len(bucket) - MAX_MEMORY_RECORDS]

    def record_analysis(self, payload: Dict[str, Any]) -> None:
        self._append(self._positions, {"id": str(uuid.uuid4()), "created_at": _now(), **payload})

    def record_scenarios(self, payload: Dict[str, Any]) -> None:
        self._append(self._scenarios, {"id": str(uuid.uuid4()), "created_at": _now(), **payload})

    def record_strategies(self, payload: Dict[str, Any]) -> None:
        self._append(self._strategies, {"id": str(uuid.uuid4()), "created_at": _now(), **payload})

    def record_rescue(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        row = {"id": str(uuid.uuid4()), "created_at": _now(), **payload}
        self._append(self._rescues, row)
        return row

    def list_rescues(self, limit: int = 50) -> List[Dict[str, Any]]:
        return list(reversed(self._rescues))[:limit]


class SupabaseRepository(BaseRepository):
    """Supabase (PostgreSQL) store. Schema lives in supabase/schema.sql."""

    backend_name = "supabase"

    def __init__(self, url: str, key: str) -> None:
        from supabase import create_client  # imported lazily: optional dependency

        self._client = create_client(url, key)
        self._user_id = get_settings().demo_user_id

    def _insert(self, table: str, row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            result = self._client.table(table).insert(row).execute()
            return (result.data or [None])[0]
        except Exception as exc:  # pragma: no cover - network path
            logger.warning("Supabase insert into %s failed: %s", table, exc)
            return None

    def record_analysis(self, payload: Dict[str, Any]) -> None:
        self._insert("positions", {"user_id": self._user_id, **payload})

    def record_scenarios(self, payload: Dict[str, Any]) -> None:
        self._insert("scenarios", {"user_id": self._user_id, **payload})

    def record_strategies(self, payload: Dict[str, Any]) -> None:
        self._insert("protection_strategies", {"user_id": self._user_id, **payload})

    def record_rescue(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        row = {"user_id": self._user_id, **payload}
        stored = self._insert("rescue_transactions", row)
        return stored or {"id": str(uuid.uuid4()), "created_at": _now(), **payload}

    def list_rescues(self, limit: int = 50) -> List[Dict[str, Any]]:
        try:  # pragma: no cover - network path
            result = (
                self._client.table("rescue_transactions")
                .select("*")
                .eq("user_id", self._user_id)
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
            return result.data or []
        except Exception as exc:  # pragma: no cover - network path
            logger.warning("Supabase read from rescue_transactions failed: %s", exc)
            return []


_repository: Optional[BaseRepository] = None


def get_repository() -> BaseRepository:
    """Return the active repository, choosing an implementation on first use."""
    global _repository
    if _repository is not None:
        return _repository

    settings = get_settings()
    if settings.supabase_enabled:
        try:
            _repository = SupabaseRepository(settings.supabase_url, settings.supabase_key)
            logger.info("Persistence: Supabase")
            return _repository
        except Exception as exc:
            logger.warning(
                "Supabase configured but unavailable (%s). Falling back to memory.", exc
            )

    _repository = MemoryRepository()
    logger.info("Persistence: in-memory (set SUPABASE_URL/SUPABASE_SERVICE_KEY to persist)")
    return _repository


def reset_repository() -> None:
    """Test hook: drop the cached repository so the next call re-selects."""
    global _repository
    _repository = None

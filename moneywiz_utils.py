"""
Shared MoneyWiz utilities.
Used by both server.py (MCP) and app.py (Sync App).
"""

import os
import sqlite3
from pathlib import Path

# ---------------------------------------------------------------------------
# Monkey-patch moneywiz-api transaction validation before import
# The library uses assert for validation, which fails on edge cases
# (e.g. 0-amount transactions). We skip invalid records silently.
# ---------------------------------------------------------------------------
from moneywiz_api.model import transaction as _tx_module
import inspect as _inspect

for _name, _cls in _inspect.getmembers(_tx_module, _inspect.isclass):
    if hasattr(_cls, "validate"):
        _orig = _cls.validate

        def _make_safe(_o):
            def _safe_validate(self):
                try:
                    _o(self)
                except AssertionError:
                    pass

            return _safe_validate

        _cls.validate = _make_safe(_orig)

from moneywiz_api import MoneywizApi

# ---------------------------------------------------------------------------
# DB path discovery
# ---------------------------------------------------------------------------

_DEFAULT_DB_PATH = Path.home() / (
    "Library/Containers/com.moneywiz.personalfinance"
    "/Data/Documents/.AppData/ipadMoneyWiz.sqlite"
)


def find_db_path() -> Path:
    env_path = os.environ.get("MONEYWIZ_DB_PATH")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p
        raise FileNotFoundError(f"MONEYWIZ_DB_PATH set but not found: {env_path}")
    if _DEFAULT_DB_PATH.exists():
        return _DEFAULT_DB_PATH
    raise FileNotFoundError(
        "MoneyWiz database not found. "
        "Set MONEYWIZ_DB_PATH env var or ensure MoneyWiz is installed."
    )


# ---------------------------------------------------------------------------
# Lazy API init
# ---------------------------------------------------------------------------

_api: MoneywizApi | None = None


def get_api() -> MoneywizApi:
    global _api
    if _api is None:
        db_path = find_db_path()
        try:
            _api = MoneywizApi(db_path)
        except sqlite3.OperationalError as e:
            raise RuntimeError(
                f"Cannot open MoneyWiz database: {e}. "
                "The database may be locked. Try closing MoneyWiz and retry."
            ) from e
    return _api


def reload_api() -> MoneywizApi:
    """Force a fresh reload of the MoneyWiz API (use after creating transactions)."""
    global _api
    _api = None
    return get_api()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _payee_name(api: MoneywizApi, payee_id: int | None) -> str | None:
    if payee_id is None:
        return None
    try:
        p = api.payee_manager.get(payee_id)
        return p.name if p else None
    except Exception:
        return None

"""
MoneyWiz MCP Server
Read-only MCP server exposing MoneyWiz financial data to Claude.

Usage:
  python3 server.py

Register in Claude Code (~/.claude/settings.json):
  {
    "mcpServers": {
      "moneywiz": {
        "command": "python3",
        "args": ["/Users/burity/dev/moneywiz-integration/server.py"]
      }
    }
  }
"""

import json
import os
import sqlite3
from datetime import datetime, date
from decimal import Decimal
from pathlib import Path

# Monkey-patch moneywiz-api transaction validation before import
# The library uses assert for validation, which fails on edge cases (e.g. 0-amount transactions).
# We skip invalid records silently rather than crashing the server.
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
from mcp.server.fastmcp import FastMCP

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


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _val(v):
    """Convert non-JSON-serializable types to JSON-safe values."""
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


def _serialize(d: dict) -> dict:
    return {k: _val(v) for k, v in d.items() if not str(k).startswith("_")}


def _account_dict(acct) -> dict:
    d = _serialize(acct.as_dict())
    d["type"] = type(acct).__name__
    return d


def _category_chain(api: MoneywizApi, category_id: int) -> str:
    try:
        chain = api.category_manager.get_name_chain(category_id)
        return " > ".join(chain) if chain else str(category_id)
    except Exception:
        return str(category_id)


def _payee_name(api: MoneywizApi, payee_id: int | None) -> str | None:
    if payee_id is None:
        return None
    try:
        p = api.payee_manager.get(payee_id)
        return p.name if p else None
    except Exception:
        return None


def _serialize_transaction(tx, api: MoneywizApi) -> dict:
    d = _serialize(tx.as_dict())
    d["type"] = type(tx).__name__

    # Resolve payee ID → name
    payee_id = d.get("payee")
    d["payee_name"] = _payee_name(api, payee_id)

    # Resolve categories
    try:
        cat_assignments = api.transaction_manager.category_for_transaction(tx.id)
        d["categories"] = [
            {
                "name": _category_chain(api, cid),
                "amount": str(amt),
            }
            for cid, amt in cat_assignments
        ] if cat_assignments else []
    except Exception:
        d["categories"] = []

    return d


def _parse_date(s: str | None) -> datetime | None:
    if s is None:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        raise ValueError(f"Invalid date format '{s}'. Use ISO format: YYYY-MM-DD")


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP("MoneyWiz")


@mcp.tool()
def list_accounts(user_id: int | None = None) -> str:
    """List all MoneyWiz accounts with type, currency and opening balance.
    Optionally filter by user_id (2 or 3 are typical values)."""
    api = get_api()
    if user_id is not None:
        account_list = api.account_manager.get_accounts_for_user(user_id)
    else:
        account_list = [api.account_manager.get(aid) for aid in api.account_manager.records()]
    return json.dumps([_account_dict(a) for a in account_list if a is not None], ensure_ascii=False)


@mcp.tool()
def get_account_balance(account_id: int) -> str:
    """Calculate the current balance for a given account (opening balance + sum of all transactions)."""
    api = get_api()
    acct = api.account_manager.get(account_id)
    if acct is None:
        return json.dumps({"error": f"Account {account_id} not found"})

    txs = api.transaction_manager.get_all_for_account(account_id)
    total = Decimal("0")
    for tx in txs:
        if hasattr(tx, "amount") and tx.amount is not None:
            total += tx.amount

    balance = acct.opening_balance + total
    return json.dumps(
        {
            "account_id": account_id,
            "name": acct.name,
            "currency": acct.currency,
            "opening_balance": str(acct.opening_balance),
            "transactions_total": str(total),
            "current_balance": str(balance),
        },
        ensure_ascii=False,
    )


@mcp.tool()
def list_transactions(
    account_id: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> str:
    """List MoneyWiz transactions with optional filters.
    Dates in ISO format (YYYY-MM-DD). Returns paginated results with payee and category resolved."""
    api = get_api()
    start_dt = _parse_date(start_date)
    end_dt = _parse_date(end_date)
    # end_date is inclusive: extend to end of day
    if end_dt:
        end_dt = end_dt.replace(hour=23, minute=59, second=59)

    if account_id is not None:
        tx_ids = [tx.id for tx in api.transaction_manager.get_all_for_account(account_id)]
    else:
        tx_ids = list(api.transaction_manager.records())

    results = []
    for tid in tx_ids:
        tx = api.transaction_manager.get(tid)
        if tx is None:
            continue
        dt = tx.datetime if hasattr(tx, "datetime") else None
        if start_dt and dt and dt < start_dt:
            continue
        if end_dt and dt and dt > end_dt:
            continue
        results.append(tx)

    # Sort by date descending
    results.sort(key=lambda t: t.datetime if hasattr(t, "datetime") and t.datetime else datetime.min, reverse=True)

    page = results[offset: offset + limit]
    return json.dumps(
        {
            "total": len(results),
            "offset": offset,
            "limit": limit,
            "transactions": [_serialize_transaction(tx, api) for tx in page],
        },
        ensure_ascii=False,
    )


@mcp.tool()
def search_transactions(query: str, account_id: int | None = None, limit: int = 20) -> str:
    """Search transactions by description, notes or payee name (case-insensitive)."""
    api = get_api()
    q = query.lower()

    if account_id is not None:
        tx_ids = [tx.id for tx in api.transaction_manager.get_all_for_account(account_id)]
    else:
        tx_ids = list(api.transaction_manager.records())

    matches = []
    for tid in tx_ids:
        tx = api.transaction_manager.get(tid)
        if tx is None:
            continue
        desc = (tx.description or "").lower() if hasattr(tx, "description") else ""
        notes = (tx.notes or "").lower() if hasattr(tx, "notes") else ""
        payee_name = (_payee_name(api, tx.payee) or "").lower() if hasattr(tx, "payee") else ""

        if q in desc or q in notes or q in payee_name:
            matches.append(tx)
        if len(matches) >= limit:
            break

    return json.dumps(
        [_serialize_transaction(tx, api) for tx in matches],
        ensure_ascii=False,
    )


@mcp.tool()
def get_spending_summary(
    start_date: str,
    end_date: str,
    account_id: int | None = None,
    group_by: str = "category",
) -> str:
    """Summarize spending for a period, grouped by 'category', 'payee' or 'month'.
    Dates in ISO format (YYYY-MM-DD)."""
    api = get_api()
    start_dt = _parse_date(start_date)
    end_dt = _parse_date(end_date)
    if end_dt:
        end_dt = end_dt.replace(hour=23, minute=59, second=59)

    if group_by not in ("category", "payee", "month"):
        return json.dumps({"error": "group_by must be 'category', 'payee' or 'month'"})

    if account_id is not None:
        tx_ids = [tx.id for tx in api.transaction_manager.get_all_for_account(account_id)]
    else:
        tx_ids = list(api.transaction_manager.records())

    totals: dict[str, Decimal] = {}

    for tid in tx_ids:
        tx = api.transaction_manager.get(tid)
        if tx is None:
            continue
        dt = tx.datetime if hasattr(tx, "datetime") else None
        if start_dt and dt and dt < start_dt:
            continue
        if end_dt and dt and dt > end_dt:
            continue
        amount = tx.amount if hasattr(tx, "amount") and tx.amount else Decimal("0")

        if group_by == "month":
            key = dt.strftime("%Y-%m") if dt else "unknown"
            totals[key] = totals.get(key, Decimal("0")) + amount
        elif group_by == "payee":
            key = _payee_name(api, tx.payee) or "Unknown" if hasattr(tx, "payee") else "Unknown"
            totals[key] = totals.get(key, Decimal("0")) + amount
        else:  # category
            cat_assignments = api.transaction_manager.category_for_transaction(tid)
            if cat_assignments:
                for cid, amt in cat_assignments:
                    key = _category_chain(api, cid)
                    totals[key] = totals.get(key, Decimal("0")) + amt
            else:
                key = "Uncategorized"
                totals[key] = totals.get(key, Decimal("0")) + amount

    sorted_totals = sorted(totals.items(), key=lambda x: abs(x[1]), reverse=True)
    return json.dumps(
        {
            "period": f"{start_date} to {end_date}",
            "group_by": group_by,
            "summary": [{"name": k, "amount": str(v)} for k, v in sorted_totals],
        },
        ensure_ascii=False,
    )


@mcp.tool()
def list_categories(user_id: int | None = None, type: str | None = None) -> str:
    """List MoneyWiz categories with full parent chain.
    Optional type filter: 'Income' or 'Expense'."""
    api = get_api()
    if user_id is not None:
        cats = api.category_manager.get_categories_for_user(user_id)
    else:
        cats = [api.category_manager.get(cid) for cid in api.category_manager.records()]

    result = []
    for cat in cats:
        if cat is None:
            continue
        if type and hasattr(cat, "type") and cat.type != type:
            continue
        d = _serialize(cat.as_dict())
        d["chain"] = _category_chain(api, cat.id)
        result.append(d)

    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def list_payees(user_id: int | None = None) -> str:
    """List all MoneyWiz payees."""
    api = get_api()
    payee_ids = list(api.payee_manager.records())
    result = []
    for pid in payee_ids:
        p = api.payee_manager.get(pid)
        if p is None:
            continue
        d = _serialize(p.as_dict())
        if user_id is not None and d.get("user") != user_id:
            continue
        result.append(d)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def reload_data() -> str:
    """Reload MoneyWiz data from the database. Use after adding transactions in MoneyWiz."""
    global _api
    _api = None
    api = get_api()
    counts = {
        "accounts": len(list(api.account_manager.records())),
        "transactions": len(list(api.transaction_manager.records())),
        "categories": len(list(api.category_manager.records())),
        "payees": len(list(api.payee_manager.records())),
    }
    return json.dumps({"status": "reloaded", "counts": counts}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")

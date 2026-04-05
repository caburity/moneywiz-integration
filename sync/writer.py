"""
Writer: creates transactions in MoneyWiz via URL Schemas.

For each transaction:
  - Builds moneywiz://expense? or moneywiz://income? URL
  - Invokes via subprocess.run(["open", url]) on macOS
  - Waits DELAY_SECONDS for MoneyWiz to process
  - Verifies the transaction was created (reload DB + check)
  - Retries verification once if unverified

Yields SSE-compatible progress dicts (suitable for json.dumps).
Final event: {"done": True, "synced": N, "unverified": M, "error": K}
"""

import sqlite3
import subprocess
import time
from datetime import date
from decimal import Decimal
from typing import Generator
from urllib.parse import quote

from moneywiz_utils import find_db_path, reload_api
from sync.comparator import _make_key, _find_account_id

DELAY_SECONDS = 3
PAYEE = "Automacao"
CURRENCY = "EUR"


def sync_transactions(transactions: list[dict]) -> Generator[dict, None, None]:
    """
    Sync a list of transactions to MoneyWiz.

    Each dict must have: date, description, amount (Decimal), type ("expense"|"income"), account.

    Yields progress dicts:
      {"current": N, "total": M, "status": "synced"|"unverified"|"error",
       "description": str, "amount": str}
    Final yield:
      {"done": True, "synced": N, "unverified": M, "error": K}
    """
    total = len(transactions)
    synced = 0
    unverified = 0
    errors = 0

    for i, tx in enumerate(transactions, start=1):
        try:
            url = _build_url(tx)
        except Exception as e:
            yield {
                "current": i,
                "total": total,
                "status": "error",
                "description": tx.get("description", ""),
                "amount": str(tx.get("amount", "")),
                "message": f"Erro ao construir URL: {e}",
            }
            errors += 1
            continue

        # Invoke URL Schema
        try:
            subprocess.run(["open", url], check=True, capture_output=True)
        except FileNotFoundError:
            yield {
                "current": i,
                "total": total,
                "status": "error",
                "description": tx.get("description", ""),
                "amount": str(tx.get("amount", "")),
                "message": "Comando 'open' não encontrado. Apenas suportado em macOS.",
            }
            errors += 1
            continue
        except subprocess.CalledProcessError as e:
            yield {
                "current": i,
                "total": total,
                "status": "error",
                "description": tx.get("description", ""),
                "amount": str(tx.get("amount", "")),
                "message": f"Erro ao invocar URL Schema: {e}",
            }
            errors += 1
            continue

        # Wait for MoneyWiz to process
        time.sleep(DELAY_SECONDS)

        # Verify the transaction was created
        verified = _verify(tx)
        if not verified:
            # Retry once
            time.sleep(DELAY_SECONDS)
            verified = _verify(tx)

        if verified:
            status = "synced"
            synced += 1
        else:
            status = "unverified"
            unverified += 1

        yield {
            "current": i,
            "total": total,
            "status": status,
            "description": tx.get("description", ""),
            "amount": str(tx.get("amount", "")),
        }

    yield {"done": True, "synced": synced, "unverified": unverified, "error": errors}


def _build_url(tx: dict) -> str:
    """Build a moneywiz:// URL for a transaction dict."""
    tx_type = tx.get("type", "expense")
    schema = "expense" if tx_type == "expense" else "income"

    tx_date: date = tx["date"]
    amount: Decimal = tx["amount"]
    description: str = tx.get("description", "")
    account: str = tx.get("account", "")

    # MoneyWiz expects "yyyy-MM-dd HH:mm:ss"
    date_str = f"{tx_date.isoformat()} 12:00:00"

    params = {
        "amount": f"{amount:.2f}".replace(".", ","),
        "account": account,
        "payee": PAYEE,
        "description": description,
        "date": date_str,
        "save": "true",
        "currency": CURRENCY,
    }

    # Build query string with proper URL encoding
    # Colons are kept unencoded in date values (safe=':') as MoneyWiz expects "HH:mm:ss"
    query = "&".join(
        f"{k}={quote(str(v), safe=':')}" for k, v in params.items()
    )
    return f"moneywiz://{schema}?{query}"


def _wal_checkpoint() -> None:
    """Force a WAL checkpoint so moneywiz-api sees the latest writes from MoneyWiz."""
    try:
        db_path = find_db_path()
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
        conn.close()
    except Exception:
        pass


def _verify(tx: dict) -> bool:
    """
    Reload the MoneyWiz API and check if the transaction now exists.
    Forces a WAL checkpoint first to ensure we see MoneyWiz's latest writes.
    Uses the same (date, abs(amount)) matching as the comparator.
    """
    try:
        _wal_checkpoint()
        api = reload_api()
        account_id = _find_account_id(api, tx["account"])
        if account_id is None:
            return False

        key = _make_key(tx["date"], tx["amount"])

        for mw_tx in api.transaction_manager.get_all_for_account(account_id):
            if mw_tx is None:
                continue
            mw_date = mw_tx.datetime.date() if hasattr(mw_tx, "datetime") and mw_tx.datetime else None
            mw_amount = mw_tx.amount if hasattr(mw_tx, "amount") and mw_tx.amount is not None else Decimal("0")
            if mw_date and _make_key(mw_date, mw_amount) == key:
                return True
        return False
    except Exception:
        return False

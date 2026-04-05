"""
Comparator: identifies new transactions from a parsed PDF statement
by comparing against what already exists in MoneyWiz.

Matching key: (date_str, abs(amount) rounded to 2 decimals)
Count-based: new_count = max(0, pdf_count - moneywiz_count) per key
"""

from collections import Counter
from datetime import date
from decimal import Decimal

from moneywiz_utils import get_api


def compare(parsed_txs: list[dict], account_name: str) -> dict:
    """
    Compare parsed PDF transactions against MoneyWiz for the given account.

    Args:
        parsed_txs: list of dicts from parser (keys: date, description, amount, type, account)
        account_name: exact MoneyWiz account name (e.g. "Cartão 123")

    Returns:
        {
            "new_transactions": [list of new tx dicts with added "key" field],
            "summary": {
                "total_pdf": N,
                "existing": M,
                "new": K,
                "account": account_name,
            }
        }
    """
    if not parsed_txs:
        return {
            "new_transactions": [],
            "summary": {"total_pdf": 0, "existing": 0, "new": 0, "account": account_name},
        }

    api = get_api()

    # Find account by name
    account_id = _find_account_id(api, account_name)

    # Build counter of existing MoneyWiz transactions for this account
    mw_counter: Counter = Counter()
    if account_id is not None:
        for tx in api.transaction_manager.get_all_for_account(account_id):
            if tx is None:
                continue
            tx_date = tx.datetime.date() if hasattr(tx, "datetime") and tx.datetime else None
            tx_amount = tx.amount if hasattr(tx, "amount") and tx.amount is not None else Decimal("0")
            if tx_date is not None:
                key = _make_key(tx_date, tx_amount)
                mw_counter[key] += 1

    # Build counter of PDF transactions
    pdf_counter: Counter = Counter()
    for tx in parsed_txs:
        key = _make_key(tx["date"], tx["amount"])
        pdf_counter[key] += 1

    # Compute new transactions
    new_transactions = []
    # Track how many of each key we've emitted already
    emitted: Counter = Counter()

    for tx in parsed_txs:
        key = _make_key(tx["date"], tx["amount"])
        # How many of this key are truly new?
        truly_new = max(0, pdf_counter[key] - mw_counter[key])
        if emitted[key] < truly_new:
            new_transactions.append({**tx, "key": key})
            emitted[key] += 1

    total_new = len(new_transactions)
    total_pdf = len(parsed_txs)
    existing = total_pdf - total_new

    return {
        "new_transactions": new_transactions,
        "summary": {
            "total_pdf": total_pdf,
            "existing": existing,
            "new": total_new,
            "account": account_name,
        },
    }


def _find_account_id(api, name: str) -> int | None:
    """Find a MoneyWiz account ID by exact name match (case-insensitive)."""
    for aid in api.account_manager.records():
        acct = api.account_manager.get(aid)
        if acct and acct.name.strip().lower() == name.strip().lower():
            return acct.id
    return None


def _make_key(tx_date: date, amount: Decimal) -> str:
    """Build a match key from date and absolute amount (2 decimal places)."""
    return f"{tx_date.isoformat()}|{abs(amount):.2f}"

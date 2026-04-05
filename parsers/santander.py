"""
Parser for Santander Totta credit card PDF statements.

Expected section: "Listagem Movimentos"
Date format: DD-MM-YYYY
Amount: comma decimal + " EUR" (e.g. "10,99 EUR")
D = Debit (expense), C = Credit (income)
Two physical cards in same statement: TPA*2681, TPA*1881, ESTRANG*2681, ESTRANG*1881
All map to account "Cartão 123".
Multi-line descriptions: continuation lines (no movement number prefix) append to previous.
"""

import re
from datetime import date
from decimal import Decimal, InvalidOperation

import pdfplumber

_SECTION_ANCHOR = "Listagem Movimentos"
_ACCOUNT_NAME = "Cartão123"

# Transactions starting with these strings are ignored
_IGNORE_PREFIXES = (
    "PAG.TRANS.BANCARIA",
    "COMISSAO DISPONIBILIZACAO",
    "BONIF. COMISS DISPONIBILIZACAO",
)

# Prefix to strip from description: "COMPRA TPA*2681 " or "COMPRA ESTRANG*1881 " etc.
_CARD_PREFIX_RE = re.compile(r"COMPRA\s+(TPA|ESTRANG)\*\d{4}\s+")

# Transaction start: 9-digit movement number + space + DD-MM-YYYY
# e.g. "602130001  11-02-2026  COMPRA TPA*2681 ..."
_TX_START_RE = re.compile(r"^\d{6,12}\s+(\d{2})-(\d{2})-(\d{4})\s+(.*)")

# Amount at end of line: optional D/C indicator + amount with comma + EUR
# e.g. "D  10,99 EUR" or "C  150,00 EUR"
_AMOUNT_RE = re.compile(r"\b(D|C)\s+([\d\.]+,\d{2})\s+EUR\s*$")


def parse(pdf_path: str) -> list[dict]:
    """
    Parse a Santander Totta PDF statement.

    Returns a list of dicts:
      {date, description, amount (Decimal), type ("expense"|"income"), account}

    Raises ValueError if the PDF does not look like a Santander Totta statement.
    """
    text = _extract_text(pdf_path)

    if _SECTION_ANCHOR not in text:
        raise ValueError(
            f"Ficheiro não reconhecido como extrato Santander Totta "
            f"(secção '{_SECTION_ANCHOR}' não encontrada)."
        )

    return _extract_transactions(text)


def _extract_text(pdf_path: str) -> str:
    try:
        pages = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    pages.append(t)
        return "\n".join(pages)
    except Exception as e:
        raise ValueError(f"Não foi possível ler o ficheiro PDF: {e}") from e


def _extract_transactions(text: str) -> list[dict]:
    section_start = text.find(_SECTION_ANCHOR)
    lines = text[section_start:].splitlines()

    transactions = []
    current: dict | None = None

    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue

        m = _TX_START_RE.match(line_stripped)
        if m:
            # Commit previous transaction if any
            if current is not None:
                result = _finalise(current)
                if result:
                    transactions.append(result)

            day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
            rest = m.group(4).strip()
            current = {
                "date": date(year, month, day),
                "raw_desc": rest,
            }
        elif current is not None:
            # Continuation line — append to description
            # Stop on typical table headers or footers
            if re.match(r"^(Movimento|Data|Descricao|Estado|Montante|Saldo|Total|Pagina)", line_stripped, re.IGNORECASE):
                result = _finalise(current)
                if result:
                    transactions.append(result)
                current = None
            else:
                current["raw_desc"] = current["raw_desc"] + " " + line_stripped

    # Commit last transaction
    if current is not None:
        result = _finalise(current)
        if result:
            transactions.append(result)

    return transactions


def _finalise(tx: dict) -> dict | None:
    """Extract amount/type from raw_desc, clean description, apply filters."""
    raw = tx["raw_desc"]

    # Extract amount and D/C type
    amount_m = _AMOUNT_RE.search(raw)
    if not amount_m:
        return None

    dc = amount_m.group(1)          # "D" or "C"
    amount_str = amount_m.group(2)  # e.g. "10,99"

    try:
        # Strip thousands dots, then convert comma decimal to dot: "1.234,56" → "1234.56"
        amount = Decimal(amount_str.replace(".", "").replace(",", "."))
    except InvalidOperation:
        return None

    # Remove amount+type suffix from description text
    description = raw[:amount_m.start()].strip()

    # Remove "EXTRACTADO" status word if present
    description = re.sub(r"\bEXTRACTADO\b", "", description).strip()

    # Check ignore list before stripping prefix
    if any(description.startswith(p) for p in _IGNORE_PREFIXES):
        return None

    # Strip card prefix: "COMPRA TPA*2681 " etc.
    description = _CARD_PREFIX_RE.sub("", description).strip()

    # Skip if description is empty after cleaning
    if not description:
        return None

    tx_type = "expense" if dc == "D" else "income"

    return {
        "date": tx["date"],
        "description": description,
        "amount": amount,
        "type": tx_type,
        "account": _ACCOUNT_NAME,
    }

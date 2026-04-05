"""
Parser for Millennium BCP credit card PDF statements.

Expected section: "DETALHE DOS MOVIMENTOS"
Date format: YYYY/MM/DD
Amount: dot decimal in Débito column (e.g. 36.43)
Each transaction spans 2 lines: main line + VIS/milhas line (skipped)
"""

import re
from datetime import date
from decimal import Decimal, InvalidOperation

import pdfplumber


_IMPORT_PREFIX = "COMPRA 0382 "
# Additional importable prefixes that don't have a VIS/milhas secondary line
_EXTRA_IMPORT_PREFIXES = (
    "TAXAS POSTOS COMBUSTIVEL",
    "IMPOSTO DO SELO",
    ">PAGAMENTO CARTAO DE CREDITO",
)
_SECTION_ANCHOR = "DETALHE DOS MOVIMENTOS"
_ACCOUNT_NAME = "Cartão Millennium"

# Matches date at start of a main transaction line: YYYY/MM/DD
_DATE_RE = re.compile(r"^(\d{4})/(\d{2})/(\d{2})\s")
# Matches the last decimal amount on the line (Débito or Crédito column)
# Millennium uses dot as decimal separator only: e.g. "36.43" or "1036.43"
_AMOUNT_RE = re.compile(r"([\d.]+\.\d{2})\s*$")


def parse(pdf_path: str) -> list[dict]:
    """
    Parse a Millennium BCP PDF statement.

    Returns a list of dicts:
      {date, description, amount (Decimal), type ("expense"), account}

    Raises ValueError if the PDF does not look like a Millennium BCP statement.
    """
    text = _extract_text(pdf_path)

    if _SECTION_ANCHOR not in text:
        raise ValueError(
            f"Ficheiro não reconhecido como extrato Millennium BCP "
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
    # Find section start
    section_start = text.find(_SECTION_ANCHOR)
    lines = text[section_start:].splitlines()

    transactions = []
    skip_next = False  # Used to skip VIS/milhas secondary lines

    for line in lines:
        line = line.strip()

        if not line:
            continue

        # After a transaction main line, the next non-empty line is the VIS/milhas line
        if skip_next:
            skip_next = False
            continue

        m = _DATE_RE.match(line)
        if not m:
            continue

        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))

        # The rest after the date field — find the descriptive text
        rest = line[len(m.group(0)):]

        # Identify and skip date-value column (second date in the line YYYY/MM/DD)
        rest = re.sub(r"^\d{4}/\d{2}/\d{2}\s*", "", rest)

        # Check if this is an importable transaction
        is_main_import = rest.startswith(_IMPORT_PREFIX)
        is_extra = any(rest.startswith(p) for p in _EXTRA_IMPORT_PREFIXES)

        if not is_main_import and not is_extra:
            continue

        # Extract amount (last decimal on the line)
        amount_m = _AMOUNT_RE.search(rest)
        if not amount_m:
            if is_main_import:
                skip_next = True
            continue

        try:
            # Millennium uses dot as decimal separator only (no thousands separator)
            raw_amount = amount_m.group(1)
            amount = Decimal(raw_amount)
        except InvalidOperation:
            if is_main_import:
                skip_next = True
            continue

        # Clean description
        if is_main_import:
            description = rest[len(_IMPORT_PREFIX):]
        else:
            # For TAXAS/IMPOSTO: use the prefix itself as description
            description = rest

        # Remove the amount and anything after it from description
        description = _AMOUNT_RE.sub("", description).strip()
        # Remove trailing network/card identifiers (e.g. "VIS", "MC", etc.)
        description = re.sub(r"\s+(VIS|MC|AME|MST)\s*$", "", description).strip()

        # Payments to credit card are income (credit), everything else is expense (debit)
        tx_type = "income" if rest.startswith(">PAGAMENTO CARTAO DE CREDITO") else "expense"

        transactions.append({
            "date": date(year, month, day),
            "description": description,
            "amount": amount,
            "type": tx_type,
            "account": _ACCOUNT_NAME,
        })

        # Only COMPRA lines have a VIS/milhas secondary line to skip
        if is_main_import:
            skip_next = True

    return transactions

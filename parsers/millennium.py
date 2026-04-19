"""
Parser for Millennium BCP credit card statements.

Supports two formats:
  - PDF: extrato oficial (section "DETALHE DOS MOVIMENTOS")
  - CSV: export "Saldos e movimentos" (UTF-16 LE, semicolon-separated)
"""

import csv
import io
import re
from datetime import date
from decimal import Decimal, InvalidOperation

import pdfplumber


_IMPORT_PREFIX = "COMPRA 0382 "
# Additional importable prefixes that don't have a VIS/milhas secondary line
_EXTRA_IMPORT_PREFIXES = (
    "TAXAS POSTOS COMBUSTIVEL",
    "IMPOSTO DO SELO",
    "CUSTO DE SERVICO INTERNACIONAL",
    ">PAGAMENTO CARTAO DE CREDITO",
)
# PAGAMENTO may appear without the ">" prefix (CSV format)
_PAGAMENTO_NAMES = (
    ">PAGAMENTO CARTAO DE CREDITO",
    "PAGAMENTO CARTAO DE CREDITO",
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
        tx_type = "income" if any(rest.startswith(p) for p in _PAGAMENTO_NAMES) else "expense"

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


# ---------------------------------------------------------------------------
# CSV parser (Millennium "Saldos e movimentos" export)
# ---------------------------------------------------------------------------

_CSV_SECTION_ANCHOR = "millenniumbcp.pt"
_CSV_HEADER_START = "Data de lançamento"
_CSV_DATE_RE = re.compile(r"^(\d{2})-(\d{2})-(\d{4})$")


def parse_csv(csv_path: str) -> list[dict]:
    """
    Parse a Millennium BCP CSV export ("Saldos e movimentos").

    Format: UTF-16 LE, semicolon-separated, header after metadata rows.
    Columns: Data de lançamento;Data valor;Descrição;Rede;Montante

    Raises ValueError if the CSV does not look like a Millennium export.
    """
    text = _read_csv_text(csv_path)

    if _CSV_SECTION_ANCHOR not in text:
        raise ValueError(
            f"Ficheiro não reconhecido como export Millennium BCP "
            f"(referência '{_CSV_SECTION_ANCHOR}' não encontrada)."
        )

    return _extract_csv_transactions(text)


def _read_csv_text(csv_path: str) -> str:
    """Read CSV trying UTF-16 LE first (Millennium default), then fallback."""
    for encoding in ("utf-16-le", "utf-16", "utf-8-sig", "utf-8", "latin-1"):
        try:
            with open(csv_path, encoding=encoding) as f:
                text = f.read()
            if "millenniumbcp" in text:
                return text
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise ValueError("Não foi possível ler o ficheiro CSV (encoding desconhecido).")


def _extract_csv_transactions(text: str) -> list[dict]:
    # Find header row
    lines = text.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        if line.lstrip().startswith(_CSV_HEADER_START):
            header_idx = i
            break

    if header_idx is None:
        raise ValueError(
            f"Ficheiro CSV Millennium sem cabeçalho '{_CSV_HEADER_START}'."
        )

    data_rows = lines[header_idx + 1:]
    reader = csv.reader(io.StringIO("\n".join(data_rows)), delimiter=";")

    transactions = []
    for row in reader:
        if len(row) < 5:
            continue

        date_str = row[0].strip()
        description = row[2].strip()
        network = row[3].strip()
        amount_str = row[4].strip()

        # Skip empty/invalid rows
        date_m = _CSV_DATE_RE.match(date_str)
        if not date_m:
            continue

        day, month, year = int(date_m.group(1)), int(date_m.group(2)), int(date_m.group(3))

        # Parse amount (can be negative for credit card payments)
        try:
            amount = Decimal(amount_str)
        except InvalidOperation:
            continue

        # Skip zero amounts
        if amount == 0:
            continue

        # All rows with a valid date + amount are importable
        # (CSV is already filtered to movement rows; no need for prefix matching)
        is_pagamento = any(description.startswith(p) for p in _PAGAMENTO_NAMES)

        # Clean description: strip COMPRA import prefix if present
        if description.startswith(_IMPORT_PREFIX):
            clean_desc = description[len(_IMPORT_PREFIX):].strip()
        else:
            clean_desc = description

        # Classify type: negative amount or PAGAMENTO → income, otherwise expense
        if amount < 0 or is_pagamento:
            tx_type = "income"
        else:
            tx_type = "expense"

        # Amount should always be positive (MoneyWiz handles sign via type)
        amount = abs(amount)

        transactions.append({
            "date": date(year, month, day),
            "description": clean_desc,
            "amount": amount,
            "type": tx_type,
            "account": _ACCOUNT_NAME,
        })

    return transactions

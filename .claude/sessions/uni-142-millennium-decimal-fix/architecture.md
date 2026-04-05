# Architecture: UNI-142 — Millennium Decimal Parser Fix

## Overview

### Before
```
parsers/millennium.py
  _extract_transactions()
    _AMOUNT_RE captures e.g. "10.00" or "1.036.43"
    rsplit(".", 1) → ["10", "00"] or ["1.036", "43"]
    replace(".", "") on integer part → "10" or "1036"
    Decimal(f"{integer}.{decimal}") → OK for "1036.43" but WRONG for "10.00" → 1000
```

### After
```
parsers/millennium.py
  _extract_transactions()
    _AMOUNT_RE captures e.g. "10.00" or "1036.43"
    Decimal(raw_amount) → always correct
```

## Affected Components

| File | Change |
|------|--------|
| `parsers/millennium.py` | Remove 3 lines, replace with 1 line |

## Files NOT affected

- `parsers/santander.py` — usa vírgula como decimal, lógica independente
- `sync/comparator.py` — recebe Decimal já corrigido
- `sync/writer.py` — recebe Decimal já corrigido
- `app.py` — nenhuma alteração
- `moneywiz_utils.py` — nenhuma alteração

## Assumptions

- O formato Millennium BCP nunca usa separador de milhar nos montantes do extrato
- A regex `_AMOUNT_RE = re.compile(r"([\d.]+\.\d{2})\s*$")` captura correctamente todos os montantes
- `Decimal(raw_amount)` não vai lançar `InvalidOperation` porque a regex já garante formato numérico válido (o `except (InvalidOperation, IndexError)` pode ser simplificado para `except InvalidOperation`)

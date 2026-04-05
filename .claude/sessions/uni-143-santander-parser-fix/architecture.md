# Architecture: UNI-143 — Santander Parser Fix

## Overview

### Before (broken)
```
_SECTION_ANCHOR = "Listagem Movimentos"   → not found in "ListagemMovimentos"
_CARD_PREFIX_RE = r"COMPRA\s+(TPA|ESTRANG)\*\d{4}\s+" → no match on "COMPRATPA*2681..."
_AMOUNT_RE = r"(D|C)\s+([\d\.]+,\d{2})\s+EUR\s*$"    → no match on "PENDENTE D 3,00EUR"
```

### After (fixed)
```
_SECTION_ANCHOR = "ListagemMovimentos"
_CARD_PREFIX_RE = r"COMPRA(TPA|ESTRANG)\*\d{4}"
_AMOUNT_RE = r"PENDENTE\s+(D|C)\s+([\d\.]+,\d{2})EUR\s*$"
```

## Affected Files

| File | Change |
|------|--------|
| `parsers/santander.py` | 3 constantes ajustadas |

## Files NOT affected

- `sync/writer.py` — amount comma fix já aplicado (UNI-142)
- `parsers/millennium.py` — independente
- `app.py`, `sync/comparator.py`, etc. — nenhuma alteração

## Notes

- `_TX_START_RE` já não usa `\s+` entre campos posicionais — OK
- Multi-line descriptions: linhas de continuação continuam sem número de movimento — comportamento mantido
- Ignore list do Santander: COMISSAO DISPONIBILIZACAO e BONIF são ignoradas por `_IGNORE_PREFIXES` — validar se devem continuar ignoradas

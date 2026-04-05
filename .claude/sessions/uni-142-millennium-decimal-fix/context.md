# Session Context: UNI-142 — Millennium Decimal Parser Fix

## Task Info

- **Task ID:** UNI-142 (Linear)
- **Title:** Bug: Millennium parser interpreta ponto como milhar em vez de decimal
- **Branch:** feature/uni-133-sync-app (bug pertence a esta branch, não se cria nova)
- **Story Points:** 1
- **Provider:** Linear

## Problem

`parsers/millennium.py` — lógica `rsplit(".", 1)` + `replace(".", "")` foi escrita para tratar separadores de milhar (ex: `1.036.43`). Mas o formato Millennium BCP **não usa separador de milhar** — o ponto é sempre e apenas separador decimal.

Resultado: `10.00` → interpretado como `1000` (errado).

## Fix

Ficheiro: `parsers/millennium.py`, linhas ~114–119.

**Antes:**
```python
raw_amount = amount_m.group(1)
parts = raw_amount.rsplit(".", 1)
integer_part = parts[0].replace(".", "")
amount = Decimal(f"{integer_part}.{parts[1]}")
```

**Depois:**
```python
raw_amount = amount_m.group(1)
amount = Decimal(raw_amount)
```

## Comportamento esperado

- `10.00` → `Decimal("10.00")` = 10,00
- `36.43` → `Decimal("36.43")` = 36,43
- `1036.43` → `Decimal("1036.43")` = 1036,43

## Phase→Subtask Mapping

- **Phase 1:** Fix parser — sem subtasks (ticket simples)

## Constraints

- Não criar nova branch
- Não alterar parser Santander
- Não alterar `_AMOUNT_RE`

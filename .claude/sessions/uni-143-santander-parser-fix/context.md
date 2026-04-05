# Session Context: UNI-143 — Santander Parser Fix

## Task Info

- **Task ID:** UNI-143 (Linear)
- **Title:** Bug: Parser Santander não reconhece PDF (secção Listagem Movimentos não encontrada)
- **Branch:** feature/uni-143-santander-parser-fix (baseada em feature/uni-133-sync-app)
- **Story Points:** 3
- **Provider:** Linear

## Root Cause

O `pdfplumber` extrai o texto do PDF Santander com palavras concatenadas sem espaços.
Texto real extraído:
- `"ListagemMovimentos"` (anchor sem espaço)
- `"COMPRATPA*2681MERCADONADIREITA PENDENTE D 41,89EUR"` (prefixo colado)
- `"PENDENTE D 3,00EUR"` (sem espaço antes de EUR, com PENDENTE)

## 3 Fixes Necessários

| # | Constante | Antes | Depois |
|---|-----------|-------|--------|
| 1 | `_SECTION_ANCHOR` | `"Listagem Movimentos"` | `"ListagemMovimentos"` |
| 2 | `_CARD_PREFIX_RE` | `r"COMPRA\s+(TPA\|ESTRANG)\*\d{4}\s+"` | `r"COMPRA(TPA\|ESTRANG)\*\d{4}"` |
| 3 | `_AMOUNT_RE` | `r"(D\|C)\s+([\d\.]+,\d{2})\s+EUR\s*$"` | `r"PENDENTE\s+(D\|C)\s+([\d\.]+,\d{2})EUR\s*$"` |

## Ficheiro

`parsers/santander.py`

## Validação

Testar com `/Users/burity/Desktop/Santander.pdf` — deve extrair 11 transações:
- COMISSAO DISPONIBILIZACAO (x2) — D 3,00
- BONIF. COMISS DISPONIBILIZACAO — C 0,75
- COMPRA TPA/ESTRANG (x8) — vários montantes

## Phase→Subtask Mapping

- **Phase 1:** Fix santander.py — sem subtasks (ticket simples)

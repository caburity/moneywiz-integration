# Session Context: UNI-132 — MCP Server Read-Only

## Task
Epic UNI-132: Fase 1 completa — MCP Server read-only que expõe dados do MoneyWiz ao Claude.

## Subtasks
- **UNI-134** (1pt): Setup inicial + requirements.txt ✅
- **UNI-135** (5pt): Implementar server.py com 8 MCP tools ✅
- **UNI-136** (2pt): Registar MCP no Claude Code + teste e2e ✅

## Objective
Servidor MCP read-only (stdio) que permite ao Claude consultar dados financeiros do MoneyWiz em linguagem natural: contas, transações, categorias, payees, saldos e sumários de spending.

## Outcome
- `server.py` implementado com 8 tools MCP funcionais
- MCP registado via `claude mcp add` → `moneywiz: ✓ Connected`
- PR caburity/moneywiz-integration#1 merged para main

## Key Decisions
1. **Monkey-patch de validação**: moneywiz-api usa `assert amount * original_amount > 0` que falha em transações de montante 0 (e.g. salary splits). Solução: patch de todas as classes `validate()` para ignorar AssertionError silenciosamente.
2. **Lazy init**: `get_api()` só inicializa na primeira chamada (~2-3s). Subsequentes são instantâneas.
3. **pytest como runtime dep**: moneywiz-api importa `pytest.approx()` em constructores de modelos.
4. **user_id 2 e 3**: O utilizador principal tem contas nos users 2 (43 contas) e 3 (61 contas).

## DB Path
`~/Library/Containers/com.moneywiz.personalfinance/Data/Documents/.AppData/ipadMoneyWiz.sqlite`
(46MB, ~30942 transações, 104 contas)

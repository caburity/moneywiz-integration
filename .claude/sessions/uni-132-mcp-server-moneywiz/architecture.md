# Architecture: MCP Server Read-Only

## Stack
- Python 3.14.2
- FastMCP (`mcp>=1.20.0`) — stdio transport
- moneywiz-api v1.0.6 — acesso direto ao SQLite do MoneyWiz
- pytest (runtime dep do moneywiz-api)

## Entry Point
```
python3 server.py   →   mcp.run(transport="stdio")
```

## Key Components

### DB Path Discovery (`find_db_path`)
1. Verifica `MONEYWIZ_DB_PATH` env var
2. Fallback: `~/Library/Containers/com.moneywiz.personalfinance/Data/Documents/.AppData/ipadMoneyWiz.sqlite`
3. Lança `FileNotFoundError` se não encontrado

### Lazy API Init (`get_api`)
- Singleton global `_api: MoneywizApi | None`
- Inicializa na primeira chamada (eager load de ~30K transações, ~2-3s)
- Captura `sqlite3.OperationalError` com mensagem clara (DB locked)

### Monkey-Patch de Validação
Aplicado ANTES do import do MoneywizApi:
```python
for _name, _cls in inspect.getmembers(transaction_module, isclass):
    if hasattr(_cls, "validate"):
        _cls.validate = safe_wrapper(_cls.validate)  # swallow AssertionError
```
Necessário porque `DepositTransaction.validate()` faz `assert amount * original_amount > 0` — falha para transações com montante 0.

### Serialização
- `_val(v)`: Decimal→str, datetime→ISO 8601
- `_serialize(d)`: filtra campos `_private`, aplica `_val` a todos os valores
- `_account_dict(acct)`: adiciona campo `type` (nome da classe Python)
- `_serialize_transaction(tx, api)`: resolve payee_id→nome e category_id→chain

### MCP Tools (8)

| Tool | Descrição |
|------|-----------|
| `list_accounts` | Lista contas com filtro opcional por user_id |
| `get_account_balance` | opening_balance + soma de transações |
| `list_transactions` | Paginado, filtrado por conta/data, ordenado desc |
| `search_transactions` | Busca em description/notes/payee (case-insensitive) |
| `get_spending_summary` | Agrega por category/payee/month num período |
| `list_categories` | Com full parent chain, filtro por type |
| `list_payees` | Lista todos os payees |
| `reload_data` | Força reinit do API (para após adicionar transações no MoneyWiz) |

## Data Flow
```
Claude → MCP (stdio) → server.py → get_api() → MoneywizApi → SQLite (read-only)
                                              ↓
                                   _serialize_transaction()
                                   _category_chain()
                                   _payee_name()
                                              ↓
                                        JSON response
```

## Registration
```bash
claude mcp add moneywiz python3 /Users/burity/dev/moneywiz-integration/server.py
# Writes to ~/.claude.json
```

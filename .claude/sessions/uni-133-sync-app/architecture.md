# Architecture: UNI-133 Sync App

## System Overview

### Before (Fase 1 only)
```
Claude → MCP (stdio) → server.py → MoneywizApi → SQLite (read-only)
```

### After (Fase 1 + Fase 2)
```
Claude → MCP (stdio) → server.py → MoneywizApi → SQLite (read-only)

Browser → Flask (5050) → app.py
                          ├── parsers/millennium.py  ← PDF (Millennium)
                          ├── parsers/santander.py   ← PDF (Santander)
                          ├── sync/comparator.py  → MoneywizApi → SQLite (read)
                          ├── sync/backup.py      → SQLite copy (read+write filesystem)
                          └── sync/writer.py      → open moneywiz:// URL → MoneyWiz app
                                                                           ↓
                                                                     SQLite (written by MoneyWiz)
```

## File Structure (final state)

```
moneywiz-integration/
  server.py              # MCP server — now imports from moneywiz_utils.py
  moneywiz_utils.py      # NEW: shared utilities (monkey-patch, find_db_path, get_api, reload_data)
  app.py                 # NEW: Flask web app (routes, SSE, file upload orchestration)
  parsers/
    __init__.py          # empty
    millennium.py        # NEW: Millennium BCP PDF parser
    santander.py         # NEW: Santander Totta PDF parser
  sync/
    __init__.py          # empty
    comparator.py        # NEW: compare parsed vs MoneyWiz, count-based matching
    backup.py            # NEW: copy SQLite files to moneywiz-backups/
    writer.py            # NEW: create transactions via URL Schemas, yield SSE events
  templates/
    index.html           # NEW: single-page UI (upload, results, sync, progress)
  static/
    style.css            # NEW: minimal CSS
  moneywiz-backups/      # Created at runtime, gitignored
  uploads/               # Temp PDFs, gitignored
```

## Component Details

### `moneywiz_utils.py`
Extracted from `server.py` (currently inline). Contains:
- Monkey-patch block (silence AssertionError on 0-amount transactions)
- `_DEFAULT_DB_PATH`
- `find_db_path() -> Path`
- `_api: MoneywizApi | None` (singleton)
- `get_api() -> MoneywizApi`
- `reload_api()` — sets `_api = None` to force fresh init
- `_payee_name(api, payee_id) -> str | None`

`server.py` updated to: `from moneywiz_utils import find_db_path, get_api, reload_api, _payee_name`

### `parsers/millennium.py`
```python
def parse(pdf_path: str) -> list[dict]:
    # Returns list of {date, description, amount (Decimal), type, account}
```
- Uses pdfplumber
- Anchor: "DETALHE DOS MOVIMENTOS"
- Regex `\d{4}/\d{2}/\d{2}` for transaction start
- Strips "COMPRA 0382 " prefix
- Skips VIS/milhas secondary lines

### `parsers/santander.py`
```python
def parse(pdf_path: str) -> list[dict]:
    # Returns list of {date, description, amount (Decimal), type ("expense"|"income"), account}
```
- Uses pdfplumber
- Anchor: "Listagem Movimentos"
- Transaction start: 9-digit movement + date `\d{2}-\d{2}-\d{4}`
- Multi-line description: continuation lines append to previous
- Strips `COMPRA (TPA|ESTRANG)\*\d{4} ` regex prefix
- D → "expense", C → "income"

### `sync/comparator.py`
```python
def compare(parsed_txs: list[dict], account_name: str) -> dict:
    # Returns {"new_transactions": [...], "summary": {...}}
```
- Finds account by name via `get_api().account_manager`
- Builds Counter of `(date_str, f"{abs(amount):.2f}")` keys
- `new_count = max(0, pdf_count - moneywiz_count)` per key

### `sync/backup.py`
```python
def create_backup() -> Path:
    # Copies .sqlite + -wal + -shm to moneywiz-backups/YYYYMMDD_HHmmss/
```
- Uses `find_db_path()` from `moneywiz_utils`
- `shutil.copy2()` for metadata preservation
- Skips `-wal`/`-shm` silently if they don't exist

### `sync/writer.py`
```python
def sync_transactions(transactions: list[dict]) -> Generator[dict, None, None]:
    # Yields: {"current": N, "total": M, "status": "synced|unverified|error", ...}
```
- Builds `moneywiz://expense?` or `moneywiz://income?` URL
- `urllib.parse.urlencode()` for proper encoding
- `subprocess.run(["open", url])`
- `time.sleep(3)` + verify via `reload_api()` + comparator logic
- Retry once if unverified
- Final yield: `{"done": True, "synced": N, "unverified": M, "error": K}`

### `app.py`
```python
# Routes:
# GET  /           → render index.html
# POST /upload     → parse PDFs, compare, return JSON
# POST /sync       → backup + stream SSE from writer
```
- Parser detection: try `millennium.parse()`, on ValueError try `santander.parse()`
- In-memory session storage: `sessions = {}` (single-user, no persistence)
- SSE: `Response(stream_with_context(generate()), content_type="text/event-stream")`
- Startup: `threading.Timer(1.5, webbrowser.open, ["http://localhost:5050"]).start()`
- Port: 5050, debug=False in production

### `templates/index.html`
Single-page app with 4 sections (shown/hidden via JS):
1. Upload section (drag-and-drop)
2. Results section (tables by card)
3. Sync progress section (SSE)
4. Summary section

Vanilla JS only. `fetch()` for /upload, `EventSource` for SSE.

## Patterns Maintained

| Pattern | Source | Target |
|---------|--------|--------|
| Monkey-patch validation | server.py:26-45 | moneywiz_utils.py |
| Lazy init singleton | server.py:79-93 | moneywiz_utils.py |
| `find_db_path()` | server.py:60-72 | moneywiz_utils.py |
| `reload_data()` | server.py:401-412 | moneywiz_utils.py (renamed `reload_api()`) |
| UTF-8 / Portuguese encoding | server.py | All files |
| SQLite read via moneywiz-api | server.py | comparator.py, writer.py |

## Key Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| PDF format changes | Raise ValueError with clear message; show error in UI |
| MoneyWiz not open | Catch OSError from subprocess; show actionable error |
| URL Schema not verified | 3s delay + retry + mark "unverified" (not "failed") |
| DB locked during backup | Catch PermissionError; report to user |
| Duplicate sync | Comparison runs before every sync; if no new transactions, block Sync button |

## Testing Plan

1. **Parsers**: Run against real PDF samples, count transactions manually, assert equality
2. **Comparator**: Create a test set with known overlap, verify new_count is correct
3. **Backup**: Verify 3 files exist in backup dir with correct timestamps
4. **Writer**: Sync 1-2 test transactions, verify in MoneyWiz (or via MCP `list_transactions`)
5. **E2E**: Upload real PDF → Analyze → Select 2 → Sincronizar → confirm via MCP

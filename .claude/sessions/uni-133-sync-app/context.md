# Session Context: UNI-133 — Fase 2 Sync App

## Task IDs
- Epic: UNI-133 (`b0f9cd44-8db9-43a4-8daf-d2ddbaa4b546`)
- UNI-137 (`b5aa878f-7d83-4fbf-9038-fb9105ad82f8`) — Parser PDF Millennium BCP — 3 pts
- UNI-138 (`7ca0b872-528d-4a01-bfc8-292c89fc246f`) — Parser PDF Santander Totta — 3 pts
- UNI-139 (`12f84ff4-0bd6-4284-94d2-587c9d6fb294`) — Comparador + Backup — 5 pts
- UNI-140 (`9bc610b2-232b-4379-b81b-74f53b86a742`) — Writer via URL Schemas — 5 pts
- UNI-141 (`4345214f-211a-4fc3-92ce-eef0051310f6`) — Web App Flask + UI — 5 pts

## Branch
`feature/uni-133-sync-app`

## Why
Manual reconciliation of Portuguese bank credit card statements (Millennium BCP + Santander Totta) against MoneyWiz is time-consuming and error-prone. This app automates parsing, comparison and selective sync.

## What is Being Built

A local Flask web app (port 5050, auto-opens browser) that:
1. Accepts 1-2 PDF credit card statements via drag-and-drop UI
2. Parses transactions from each PDF (Millennium or Santander format auto-detected)
3. Compares parsed transactions against MoneyWiz DB — identifies new ones
4. Shows new transactions grouped by card with checkboxes for selection
5. On "Sincronizar": creates backup of MoneyWiz SQLite, then creates each selected transaction in MoneyWiz via URL Schemas with real-time SSE progress

## Confirmed Technical Decisions
- Santander D (debit) → `moneywiz://expense?`, C (credit) → `moneywiz://income?`
- Account names exact: "Cartão 123" (Santander), "Cartão Millennium" (Millennium)
- SSE (Server-Sent Events) for real-time sync progress
- Port 5050 (avoids macOS AirPlay on 5000)
- 3s delay between URL Schema calls + DB verification + 1 retry if unverified
- `save=true` in all URL Schemas (direct save, no MoneyWiz UI)
- Payee: "Automacao", Currency: EUR
- URL Schema date: `yyyy-MM-dd 12:00:00` (noon default)
- Shared utilities extracted to `moneywiz_utils.py` (reused from server.py)

## Phase → Sub-Task Mapping

| Phase | Sub-Task | Files |
|-------|----------|-------|
| Step 0 | Extract shared utils | `moneywiz_utils.py` (new), `server.py` (update imports) |
| Phase A-1 | UNI-137 | `parsers/millennium.py` |
| Phase A-2 | UNI-138 | `parsers/santander.py` |
| Phase B | UNI-139 | `sync/comparator.py`, `sync/backup.py` |
| Phase C | UNI-140 | `sync/writer.py` |
| Phase D | UNI-141 | `app.py`, `templates/index.html`, `static/style.css` |

## Dependencies
- pdfplumber (already in requirements.txt)
- flask (already in requirements.txt)
- moneywiz-api v1.0.6 (already in requirements.txt)
- subprocess + webbrowser + threading (stdlib)

## Constraints
- MoneyWiz must be open for URL Schema writes
- PDF format must match known Millennium/Santander formats (raise ValueError otherwise)
- All processing is 100% local, no network calls

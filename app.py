"""
MoneyWiz Sync App — Flask web application.

Routes:
  GET  /        → Single-page UI
  POST /upload  → Parse PDFs, compare with MoneyWiz, return JSON
  POST /sync    → Backup + stream SSE progress from writer

Run:
  python3 app.py
  (auto-opens http://localhost:5050 in browser)
"""

import json
import os
import threading
import uuid
import webbrowser
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, stream_with_context

from parsers import millennium, santander
from sync import backup, comparator
from sync.writer import sync_transactions

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 MB max upload

UPLOAD_DIR = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

# In-memory session storage (single-user, no persistence needed)
_sessions: dict[str, list[dict]] = {}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
def upload():
    """
    Accept 1-2 PDF files, auto-detect bank, parse, compare with MoneyWiz.

    Returns JSON:
    {
      "session_id": "...",
      "accounts": [
        {
          "account": "Cartão Millennium",
          "new": 5,
          "total_pdf": 12,
          "existing": 7,
          "transactions": [{id, date, description, amount, type}, ...]
        },
        ...
      ],
      "all_synced": false
    }
    """
    files = request.files.getlist("pdfs")
    if not files or all(f.filename == "" for f in files):
        return jsonify({"error": "Nenhum ficheiro enviado."}), 400

    all_new: list[dict] = []
    errors: list[str] = []

    for f in files:
        if not f.filename:
            continue
        # Save temporarily
        safe_name = f"{uuid.uuid4().hex}_{Path(f.filename).name}"
        tmp_path = UPLOAD_DIR / safe_name
        try:
            f.save(str(tmp_path))
            txs = _parse_pdf(str(tmp_path))
            if not txs:
                errors.append(f"{f.filename}: nenhuma transação encontrada.")
                continue

            # Compare against MoneyWiz (group by account)
            account_name = txs[0]["account"]
            result = comparator.compare(txs, account_name)
            all_new.extend(result["new_transactions"])
        except ValueError as e:
            errors.append(f"{f.filename}: {e}")
        except Exception as e:
            errors.append(f"{f.filename}: Erro inesperado — {e}")
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass

    if errors and not all_new:
        return jsonify({"error": " | ".join(errors)}), 422

    # Group new transactions by account and assign stable IDs
    session_id = uuid.uuid4().hex
    accounts_map: dict[str, dict] = {}
    indexed: list[dict] = []

    for i, tx in enumerate(all_new):
        acct = tx["account"]
        if acct not in accounts_map:
            accounts_map[acct] = {
                "account": acct,
                "transactions": [],
            }
        tx_out = {
            "id": i,
            "date": tx["date"].isoformat(),
            "description": tx["description"],
            "amount": str(tx["amount"]),
            "type": tx["type"],
            "account": acct,
        }
        accounts_map[acct]["transactions"].append(tx_out)
        indexed.append(tx)  # keep original for writer (has Decimal/date objects)

    # Store originals in session for /sync
    _sessions[session_id] = indexed

    accounts_out = list(accounts_map.values())
    # Sort each account's transactions by date
    for a in accounts_out:
        a["transactions"].sort(key=lambda t: t["date"])

    response = {
        "session_id": session_id,
        "accounts": accounts_out,
        "all_synced": len(all_new) == 0,
    }
    if errors:
        response["warnings"] = errors

    return jsonify(response)


@app.route("/sync", methods=["POST"])
def sync():
    """
    Accept selected transaction IDs, create backup, stream SSE progress.

    Body JSON: {"session_id": "...", "ids": [0, 2, 5, ...]}

    Streams text/event-stream with data: {...} lines.
    """
    body = request.get_json(force=True, silent=True) or {}
    session_id = body.get("session_id")
    selected_ids = body.get("ids", [])

    if not session_id or session_id not in _sessions:
        return jsonify({"error": "Sessão inválida ou expirada. Faça upload novamente."}), 400

    all_txs = _sessions[session_id]
    selected = [all_txs[i] for i in selected_ids if 0 <= i < len(all_txs)]

    if not selected:
        return jsonify({"error": "Nenhuma transação selecionada."}), 400

    # Create backup before any writes
    try:
        backup_dir = backup.create_backup()
        backup_msg = f"Backup criado em {backup_dir.name}"
    except Exception as e:
        return jsonify({"error": f"Falha ao criar backup: {e}. Sync cancelado."}), 500

    def generate():
        # First event: backup confirmation
        yield f"data: {json.dumps({'backup': backup_msg})}\n\n"

        for event in sync_transactions(selected):
            yield f"data: {json.dumps(event, default=str)}\n\n"

        # Clean up session after sync
        _sessions.pop(session_id, None)

    return Response(
        stream_with_context(generate()),
        content_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_pdf(path: str) -> list[dict]:
    """Auto-detect format and parse. CSV → Millennium export. PDF → try Millennium then Santander."""
    if path.lower().endswith(".csv"):
        return millennium.parse_csv(path)

    try:
        return millennium.parse(path)
    except ValueError:
        pass
    return santander.parse(path)  # raises ValueError if not Santander either


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    url = f"http://localhost:{port}"

    # Open browser after a short delay to let Flask start
    threading.Timer(1.5, webbrowser.open, [url]).start()
    print(f"MoneyWiz Sync App → {url}")

    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)

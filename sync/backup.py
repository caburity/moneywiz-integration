"""
Backup: creates a timestamped copy of the MoneyWiz SQLite database
before any sync operation.

Copies .sqlite + -wal + -shm (if they exist) to:
  moneywiz-backups/YYYYMMDD_HHmmss/
"""

import shutil
from datetime import datetime
from pathlib import Path

from moneywiz_utils import find_db_path

# Backups directory relative to project root (already in .gitignore)
_BACKUP_BASE = Path(__file__).parent.parent / "moneywiz-backups"


def create_backup() -> Path:
    """
    Copy MoneyWiz SQLite files to a timestamped backup directory.

    Returns the backup directory Path.
    Raises RuntimeError if the DB is not found or the copy fails.
    """
    db_path = find_db_path()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = _BACKUP_BASE / timestamp
    backup_dir.mkdir(parents=True, exist_ok=True)

    # Always copy the main .sqlite file
    _copy_file(db_path, backup_dir / db_path.name)

    # Copy WAL and SHM files if present (they may not exist)
    for suffix in ("-wal", "-shm"):
        companion = db_path.with_name(db_path.name + suffix)
        if companion.exists():
            _copy_file(companion, backup_dir / companion.name)

    return backup_dir


def _copy_file(src: Path, dst: Path) -> None:
    try:
        shutil.copy2(src, dst)
    except Exception as e:
        raise RuntimeError(
            f"Falha ao copiar {src.name} para backup: {e}"
        ) from e

import os
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path

from flask import jsonify

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB = "/tmp/library_split.db"

os.environ.setdefault("LIBRARY_DB_PATH", DEFAULT_DB)
DB_PATH = Path(os.environ["LIBRARY_DB_PATH"])


def build_db():
    print(f"[cloudtype] db missing, building to {DB_PATH}")
    build_env = os.environ.copy()
    build_env["LIBRARY_DB_PATH"] = str(DB_PATH)
    try:
        subprocess.run(
            [sys.executable, str(ROOT_DIR / "scripts" / "build_sqlite.py")],
            cwd=str(ROOT_DIR),
            check=True,
            env=build_env,
        )
        print("[cloudtype] db build complete")
    except Exception as exc:
        print(f"[cloudtype] db build failed: {exc}")


def db_ready():
    if not DB_PATH.exists() or DB_PATH.stat().st_size == 0:
        return False
    try:
        conn = sqlite3.connect(str(DB_PATH))
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='books';"
            ).fetchone()
            return bool(row)
        finally:
            conn.close()
    except Exception:
        return False


if not db_ready():
    threading.Thread(target=build_db, daemon=True).start()

from app_search import app as flask_app


@flask_app.before_request
def gate_until_ready():
    if db_ready():
        return None
    if getattr(gate_until_ready, "_warned", False) is False:
        gate_until_ready._warned = True
        print("[cloudtype] db not ready yet; serving 503")
    return jsonify({"error": "db is building"}), 503


if __name__ == "__main__":
    port = int(os.environ.get("LIBRARY_SEARCH_PORT", "5000"))
    flask_app.run(host="0.0.0.0", port=port)

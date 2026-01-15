import os
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB = "/tmp/library_split.db"

os.environ.setdefault("LIBRARY_DB_PATH", DEFAULT_DB)
DB_PATH = Path(os.environ["LIBRARY_DB_PATH"])

if not DB_PATH.exists():
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
    except Exception as exc:
        print(f"[cloudtype] db build failed: {exc}")

from app_search import app as flask_app

if __name__ == "__main__":
    port = int(os.environ.get("LIBRARY_SEARCH_PORT", "5000"))
    flask_app.run(host="0.0.0.0", port=port)

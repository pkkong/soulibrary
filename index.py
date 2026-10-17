"""Vercel WSGI entrypoint for the existing Flask app."""

from pathlib import Path
import os
import sys


PROJECT_ROOT = Path(__file__).resolve().parent
WEB_ROOT = PROJECT_ROOT / "web"


def _prepend_sys_path(path):
    path = str(path)
    if path in sys.path:
        sys.path.remove(path)
    sys.path.insert(0, path)


_prepend_sys_path(PROJECT_ROOT)
_prepend_sys_path(WEB_ROOT)
os.chdir(PROJECT_ROOT)

if os.environ.get("LIBRARY_RELAY_MODE") == "1":
    from library_relay_app import app  # noqa: E402,F401
else:
    from app_search import app  # noqa: E402,F401

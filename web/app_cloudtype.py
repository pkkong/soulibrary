import os

from db import using_postgres

if not using_postgres():
    raise SystemExit("[cloudtype] PostgreSQL env vars are required.")

from app_search import app as flask_app


if __name__ == "__main__":
    port = int(os.environ.get("LIBRARY_SEARCH_PORT", "5000"))
    flask_app.run(host="0.0.0.0", port=port)

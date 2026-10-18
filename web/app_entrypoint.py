"""Select the Flask app at runtime while keeping index.py's export explicit."""

import os

if os.environ.get("LIBRARY_RELAY_MODE") == "1":
    from library_relay_app import app
else:
    from app_search import app

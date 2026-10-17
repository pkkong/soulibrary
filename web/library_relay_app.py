"""Isolated library-page relay. It imports no main-app, DB or analytics routes."""

import os
from threading import BoundedSemaphore

from flask import Flask, jsonify, request

from live_search.relay import (
    MAX_REQUEST_BYTES, RELAY_PATH, SIGNATURE_HEADER, TIMESTAMP_HEADER,
    RelayError, authenticated, fetch_upstream, load_payload,
)

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES
_capacity = BoundedSemaphore(16)


def _failure(code, status):
    return jsonify({"version": 1, "ok": False, "error": code,
                    "region": os.environ.get("VERCEL_REGION", "unknown")}), status


@app.get("/health")
def health():
    return jsonify({"ok": True, "mode": "library-relay",
                    "region": os.environ.get("VERCEL_REGION", "unknown")})


@app.errorhandler(413)
def too_large(_error):
    return _failure("body_too_large", 413)


@app.post(RELAY_PATH)
def library_page():
    if request.query_string or request.mimetype != "application/json":
        return _failure("invalid_request", 400)
    body = request.get_data(cache=False)
    if not authenticated(request.headers.get(TIMESTAMP_HEADER), request.headers.get(SIGNATURE_HEADER), body):
        return _failure("authentication", 401)
    try:
        payload = load_payload(body)
    except RelayError:
        return _failure("invalid_request", 400)
    if not _capacity.acquire(blocking=False):
        return _failure("busy", 503)
    try:
        return jsonify(fetch_upstream(payload))
    except RelayError as error:
        return _failure(error.code, 504 if error.code == "budget_exhausted" else 502)
    except Exception:
        return _failure("transport_error", 502)
    finally:
        _capacity.release()

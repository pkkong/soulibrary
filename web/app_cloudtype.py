import os

from flask import send_from_directory
from db import using_postgres

if not using_postgres():
    raise SystemExit("[cloudtype] PostgreSQL env vars are required.")

from app_search import app as flask_app

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


def _add_static_route(rule, filename, endpoint):
    if endpoint in flask_app.view_functions:
        return
    if any(r.rule == rule for r in flask_app.url_map.iter_rules()):
        return

    def _handler():
        return send_from_directory(STATIC_DIR, filename)

    flask_app.add_url_rule(rule, endpoint, _handler)


_add_static_route("/robots.txt", "robots.txt", "robots_txt_cloudtype")
_add_static_route("/sitemap.xml", "sitemap.xml", "sitemap_xml_cloudtype")
_add_static_route(
    "/naver502d24e941f50b3d3341745ef4de5f43.html",
    "naver502d24e941f50b3d3341745ef4de5f43.html",
    "naver_verify_cloudtype",
)
_add_static_route(
    "/naver520d24e941f50b3d3341745ef4de5f43.html",
    "naver520d24e941f50b3d3341745ef4de5f43.html",
    "naver_verify_cloudtype_alt",
)


if __name__ == "__main__":
    port = int(os.environ.get("LIBRARY_SEARCH_PORT", "5000"))
    flask_app.run(host="0.0.0.0", port=port)

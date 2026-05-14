import json
import os
from datetime import datetime, timezone

from flask import Blueprint, redirect, render_template, request, url_for

from db import get_db


report_bp = Blueprint("reports", __name__)

MAX_MESSAGE_LEN = 1200
MAX_CONTACT_LEN = 120
MAX_PAGE_URL_LEN = 500
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FALLBACK_REPORTS_FILE = os.environ.get(
    "ERROR_REPORTS_FILE",
    os.path.join(ROOT_DIR, "data", "error_reports.jsonl"),
)


def _clean(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _ensure_table(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS error_reports (
            id SERIAL PRIMARY KEY,
            category TEXT NOT NULL DEFAULT '오류',
            message TEXT NOT NULL,
            contact TEXT,
            page_url TEXT,
            user_agent TEXT,
            status TEXT NOT NULL DEFAULT 'new',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    # Older deployments may already have the table with fewer columns.
    for sql in (
        "ALTER TABLE error_reports ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT '오류'",
        "ALTER TABLE error_reports ADD COLUMN IF NOT EXISTS message TEXT",
        "ALTER TABLE error_reports ADD COLUMN IF NOT EXISTS contact TEXT",
        "ALTER TABLE error_reports ADD COLUMN IF NOT EXISTS page_url TEXT",
        "ALTER TABLE error_reports ADD COLUMN IF NOT EXISTS user_agent TEXT",
        "ALTER TABLE error_reports ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'new'",
        "ALTER TABLE error_reports ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
    ):
        conn.execute(sql)
    conn.commit()


def _recent_reports(conn):
    cur = conn.execute(
        """
        SELECT id, category, message, page_url, created_at
        FROM error_reports
        ORDER BY created_at DESC, id DESC
        LIMIT 10
        """
    )
    return cur.fetchall()


def _file_report_row(payload: dict, report_id: int | None = None) -> dict:
    created_at = payload.get("created_at")
    if isinstance(created_at, str):
        try:
            created_at = datetime.fromisoformat(created_at)
        except ValueError:
            created_at = None
    return {
        "id": report_id or payload.get("id") or 0,
        "category": payload.get("category") or "오류",
        "message": payload.get("message") or "",
        "page_url": payload.get("page_url") or "",
        "created_at": created_at,
    }


def _recent_file_reports():
    if not os.path.exists(FALLBACK_REPORTS_FILE):
        return []
    rows = []
    with open(FALLBACK_REPORTS_FILE, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(_file_report_row(json.loads(line), idx))
            except json.JSONDecodeError:
                continue
    return list(reversed(rows))[:10]


def _safe_recent_file_reports():
    try:
        return _recent_file_reports()
    except Exception as exc:
        print(f"[report warning] file report read failed: {exc}")
        return []


def _append_file_report(payload: dict):
    os.makedirs(os.path.dirname(FALLBACK_REPORTS_FILE), exist_ok=True)
    with open(FALLBACK_REPORTS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _open_report_db():
    if os.environ.get("ERROR_REPORTS_STORAGE") == "file":
        return None
    try:
        conn = get_db()
        _ensure_table(conn)
        return conn
    except Exception as exc:
        print(f"[report warning] database unavailable: {exc}")
        return None


def _build_report_payload(form: dict, user_agent: str) -> dict:
    return {
        **form,
        "user_agent": user_agent,
        "status": "new",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _save_report(conn, form: dict, user_agent: str):
    if conn:
        try:
            conn.execute(
                """
                INSERT INTO error_reports (category, message, contact, page_url, user_agent)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    form["category"],
                    form["message"],
                    form["contact"],
                    form["page_url"],
                    user_agent,
                ),
            )
            conn.commit()
            return
        except Exception as exc:
            print(f"[report warning] database save failed, falling back to file: {exc}")
            try:
                conn.rollback()
            except Exception:
                pass

    _append_file_report(_build_report_payload(form, user_agent))


@report_bp.route("/reports", methods=["GET", "POST"])
def reports_page():
    error = ""
    saved = request.args.get("saved") == "1"
    form = {
        "category": "오류",
        "message": "",
        "contact": "",
        "page_url": request.args.get("url") or request.referrer or "",
    }

    conn = _open_report_db()

    try:
        if request.method == "POST":
            form = {
                "category": _clean(request.form.get("category") or "오류", 20),
                "message": _clean(request.form.get("message"), MAX_MESSAGE_LEN),
                "contact": _clean(request.form.get("contact"), MAX_CONTACT_LEN),
                "page_url": _clean(request.form.get("page_url"), MAX_PAGE_URL_LEN),
            }
            trap = (request.form.get("website") or "").strip()
            if trap:
                return redirect(url_for("reports.reports_page", saved=1))
            if len(form["message"]) < 5:
                error = "어떤 문제가 있었는지 조금만 더 적어주세요."
            else:
                user_agent = _clean(request.headers.get("User-Agent"), 500)
                _save_report(conn, form, user_agent)
                return redirect(url_for("reports.reports_page", saved=1))

        try:
            reports = _recent_reports(conn) if conn else _safe_recent_file_reports()
        except Exception as exc:
            print(f"[report warning] database read failed, falling back to file: {exc}")
            reports = _safe_recent_file_reports()
        return render_template(
            "reports.html",
            reports=reports,
            form=form,
            error=error,
            saved=saved,
            show_topbar=False,
            topbar_desc="",
            active_tab="reports",
        )
    except Exception as exc:
        print(f"[report error] save failed: {exc}")
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        return render_template(
            "reports.html",
            reports=[],
            form=form,
            error="신고를 저장하지 못했습니다. 잠시 후 다시 시도해주세요.",
            saved=False,
            show_topbar=False,
            topbar_desc="",
            active_tab="reports",
        ), 500
    finally:
        if conn:
            conn.close()

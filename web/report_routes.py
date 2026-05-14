import json
import os
import tempfile
from datetime import datetime, timezone

import requests
from flask import Blueprint, redirect, render_template, request, url_for

from db import get_db


report_bp = Blueprint("reports", __name__)

MAX_MESSAGE_LEN = 1200
MAX_CONTACT_LEN = 120
MAX_PAGE_URL_LEN = 500
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_REPORTS_FILE = os.path.join(tempfile.gettempdir(), "soulib", "error_reports.jsonl")
LEGACY_REPORTS_FILE = os.path.join(ROOT_DIR, "data", "error_reports.jsonl")
DEFAULT_GITHUB_REPO = "pkkong/library_crawler"


def _clean(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _report_file_candidates():
    paths = [
        os.environ.get("ERROR_REPORTS_FILE"),
        DEFAULT_REPORTS_FILE,
        LEGACY_REPORTS_FILE,
    ]
    result = []
    seen = set()
    for path in paths:
        if not path or path in seen:
            continue
        seen.add(path)
        result.append(path)
    return result


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
            issue_number INTEGER,
            issue_url TEXT,
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
        "ALTER TABLE error_reports ADD COLUMN IF NOT EXISTS issue_number INTEGER",
        "ALTER TABLE error_reports ADD COLUMN IF NOT EXISTS issue_url TEXT",
        "ALTER TABLE error_reports ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'new'",
        "ALTER TABLE error_reports ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
    ):
        conn.execute(sql)
    conn.commit()


def _status_label(status: str | None) -> str:
    labels = {
        "issue_created": "이슈 등록",
        "new": "접수됨",
    }
    return labels.get(status or "new", "접수됨")


def _decorate_report(row: dict) -> dict:
    data = dict(row)
    data["status_label"] = _status_label(data.get("status"))
    return data


def _recent_reports(conn):
    cur = conn.execute(
        """
        SELECT id, category, message, page_url, issue_number, issue_url, status, created_at
        FROM error_reports
        ORDER BY created_at DESC, id DESC
        LIMIT 10
        """
    )
    return [_decorate_report(row) for row in cur.fetchall()]


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
        "issue_number": payload.get("issue_number"),
        "issue_url": payload.get("issue_url") or "",
        "status": payload.get("status") or "new",
        "status_label": _status_label(payload.get("status")),
        "created_at": created_at,
    }


def _recent_file_reports():
    rows = []
    for path in _report_file_candidates():
        if not os.path.exists(path) or os.path.isdir(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                for idx, line in enumerate(f, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(_file_report_row(json.loads(line), idx))
                    except json.JSONDecodeError:
                        continue
        except Exception as exc:
            print(f"[report warning] file report read failed from {path}: {exc}")
    return list(reversed(rows))[:10]


def _safe_recent_file_reports():
    try:
        return _recent_file_reports()
    except Exception as exc:
        print(f"[report warning] file report read failed: {exc}")
        return []


def _append_file_report(payload: dict):
    last_error = None
    for path in _report_file_candidates():
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
            return
        except Exception as exc:
            last_error = exc
            print(f"[report warning] file report write failed to {path}: {exc}")
    raise RuntimeError(f"all report file fallbacks failed: {last_error}")


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


def _github_issue_labels() -> list[str]:
    raw = os.environ.get("GITHUB_ISSUE_LABELS", "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def _create_github_issue(form: dict, user_agent: str) -> dict:
    token = os.environ.get("GITHUB_ISSUE_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        return {}

    repo = os.environ.get("GITHUB_ISSUE_REPO", DEFAULT_GITHUB_REPO).strip() or DEFAULT_GITHUB_REPO
    timeout = float(os.environ.get("GITHUB_ISSUE_TIMEOUT", "8"))
    title = f"[오류신고] {form['category']} - {_clean(form['message'], 70)}"
    body = "\n".join(
        [
            "Soulib `/reports`에서 자동 생성된 오류 신고입니다.",
            "",
            "## 신고 내용",
            form["message"] or "(내용 없음)",
            "",
            "## 문제가 있던 주소",
            form["page_url"] or "(입력 없음)",
            "",
            "## 연락처",
            form["contact"] or "(입력 없음)",
            "",
            "## User-Agent",
            f"`{user_agent or '(unknown)'}`",
            "",
            "## 처리 체크리스트",
            "- [ ] 재현 확인",
            "- [ ] 원인 확인",
            "- [ ] 수정 PR 생성",
            "- [ ] 배포 후 확인",
        ]
    )
    payload = {"title": title, "body": body}
    labels = _github_issue_labels()
    if labels:
        payload["labels"] = labels

    url = f"https://api.github.com/repos/{repo}/issues"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=timeout)
        if labels and response.status_code == 422:
            payload.pop("labels", None)
            response = requests.post(url, headers=headers, json=payload, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        return {
            "issue_number": data.get("number"),
            "issue_url": data.get("html_url") or "",
        }
    except Exception as exc:
        print(f"[report warning] github issue creation failed: {exc}")
        return {}


def _build_report_payload(form: dict, user_agent: str, issue_info: dict | None = None) -> dict:
    issue_info = issue_info or {}
    return {
        **form,
        "user_agent": user_agent,
        "issue_number": issue_info.get("issue_number"),
        "issue_url": issue_info.get("issue_url") or "",
        "status": "issue_created" if issue_info.get("issue_url") else "new",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _save_report(conn, form: dict, user_agent: str, issue_info: dict | None = None):
    issue_info = issue_info or {}
    if conn:
        try:
            conn.execute(
                """
                INSERT INTO error_reports (
                    category, message, contact, page_url, user_agent,
                    issue_number, issue_url, status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    form["category"],
                    form["message"],
                    form["contact"],
                    form["page_url"],
                    user_agent,
                    issue_info.get("issue_number"),
                    issue_info.get("issue_url") or "",
                    "issue_created" if issue_info.get("issue_url") else "new",
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

    _append_file_report(_build_report_payload(form, user_agent, issue_info))


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
                issue_info = _create_github_issue(form, user_agent)
                _save_report(conn, form, user_agent, issue_info)
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

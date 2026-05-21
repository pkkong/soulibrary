import os
from datetime import datetime, timedelta, timezone

import requests
from flask import Blueprint, jsonify, redirect, render_template, request, url_for


report_bp = Blueprint("reports", __name__)

MAX_MESSAGE_LEN = 1200
MAX_CONTACT_LEN = 120
MAX_PAGE_URL_LEN = 500
DEFAULT_GITHUB_REPO = "pkkong/library_crawler"
REPORT_TITLE_PREFIX = "[오류신고]"
REPORT_STORE_ERROR = "최근 접수 목록을 잠시 불러오지 못했습니다."
REPORT_SAVE_ERROR = "신고를 접수하지 못했습니다. 잠시 후 다시 시도해주세요."
KST = timezone(timedelta(hours=9), "Asia/Seoul")


def _clean(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _to_kst(value):
    if not value:
        return None
    if isinstance(value, str):
        value = value.replace("Z", "+00:00")
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(KST)


def _github_repo() -> str:
    return os.environ.get("GITHUB_ISSUE_REPO", DEFAULT_GITHUB_REPO).strip() or DEFAULT_GITHUB_REPO


def _github_timeout() -> float:
    return float(os.environ.get("GITHUB_ISSUE_TIMEOUT", "8"))


def _github_headers(require_token: bool = True) -> dict:
    token = os.environ.get("GITHUB_ISSUE_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if require_token and not token:
        raise RuntimeError("GITHUB_ISSUE_TOKEN is required for report storage.")

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _github_error_detail(exc: Exception) -> str:
    if str(exc) == "GITHUB_ISSUE_TOKEN is required for report storage.":
        return "운영 서버에 GITHUB_ISSUE_TOKEN 환경변수가 없습니다."

    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code == 401:
        return "GitHub가 토큰을 거부했습니다. 토큰 값이 잘못됐거나 폐기된 상태입니다."
    if status_code == 403:
        return "GitHub 토큰 권한이 부족합니다. Issues 권한과 저장소 접근 범위를 확인해야 합니다."
    if status_code == 404:
        return "GitHub 저장소를 찾지 못했습니다. GITHUB_ISSUE_REPO 또는 토큰의 저장소 접근 범위가 맞지 않습니다."
    if status_code:
        return f"GitHub API가 HTTP {status_code} 응답을 반환했습니다."
    return "GitHub API 호출 중 알 수 없는 오류가 발생했습니다."


def _report_store_error(exc: Exception) -> str:
    return REPORT_STORE_ERROR


def _default_report_form(page_url: str = "") -> dict:
    return {
        "category": "오류",
        "message": "",
        "contact": "",
        "page_url": page_url,
    }


def _prepend_recent_report(reports: list[dict], report: dict | None) -> list[dict]:
    if not report:
        return reports

    pinned_report = dict(report)
    pinned_report["is_new"] = True
    pinned_key = pinned_report.get("issue_number") or pinned_report.get("id")
    if not pinned_key:
        return [pinned_report, *reports]

    deduped = [
        item
        for item in reports
        if (item.get("issue_number") or item.get("id")) != pinned_key
    ]
    return [pinned_report, *deduped]


def _github_issue_labels() -> list[str]:
    raw = os.environ.get("GITHUB_ISSUE_LABELS", "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def _status_label(state: str | None) -> str:
    if state == "closed":
        return "처리 완료"
    return "접수됨"


def _customer_resolution_message(message: str) -> str:
    summary = _clean(message, 80)
    if summary:
        return f"신고해주신 '{summary}' 문제를 확인했고, 필요한 조치를 완료했습니다. 알려주셔서 감사합니다."
    return "신고해주신 문제를 확인했고, 필요한 조치를 완료했습니다. 알려주셔서 감사합니다."


def _extract_section(body: str, heading: str) -> str:
    lines = str(body or "").splitlines()
    target = f"## {heading}".strip()
    for idx, line in enumerate(lines):
        if line.strip() != target:
            continue
        values = []
        for next_line in lines[idx + 1:]:
            if next_line.startswith("## "):
                break
            if next_line.strip():
                values.append(next_line.strip())
        return "\n".join(values).strip()
    return ""


def _category_from_title(title: str) -> str:
    title = str(title or "")
    if not title.startswith(REPORT_TITLE_PREFIX):
        return "오류"
    rest = title[len(REPORT_TITLE_PREFIX):].strip()
    if " - " in rest:
        return rest.split(" - ", 1)[0].strip() or "오류"
    return "오류"


def _latest_resolution_time(issue: dict):
    if issue.get("state") != "closed" or not issue.get("comments"):
        return None
    comments_url = issue.get("comments_url")
    if not comments_url:
        issue_number = issue.get("number")
        if not issue_number:
            return None
        comments_url = f"https://api.github.com/repos/{_github_repo()}/issues/{issue_number}/comments"

    response = requests.get(
        comments_url,
        headers=_github_headers(require_token=True),
        params={"per_page": "100"},
        timeout=_github_timeout(),
    )
    response.raise_for_status()
    comments = response.json()
    if not isinstance(comments, list):
        return None

    for comment in reversed(comments):
        if str(comment.get("body") or "").strip():
            return _to_kst(comment.get("created_at"))
    return None


def _issue_to_report(issue: dict, resolution_at=None) -> dict:
    issue_number = issue.get("number")
    body = issue.get("body") or ""
    message = _extract_section(body, "신고 내용") or issue.get("title") or ""
    closed_at = _to_kst(issue.get("closed_at"))
    resolution_message = ""
    if issue.get("state") == "closed":
        resolution_message = _customer_resolution_message(message)
        resolution_at = resolution_at or closed_at

    return {
        "id": issue_number or 0,
        "category": _category_from_title(issue.get("title") or ""),
        "message": message,
        "page_url": _extract_section(body, "문제가 있던 주소"),
        "issue_number": issue_number,
        "issue_url": issue.get("html_url") or "",
        "status": issue.get("state") or "open",
        "status_label": _status_label(issue.get("state")),
        "created_at": _to_kst(issue.get("created_at")),
        "closed_at": closed_at,
        "updated_at": _to_kst(issue.get("updated_at")),
        "resolution_message": resolution_message,
        "resolution_at": resolution_at,
    }


def _recent_github_reports(limit: int = 10) -> list[dict]:
    url = f"https://api.github.com/repos/{_github_repo()}/issues"
    params = {
        "state": "all",
        "sort": "created",
        "direction": "desc",
        "per_page": "100",
    }
    response = requests.get(
        url,
        headers=_github_headers(require_token=True),
        params=params,
        timeout=_github_timeout(),
    )
    response.raise_for_status()
    issues = response.json()
    if not isinstance(issues, list):
        raise RuntimeError("GitHub issue list response was not a list.")

    reports = []
    for issue in issues if isinstance(issues, list) else []:
        if issue.get("pull_request"):
            continue
        if not str(issue.get("title") or "").startswith(REPORT_TITLE_PREFIX):
            continue
        resolution_at = None
        try:
            resolution_at = _latest_resolution_time(issue)
        except Exception as exc:
            print(f"[report warning] github issue comment fetch failed: {exc}")
        reports.append(_issue_to_report(issue, resolution_at))
        if len(reports) >= limit:
            break
    return reports


def _render_reports_page(
    form: dict,
    error: str = "",
    saved: bool = False,
    status_code: int = 200,
    saved_report: dict | None = None,
    load_reports: bool = False,
):
    reports = []
    reports_unavailable = False
    reports_notice = ""
    reports_loading = not load_reports and not saved_report
    if load_reports:
        try:
            reports = _recent_github_reports()
        except Exception as exc:
            detail = _github_error_detail(exc)
            print(f"[report error] github issue list failed: {detail} raw={exc}")
            reports_unavailable = True
            if saved_report:
                reports_notice = "최근 접수 목록 동기화가 지연되어 방금 접수한 신고를 먼저 보여드립니다."
            else:
                error = error or _report_store_error(exc)

    reports = _prepend_recent_report(reports, saved_report)
    saved_report = reports[0] if saved_report and reports else None
    reports_count_label = "확인 중" if reports_loading else ("일시 지연" if reports_unavailable else f"{len(reports)}건")

    return render_template(
        "reports.html",
        reports=reports,
        reports_unavailable=reports_unavailable,
        reports_notice=reports_notice,
        reports_loading=reports_loading,
        reports_count_label=reports_count_label,
        saved_report=saved_report,
        form=form,
        error=error,
        saved=saved,
        show_topbar=False,
        topbar_desc="",
        active_tab="reports",
    ), status_code


def _render_recent_reports_fragment(reports, reports_unavailable=False, reports_notice="", reports_loading=False):
    return render_template(
        "partials/report_recent_list.html",
        reports=reports,
        reports_unavailable=reports_unavailable,
        reports_notice=reports_notice,
        reports_loading=reports_loading,
    )


def _create_github_issue(form: dict, user_agent: str) -> dict:
    title = f"{REPORT_TITLE_PREFIX} {form['category']} - {_clean(form['message'], 70)}"
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

    url = f"https://api.github.com/repos/{_github_repo()}/issues"
    response = requests.post(
        url,
        headers=_github_headers(require_token=True),
        json=payload,
        timeout=_github_timeout(),
    )
    if labels and response.status_code == 422:
        payload.pop("labels", None)
        response = requests.post(
            url,
            headers=_github_headers(require_token=True),
            json=payload,
            timeout=_github_timeout(),
        )
    response.raise_for_status()
    return _issue_to_report(response.json())


@report_bp.route("/reports", methods=["GET", "POST"])
def reports_page():
    error = ""
    saved = request.args.get("saved") == "1"
    form = _default_report_form(request.args.get("url") or request.referrer or "")

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
            try:
                user_agent = _clean(request.headers.get("User-Agent"), 500)
                created_report = _create_github_issue(form, user_agent)
                return _render_reports_page(
                    _default_report_form(),
                    saved=True,
                    status_code=201,
                    saved_report=created_report,
                )
            except Exception as exc:
                detail = _github_error_detail(exc)
                print(f"[report error] github issue creation failed: {detail} raw={exc}")
                return _render_reports_page(
                    form,
                    REPORT_SAVE_ERROR,
                    saved=False,
                    status_code=500,
                )

    return _render_reports_page(form, error=error, saved=saved)


@report_bp.route("/api/reports/recent")
def api_recent_reports():
    reports = []
    reports_unavailable = False
    reports_notice = ""
    status_code = 200
    try:
        reports = _recent_github_reports()
    except Exception as exc:
        detail = _github_error_detail(exc)
        print(f"[report error] github issue list failed: {detail} raw={exc}")
        reports_unavailable = True
        reports_notice = _report_store_error(exc)
        status_code = 503

    html = _render_recent_reports_fragment(
        reports,
        reports_unavailable=reports_unavailable,
        reports_notice=reports_notice,
    )
    count_label = "일시 지연" if reports_unavailable else f"{len(reports)}건"
    return jsonify({
        "html": html,
        "count_label": count_label,
        "unavailable": reports_unavailable,
    }), status_code

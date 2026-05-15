import os
from datetime import datetime, timedelta, timezone

import requests
from flask import Blueprint, redirect, render_template, request, url_for


report_bp = Blueprint("reports", __name__)

MAX_MESSAGE_LEN = 1200
MAX_CONTACT_LEN = 120
MAX_PAGE_URL_LEN = 500
DEFAULT_GITHUB_REPO = "pkkong/library_crawler"
REPORT_TITLE_PREFIX = "[오류신고]"
REPORT_STORE_ERROR = "GitHub Issues 저장소 연결에 실패했습니다. GITHUB_ISSUE_TOKEN을 확인해주세요."
REPORT_SAVE_ERROR = "신고를 저장하지 못했습니다. GitHub Issues 연결 상태를 확인해주세요."
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


def _github_issue_labels() -> list[str]:
    raw = os.environ.get("GITHUB_ISSUE_LABELS", "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def _status_label(state: str | None) -> str:
    if state == "closed":
        return "처리 완료"
    return "접수됨"


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


def _issue_to_report(issue: dict) -> dict:
    issue_number = issue.get("number")
    body = issue.get("body") or ""
    return {
        "id": issue_number or 0,
        "category": _category_from_title(issue.get("title") or ""),
        "message": _extract_section(body, "신고 내용") or issue.get("title") or "",
        "page_url": _extract_section(body, "문제가 있던 주소"),
        "issue_number": issue_number,
        "issue_url": issue.get("html_url") or "",
        "status": issue.get("state") or "open",
        "status_label": _status_label(issue.get("state")),
        "created_at": _to_kst(issue.get("created_at")),
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
        reports.append(_issue_to_report(issue))
        if len(reports) >= limit:
            break
    return reports


def _render_reports_page(form: dict, error: str = "", saved: bool = False, status_code: int = 200):
    reports = []
    reports_unavailable = False
    try:
        reports = _recent_github_reports()
    except Exception as exc:
        print(f"[report error] github issue list failed: {exc}")
        reports_unavailable = True
        error = error or REPORT_STORE_ERROR

    return render_template(
        "reports.html",
        reports=reports,
        reports_unavailable=reports_unavailable,
        form=form,
        error=error,
        saved=saved,
        show_topbar=False,
        topbar_desc="",
        active_tab="reports",
    ), status_code


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
    form = {
        "category": "오류",
        "message": "",
        "contact": "",
        "page_url": request.args.get("url") or request.referrer or "",
    }

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
                _create_github_issue(form, user_agent)
                return redirect(url_for("reports.reports_page", saved=1))
            except Exception as exc:
                print(f"[report error] github issue creation failed: {exc}")
                return _render_reports_page(form, REPORT_SAVE_ERROR, saved=False, status_code=500)

    return _render_reports_page(form, error=error, saved=saved)

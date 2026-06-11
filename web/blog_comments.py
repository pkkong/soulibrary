import os
import re
from datetime import datetime, timedelta, timezone

import requests


COMMENT_TITLE_PREFIX = "[블로그댓글]"
DEFAULT_GITHUB_REPO = "pkkong/soulibrary"
KST = timezone(timedelta(hours=9), "Asia/Seoul")
MAX_COMMENT_LEN = 700
MAX_AUTHOR_LEN = 40


def _clean(value, limit):
    return " ".join(str(value or "").split())[:limit]


def _github_repo():
    return os.environ.get("GITHUB_ISSUE_REPO", DEFAULT_GITHUB_REPO).strip() or DEFAULT_GITHUB_REPO


def _github_timeout():
    return float(os.environ.get("GITHUB_ISSUE_TIMEOUT", "8"))


def _github_headers(require_token=True):
    token = os.environ.get("GITHUB_ISSUE_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if require_token and not token:
        raise RuntimeError("GITHUB_ISSUE_TOKEN is required for blog comments.")
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _to_kst(value):
    if not value:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(KST)


def _extract_section(body, heading):
    lines = str(body or "").splitlines()
    target = f"## {heading}".strip()
    for idx, line in enumerate(lines):
        if line.strip() != target:
            continue
        values = []
        for next_line in lines[idx + 1 :]:
            if next_line.startswith("## "):
                break
            if next_line.strip():
                values.append(next_line.strip())
        return "\n".join(values).strip()
    return ""


def _safe_slug(slug):
    return re.sub(r"[^0-9A-Za-z_-]", "", slug or "")


def _issue_to_comment(issue):
    body = issue.get("body") or ""
    return {
        "id": issue.get("number") or 0,
        "author": _extract_section(body, "이름") or "익명",
        "message": _extract_section(body, "댓글 내용"),
        "created_at": _to_kst(issue.get("created_at")),
        "issue_url": issue.get("html_url") or "",
    }


def get_blog_comments(slug, limit=20):
    slug = _safe_slug(slug)
    if not slug:
        return []

    url = f"https://api.github.com/repos/{_github_repo()}/issues"
    response = requests.get(
        url,
        headers=_github_headers(require_token=True),
        params={
            "state": "open",
            "sort": "created",
            "direction": "desc",
            "per_page": "100",
        },
        timeout=_github_timeout(),
    )
    response.raise_for_status()
    issues = response.json()
    if not isinstance(issues, list):
        return []

    comments = []
    expected = f"{COMMENT_TITLE_PREFIX} {slug} - "
    for issue in issues:
        if issue.get("pull_request"):
            continue
        if not str(issue.get("title") or "").startswith(expected):
            continue
        comment = _issue_to_comment(issue)
        if comment["message"]:
            comments.append(comment)
        if len(comments) >= limit:
            break
    return comments


def create_blog_comment(slug, post_title, author, message, user_agent=""):
    slug = _safe_slug(slug)
    author = _clean(author, MAX_AUTHOR_LEN) or "익명"
    message = _clean(message, MAX_COMMENT_LEN)
    if not slug:
        raise ValueError("invalid blog post")
    if len(message) < 2:
        raise ValueError("댓글을 조금만 더 적어주세요.")

    title = f"{COMMENT_TITLE_PREFIX} {slug} - {_clean(message, 55)}"
    body = "\n".join(
        [
            "Soulib 블로그에서 작성된 댓글입니다.",
            "",
            "## 글",
            post_title or slug,
            "",
            "## 이름",
            author,
            "",
            "## 댓글 내용",
            message,
            "",
            "## User-Agent",
            f"`{_clean(user_agent, 500) or '(unknown)'}`",
        ]
    )
    response = requests.post(
        f"https://api.github.com/repos/{_github_repo()}/issues",
        headers=_github_headers(require_token=True),
        json={"title": title, "body": body},
        timeout=_github_timeout(),
    )
    response.raise_for_status()
    return _issue_to_comment(response.json())

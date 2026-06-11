#!/usr/bin/env python3
"""Print a GitHub operations snapshot for the Soulib watcher.

The script intentionally avoids printing authentication material. It reads a
token from standard GitHub env vars, git credentials, or local gh auth.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_ROOT = "https://api.github.com"
DEFAULT_REPO = "pkkong/soulibrary"
DEFAULT_BRANCH = "main"
BLOG_COMMENT_PREFIX = "[블로그댓글]"


def fail(message: str, exit_code: int = 2) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(exit_code)


def token_from_gh_hosts() -> str:
    hosts_path = Path.home() / ".config" / "gh" / "hosts.yml"
    if not hosts_path.exists():
        return ""
    try:
        for line in hosts_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("oauth_token:"):
                return stripped.split(":", 1)[1].strip()
    except OSError:
        return ""
    return ""


def token_from_git_credentials() -> str:
    try:
        result = subprocess.run(
            ["git", "credential", "fill"],
            input="protocol=https\nhost=github.com\n\n",
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    for line in result.stdout.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1].strip()
    return ""


def load_token() -> str:
    return (
        os.getenv("GITHUB_TOKEN")
        or os.getenv("GH_TOKEN")
        or os.getenv("GITHUB_ISSUE_TOKEN")
        or token_from_git_credentials()
        or token_from_gh_hosts()
    )


def github_get(path: str, token: str, params: dict[str, str] | None = None) -> Any:
    url = f"{API_ROOT}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "soulib-ops-watcher",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        fail(f"GitHub API request failed: {exc.code} {exc.reason}. {detail}", 1)
    except URLError as exc:
        fail(f"GitHub API request failed: {exc.reason}", 1)


def is_blog_comment(issue: dict[str, Any]) -> bool:
    return str(issue.get("title") or "").startswith(BLOG_COMMENT_PREFIX)


def is_actionable_error(issue: dict[str, Any]) -> bool:
    title = str(issue.get("title") or "")
    labels = {str(label.get("name") or "") for label in issue.get("labels") or []}
    if is_blog_comment(issue):
        body = str(issue.get("body") or "")
        return any(term in body for term in ("오류", "버그", "안됨", "에러", "장애"))
    return "오류신고" in title or "bug" in labels or "오류신고" in labels


def issue_summary(issue: dict[str, Any]) -> dict[str, Any]:
    body = str(issue.get("body") or "")
    return {
        "number": issue.get("number"),
        "title": issue.get("title"),
        "state": issue.get("state"),
        "labels": [label.get("name") for label in issue.get("labels") or []],
        "created_at": issue.get("created_at"),
        "updated_at": issue.get("updated_at"),
        "html_url": issue.get("html_url"),
        "is_blog_comment": is_blog_comment(issue),
        "actionable_error": is_actionable_error(issue),
        "body_preview": body[:1200],
    }


def run_summary(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": run.get("name"),
        "status": run.get("status"),
        "conclusion": run.get("conclusion"),
        "head_branch": run.get("head_branch"),
        "head_sha": run.get("head_sha"),
        "created_at": run.get("created_at"),
        "updated_at": run.get("updated_at"),
        "html_url": run.get("html_url"),
    }


def build_snapshot(repo: str, branch: str, issue_limit: int, run_limit: int) -> dict[str, Any]:
    token = load_token()
    if not token:
        fail(
            "Missing GitHub token. Set GITHUB_TOKEN/GH_TOKEN/GITHUB_ISSUE_TOKEN "
            "or make sure git credentials/gh auth are available locally."
        )

    issues_raw = github_get(
        f"/repos/{repo}/issues",
        token,
        {"state": "open", "per_page": str(issue_limit)},
    )
    issues = [
        issue_summary(issue)
        for issue in issues_raw
        if "pull_request" not in issue
    ]
    runs_raw = github_get(
        f"/repos/{repo}/actions/runs",
        token,
        {"branch": branch, "per_page": str(run_limit)},
    )
    runs = [run_summary(run) for run in runs_raw.get("workflow_runs", [])]
    return {
        "repo": repo,
        "branch": branch,
        "open_issues": issues,
        "actionable_issues": [issue for issue in issues if issue["actionable_error"]],
        "recent_runs": runs,
        "latest_run": runs[0] if runs else None,
    }


def print_text(snapshot: dict[str, Any]) -> None:
    print(f"repo: {snapshot['repo']}")
    print(f"branch: {snapshot['branch']}")
    print("open issues:")
    for issue in snapshot["open_issues"]:
        marker = "actionable" if issue["actionable_error"] else "skip"
        print(f"- #{issue['number']} [{marker}] {issue['title']} {issue['html_url']}")
    if not snapshot["open_issues"]:
        print("- none")
    print("recent workflow runs:")
    for run in snapshot["recent_runs"]:
        sha = str(run.get("head_sha") or "")[:7]
        print(
            f"- {sha} {run.get('name')} {run.get('status')}/"
            f"{run.get('conclusion')} {run.get('html_url')}"
        )
    if not snapshot["recent_runs"]:
        print("- none")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Print GitHub issues and Actions snapshot.")
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    parser.add_argument("--issue-limit", type=int, default=100)
    parser.add_argument("--run-limit", type=int, default=10)
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    snapshot = build_snapshot(args.repo, args.branch, args.issue_limit, args.run_limit)
    if args.json:
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    else:
        print_text(snapshot)


if __name__ == "__main__":
    main()

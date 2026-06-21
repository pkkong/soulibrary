#!/usr/bin/env python3
"""Check that secret values are not committed.

The report intentionally prints only file paths, line numbers, and pattern
names. It never prints matched values.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IGNORED_PATHS = [
    ".env",
    ".secrets/",
    ".vercel",
    "supabase/.temp/",
]
SECRET_PATTERNS = [
    (
        "private_key",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----"),
    ),
    (
        "github_token",
        re.compile(r"(?:github_pat_|gh[pousr]_)[A-Za-z0-9_]{20,}"),
    ),
    (
        "jwt_like",
        re.compile(r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}"),
    ),
    (
        "hardcoded_odcloud_default",
        re.compile(r"ODCLOUD_API_KEY[^\n]{0,160}[A-Za-z0-9+/]{40,}={0,2}"),
    ),
    (
        "hardcoded_seoul_default",
        re.compile(r"SEOUL_API_KEY[^\n]{0,160}[0-9a-fA-F]{24,}"),
    ),
    (
        "literal_database_url",
        re.compile(r"(?i)(?:postgres|postgresql)://[^\s<>{}\"']+"),
    ),
]
TEXT_SUFFIXES = {
    "",
    ".cfg",
    ".css",
    ".env",
    ".example",
    ".html",
    ".js",
    ".json",
    ".md",
    ".py",
    ".sh",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}


def tracked_files() -> list[Path]:
    raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    return [ROOT / item.decode() for item in raw.split(b"\0") if item]


def is_text_candidate(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES


def is_allowed_match(path: Path, pattern_name: str, line: str) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return True
    if rel == ".env.example":
        return True
    if pattern_name == "literal_database_url":
        # Smoke tests use non-secret example URLs to verify Supabase routing.
        if rel == "scripts/smoke_test.py" and "example.supabase.co" in line:
            return True
        if "<" in line and ">" in line:
            return True
    return False


def scan_current() -> list[tuple[str, int, str]]:
    findings: list[tuple[str, int, str]] = []
    for path in tracked_files():
        if not path.exists() or not path.is_file() or not is_text_candidate(path):
            continue
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith("apps-in-toss/package-lock.json"):
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for line_no, line in enumerate(lines, 1):
            for pattern_name, pattern in SECRET_PATTERNS:
                if pattern.search(line) and not is_allowed_match(path, pattern_name, line):
                    findings.append((rel, line_no, pattern_name))
    return findings


def check_ignored_paths() -> list[str]:
    failures: list[str] = []
    for item in IGNORED_PATHS:
        result = subprocess.run(
            ["git", "check-ignore", "-q", item],
            cwd=ROOT,
            check=False,
        )
        if result.returncode != 0:
            failures.append(item)
    return failures


def env_keys(path: Path) -> list[str]:
    if not path.exists() or not path.is_file():
        return []
    keys: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        keys.append(stripped.split("=", 1)[0])
    return keys


def local_inventory() -> dict[str, object]:
    inventory: dict[str, object] = {
        ".env": env_keys(ROOT / ".env"),
        ".env.example": env_keys(ROOT / ".env.example"),
        ".secrets": [],
        ".vercel/project.json": [],
        "supabase/.temp/linked-project.json": [],
    }
    secrets_dir = ROOT / ".secrets"
    if secrets_dir.exists():
        inventory[".secrets"] = [
            item.relative_to(secrets_dir).as_posix()
            for item in sorted(secrets_dir.rglob("*"))
            if item.is_file()
        ]
    for rel in (".vercel/project.json", "supabase/.temp/linked-project.json"):
        path = ROOT / rel
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
                inventory[rel] = sorted(data.keys())
            except Exception:
                inventory[rel] = ["<unreadable-json>"]
    return inventory


def print_inventory() -> None:
    inventory = local_inventory()
    for label, items in inventory.items():
        print(label)
        if not items:
            print("  <none>")
            continue
        for item in items:
            print(f"  {item}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check local secret hygiene without printing values.")
    parser.add_argument("--inventory", action="store_true", help="Print local key/file inventory without values.")
    args = parser.parse_args()

    if args.inventory:
        print_inventory()

    ignored_failures = check_ignored_paths()
    findings = scan_current()

    if ignored_failures:
        print("Ignored-path failures:")
        for item in ignored_failures:
            print(f"  {item}")

    if findings:
        print("Potential committed secret values:")
        for rel, line_no, pattern_name in findings:
            print(f"  {rel}:{line_no}: {pattern_name}")

    if ignored_failures or findings:
        return 1

    print("secret_hygiene: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

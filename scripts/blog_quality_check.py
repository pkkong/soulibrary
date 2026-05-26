#!/usr/bin/env python3
"""Validate Soulib blog posts before automated publishing."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
BLOG_DIR = ROOT_DIR / "content" / "blog"
WEB_DIR = ROOT_DIR / "web"
ALLOWED_CATEGORY_SLUGS = {"guide", "recommendations"}
REQUIRED_FRONTMATTER = ("title", "description", "category", "category_slug", "date")
SUPPORTED_BODY_LINK_SCHEMES = ("http://", "https://")
STRICT_MIN_BODY_CHARS = 3500
BASELINE_MIN_BODY_CHARS = 900
SOULIB_SEARCH_BLOCK_RE = re.compile(r"^\[\[soulib-search:([^\]]+)\]\]$", flags=re.MULTILINE)


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text
    raw_meta = text[4:end]
    body = text[end + 5 :]
    meta: dict[str, str] = {}
    for line in raw_meta.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip('"')
    return meta, body


def body_char_count(body: str) -> int:
    stripped = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", body)
    stripped = re.sub(r"\[[^\]]+\]\([^)]+\)", "", stripped)
    stripped = re.sub(r"[#*_=`>\-\s|]", "", stripped)
    return len(stripped)


def markdown_links(body: str) -> list[tuple[str, str]]:
    return re.findall(r"(?<!!)\[([^\]]+)\]\(([^)]+)\)", body)


def markdown_images(body: str) -> list[tuple[str, str]]:
    return re.findall(r"!\[([^\]]*)\]\(([^)]+)\)", body)


def soulib_search_blocks(body: str) -> list[list[str]]:
    return [[part.strip() for part in match.split("|")] for match in SOULIB_SEARCH_BLOCK_RE.findall(body)]


def static_path_exists(url: str) -> bool:
    if not url.startswith("/static/"):
        return False
    path = WEB_DIR / url.lstrip("/").replace("/", "/")
    return path.is_file()


def tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[0-9A-Za-z가-힣]{2,}", text.lower())
        if token not in {"soulib", "https", "http", "www"}
    }


def token_similarity(left: str, right: str) -> float:
    left_tokens = tokens(left)
    right_tokens = tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def load_post(path: Path) -> tuple[dict[str, str], str]:
    return parse_frontmatter(path.read_text(encoding="utf-8"))


def all_post_paths() -> list[Path]:
    return sorted(path for path in BLOG_DIR.glob("*.md") if not path.name.startswith("_"))


def validate_post(path: Path, strict: bool, all_paths: list[Path]) -> list[str]:
    errors: list[str] = []
    meta, body = load_post(path)
    label = path.relative_to(ROOT_DIR)

    if not re.fullmatch(r"[0-9a-z][0-9a-z-]*\.md", path.name):
        errors.append(f"{label}: filename must be lowercase English slug ending in .md")

    for key in REQUIRED_FRONTMATTER:
        if not meta.get(key):
            errors.append(f"{label}: missing frontmatter `{key}`")

    if meta.get("category_slug") and meta["category_slug"] not in ALLOWED_CATEGORY_SLUGS:
        errors.append(f"{label}: category_slug must be one of {sorted(ALLOWED_CATEGORY_SLUGS)}")

    if meta.get("date"):
        try:
            datetime.strptime(meta["date"], "%Y-%m-%d")
        except ValueError:
            errors.append(f"{label}: date must be YYYY-MM-DD")

    if len(meta.get("description", "")) < 25:
        errors.append(f"{label}: description is too short to explain the post value")

    min_chars = STRICT_MIN_BODY_CHARS if strict else BASELINE_MIN_BODY_CHARS
    chars = body_char_count(body)
    if chars < min_chars:
        errors.append(f"{label}: body is too short ({chars} chars, minimum {min_chars})")

    headings = re.findall(r"^##\s+", body, flags=re.MULTILINE)
    if strict and len(headings) < 5:
        errors.append(f"{label}: strict posts need at least 5 `##` sections")

    if strict and not re.search(r"\*\*[^*]+\*\*", body):
        errors.append(f"{label}: strict posts need concrete bolded actions")

    if strict and not re.search(r"==[^=]+==", body):
        errors.append(f"{label}: strict posts need at least one highlighted caveat")

    if strict and "Soulib" not in body:
        errors.append(f"{label}: strict posts must explain how Soulib fits into the workflow")

    if strict and not all(term in body for term in ("도서관", "대출")):
        errors.append(f"{label}: strict posts must connect the guidance to library borrowing context")

    if re.search(r"\b(TODO|TBD|FIXME)\b", body, flags=re.IGNORECASE):
        errors.append(f"{label}: contains placeholder TODO/TBD/FIXME")

    if re.search(r"^\s*\|", body, flags=re.MULTILINE):
        errors.append(f"{label}: table syntax is not supported by the renderer")

    if re.search(r"^\s*\d+\.\s+", body, flags=re.MULTILINE):
        errors.append(f"{label}: numbered lists are not supported by the blog renderer")

    if re.search(r"<[^>]+>", body):
        errors.append(f"{label}: raw HTML is not supported in blog posts")

    links = markdown_links(body)
    if strict and meta.get("category_slug") == "guide" and len(links) < 2:
        errors.append(f"{label}: strict guide posts need at least two official http(s) source links")
    for _text, url in links:
        if not url.startswith(SUPPORTED_BODY_LINK_SCHEMES):
            errors.append(f"{label}: markdown links must use http(s), got `{url}`")
        if url.startswith(("http://www.soulib.kr/blog/", "https://www.soulib.kr/blog/")):
            continue
        if strict and "soulib.kr" not in url and not re.match(r"^https://", url):
            errors.append(f"{label}: strict external source links should use https, got `{url}`")

    image_url = meta.get("image", "")
    if image_url:
        if not static_path_exists(image_url):
            errors.append(f"{label}: frontmatter image must be an existing /static/ asset, got `{image_url}`")
        if strict and len(meta.get("image_alt", "")) < 12:
            errors.append(f"{label}: strict posts need specific image_alt text")

    images = markdown_images(body)
    for alt, url in images:
        if not static_path_exists(url):
            errors.append(f"{label}: body image must be an existing /static/ asset, got `{url}`")
        if strict and len(alt.strip()) < 12:
            errors.append(f"{label}: strict body images need specific alt/caption text")

    malformed_search_blocks = [
        line.strip()
        for line in body.splitlines()
        if "[[soulib-search:" in line and not SOULIB_SEARCH_BLOCK_RE.fullmatch(line.strip())
    ]
    for line in malformed_search_blocks:
        errors.append(f"{label}: malformed Soulib search card syntax `{line}`")

    search_blocks = soulib_search_blocks(body)
    for parts in search_blocks:
        if len(parts) < 3 or not all(parts[:3]):
            errors.append(f"{label}: Soulib search cards need title, meta, and note fields")
    if strict and meta.get("category_slug") == "recommendations":
        if len(search_blocks) < 3:
            errors.append(f"{label}: strict recommendation posts need at least 3 Soulib search cards")
        if not image_url and not images:
            errors.append(f"{label}: strict recommendation posts need a real visual asset")

    if strict and any(word in body for word in ("모든 도서관", "무조건", "반드시 대출", "자동으로 대출")):
        errors.append(f"{label}: strict post contains risky absolute wording")

    title_key = re.sub(r"\s+", "", meta.get("title", "").lower())
    for other_path in all_paths:
        if other_path == path:
            continue
        other_meta, other_body = load_post(other_path)
        other_title_key = re.sub(r"\s+", "", other_meta.get("title", "").lower())
        if title_key and title_key == other_title_key:
            errors.append(f"{label}: duplicate title with {other_path.relative_to(ROOT_DIR)}")
        if strict and token_similarity(body, other_body) >= 0.45:
            errors.append(f"{label}: too similar to existing post {other_path.relative_to(ROOT_DIR)}")

    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate Soulib blog Markdown quality.")
    parser.add_argument("paths", nargs="*", help="Specific blog markdown files to validate.")
    parser.add_argument("--strict", action="store_true", help="Apply automated-publishing quality gates.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.paths:
        paths = [Path(path).resolve() for path in args.paths]
    else:
        paths = all_post_paths()
    all_paths = all_post_paths()
    errors: list[str] = []
    for path in paths:
        if not path.exists():
            errors.append(f"{path}: file does not exist")
            continue
        if path.parent != BLOG_DIR.resolve():
            errors.append(f"{path}: file must be directly under content/blog")
            continue
        errors.extend(validate_post(path, args.strict, all_paths))

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    mode = "strict" if args.strict else "baseline"
    print(f"blog_quality_check: ok ({mode}, {len(paths)} post(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

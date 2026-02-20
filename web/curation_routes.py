import os
import json
import re
import time
import html
from pathlib import Path
from typing import Optional
from flask import Blueprint, render_template, request, abort, redirect, url_for, current_app
from db import get_db
from curations import (
    HOME_STYLE_OPTIONS,
    HOME_STYLE_VALUES,
    curation_template_path,
    get_curation_map,
    get_curations,
    save_curations,
)
from utils.normalize import normalize_author, normalize_title

curation_bp = Blueprint("curation", __name__)


def _normalize_loose_text(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").lower())


def _normalize_strict_text(value: str) -> str:
    return re.sub(r"[^0-9a-z\uac00-\ud7a3]", "", str(value or "").lower())


def _book_match_score(target_title: str, target_author: str, row: dict) -> dict:
    row_title = row.get("title") or ""
    row_author = row.get("author") or ""
    target_title_strict = _normalize_strict_text(target_title)
    row_title_strict = _normalize_strict_text(row_title)
    target_title_loose = _normalize_loose_text(target_title)
    row_title_loose = _normalize_loose_text(row_title)
    target_author_strict = _normalize_strict_text(target_author)
    row_author_strict = _normalize_strict_text(row_author)

    title_score = 0
    if target_title_strict and row_title_strict:
        if row_title_strict == target_title_strict:
            title_score = 100
        elif row_title_strict.startswith(target_title_strict) or target_title_strict.startswith(row_title_strict):
            title_score = 70
        elif target_title_loose and row_title_loose and (
            row_title_loose in target_title_loose or target_title_loose in row_title_loose
        ):
            title_score = 40

    author_score = 0
    if target_author_strict and row_author_strict:
        if row_author_strict == target_author_strict:
            author_score = 40
        elif row_author_strict in target_author_strict or target_author_strict in row_author_strict:
            author_score = 20

    return {"title": title_score, "author": author_score, "total": title_score + author_score}


def _find_book_id_by_title_author(title: str, author: str) -> Optional[int]:
    norm_title = normalize_title(title)
    norm_author = normalize_author(author)
    if not norm_title:
        return None

    conn = get_db()
    try:
        rows = []
        # Fast exact lookup by normalized title.
        if norm_author:
            cur = conn.execute(
                """
                SELECT id, title, author
                FROM books
                WHERE title_norm = ? AND author_norm = ?
                ORDER BY id
                LIMIT 10
                """,
                (norm_title, norm_author),
            )
            rows = cur.fetchall() or []
        if not rows:
            cur = conn.execute(
                """
                SELECT id, title, author
                FROM books
                WHERE title_norm = ?
                ORDER BY id
                LIMIT 60
                """,
                (norm_title,),
            )
            rows = cur.fetchall() or []
        if not rows:
            cur = conn.execute(
                """
                SELECT id, title, author
                FROM books
                WHERE title_norm LIKE ?
                ORDER BY id
                LIMIT 80
                """,
                (f"{norm_title}%",),
            )
            rows = cur.fetchall() or []
    finally:
        conn.close()

    if not rows:
        return None

    scored = []
    for row in rows:
        score = _book_match_score(title, author, row)
        scored.append((score["total"], score["title"], score["author"], row))
    scored.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    best_total, best_title, best_author, best_row = scored[0]
    has_author = bool(_normalize_strict_text(author))
    if best_title < 70:
        return None
    if has_author and best_author < 20:
        return None
    if best_total <= 0:
        return None
    return int(best_row.get("id"))


def _resolve_book_ids_from_entries(entries: list[dict]) -> tuple[list[int], list[dict]]:
    resolved_ids = []
    unresolved = []
    seen = set()
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title") or "").strip()
        author = str(entry.get("author") or "").strip()
        if not title:
            continue
        book_id = _find_book_id_by_title_author(title, author)
        if not book_id:
            unresolved.append({"title": title, "author": author})
            continue
        if book_id in seen:
            continue
        seen.add(book_id)
        resolved_ids.append(book_id)
    return resolved_ids, unresolved


def _dedupe_book_ids_by_group(book_ids: list[int]) -> list[int]:
    ordered_ids = []
    seen_ids = set()
    for book_id in book_ids or []:
        try:
            value = int(book_id)
        except Exception:
            continue
        if value in seen_ids:
            continue
        seen_ids.add(value)
        ordered_ids.append(value)

    if not ordered_ids:
        return []

    conn = get_db()
    try:
        placeholders = ",".join("?" for _ in ordered_ids)
        cur = conn.execute(
            f"""
            SELECT id, merge_group_id, canonical_id, publisher_norm
            FROM books
            WHERE id IN ({placeholders})
            """,
            ordered_ids,
        )
        rows = cur.fetchall() or []
    finally:
        conn.close()

    by_id = {int(row.get("id")): row for row in rows if row and row.get("id") is not None}
    deduped = []
    seen_keys = set()
    for book_id in ordered_ids:
        row = by_id.get(book_id)
        if not row:
            # Keep unknown ids as-is to avoid unexpected data loss.
            key = f"id:{book_id}"
            if key in seen_keys:
                continue
            seen_keys.add(key)
            deduped.append(book_id)
            continue

        group_id = row.get("merge_group_id") or row.get("canonical_id") or row.get("id")
        publisher_norm = row.get("publisher_norm") or ""
        key = f"{group_id}:{publisher_norm}"
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(book_id)
    return deduped


def _is_local_request():
    return request.remote_addr in {"127.0.0.1", "::1"}


def _curation_admin_enabled():
    raw = (os.environ.get("ENABLE_CURATION_ADMIN") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _curation_admin_allowed():
    if not _curation_admin_enabled():
        return False
    # Local-only editing policy:
    # curation update is allowed only on localhost when explicitly enabled.
    return _is_local_request()


def _normalize_slug(value: str) -> str:
    slug = (value or "").strip()
    if not slug:
        return ""
    slug = slug.replace(" ", "-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug


def _auto_slug_from_title(title: str) -> str:
    cleaned = re.sub(r"[^\w]+", "-", (title or "").lower(), flags=re.UNICODE).strip("-")
    return cleaned


def _parse_book_ids(raw: str):
    ids = []
    for part in re.split(r"[,\s]+", raw or ""):
        part = part.strip()
        if not part:
            continue
        if part.isdigit():
            ids.append(int(part))
    return ids


def _parse_books_text(raw: str):
    books = []
    for line in (raw or "").splitlines():
        text = line.strip()
        if not text:
            continue
        if "|" in text:
            title, author = text.split("|", 1)
        elif " - " in text:
            title, author = text.split(" - ", 1)
        elif "-" in text:
            title, author = text.split("-", 1)
        elif "/" in text:
            title, author = text.split("/", 1)
        else:
            title, author = text, ""
        title = title.strip()
        author = author.strip()
        if not title:
            continue
        books.append({"title": title, "author": author})
    return books


def _strip_heading_prefix(text: str) -> str:
    return re.sub(r"^#{1,6}\s*", "", text or "").strip()


def _extract_title_summary(raw_text: str):
    raw_text = raw_text or ""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", raw_text) if b.strip()]
    if not blocks:
        return "", ""
    first_line = _strip_heading_prefix(blocks[0].splitlines()[0])
    title = first_line if len(first_line) <= 120 else first_line[:120]
    summary = ""
    if len(blocks) > 1:
        summary = blocks[1].replace("\n", " ").strip()
    else:
        summary = blocks[0].replace("\n", " ").strip()
    if summary.startswith(title):
        summary = summary[len(title) :].strip(" -–—:")
    if len(summary) > 200:
        summary = summary[:200].rstrip() + "..."
    return title, summary


def _extract_books_from_text(raw_text: str):
    books = []
    for line in (raw_text or "").splitlines():
        text = line.strip()
        if not text:
            continue
        text = re.sub(r"^[\-\*\u2022\s]+", "", text)
        text = re.sub(r"^\d+[\.\)]\s*", "", text)
        if "추천" in text and "목록" in text:
            continue
        match = re.match(r"^(.+?)\s*(?:[-–—|/]\s+)\s*(.+)$", text)
        if match:
            title = match.group(1).strip()
            author = match.group(2).strip()
            if title and author:
                books.append({"title": title, "author": author})
    return books


def _parse_sectioned_text(raw_text: str):
    sections = {}
    current = None
    for line in (raw_text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            if current:
                sections[current].append("")
            continue
        match = re.match(r"^\[(.+?)\]\s*$", stripped)
        if match:
            label = match.group(1).strip().lower()
            label = label.split(":")[0].strip()
            if "제목" in label:
                current = "title"
            elif "요약" in label:
                current = "summary"
            elif "본문" in label:
                current = "body"
            elif "추천" in label or "목록" in label:
                current = "books"
            elif "참고" in label:
                current = "refs"
            else:
                current = None
            if current and current not in sections:
                sections[current] = []
            continue
        if current:
            sections[current].append(stripped)
    return {k: "\n".join(v).strip() for k, v in sections.items() if v}


def _inline_format(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"__(.+?)__", r"<strong>\1</strong>", text)
    return text


def _text_to_html(raw_text: str) -> str:
    lines = (raw_text or "").splitlines()
    html_parts = []
    list_mode = None

    def close_list():
        nonlocal list_mode
        if list_mode:
            html_parts.append(f"</{list_mode}>")
            list_mode = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            close_list()
            continue
        heading = re.match(r"^(#{1,3})\s+(.*)", stripped)
        if heading:
            close_list()
            level = len(heading.group(1)) + 1
            level = min(level, 4)
            content = _inline_format(heading.group(2).strip())
            html_parts.append(f"<h{level}>{content}</h{level}>")
            continue
        ordered = re.match(r"^(\d+)[\.\)]\s+(.*)", stripped)
        if ordered:
            if list_mode != "ol":
                close_list()
                list_mode = "ol"
                html_parts.append("<ol>")
            content = _inline_format(ordered.group(2).strip())
            html_parts.append(f"<li>{content}</li>")
            continue
        bullet = re.match(r"^[-*\u2022]\s+(.*)", stripped)
        if bullet:
            if list_mode != "ul":
                close_list()
                list_mode = "ul"
                html_parts.append("<ul>")
            content = _inline_format(bullet.group(1).strip())
            html_parts.append(f"<li>{content}</li>")
            continue
        close_list()
        content = _inline_format(stripped)
        html_parts.append(f"<p>{content}</p>")

    close_list()
    return "\n".join(html_parts).strip()


def _extract_json_payload(raw_text: str):
    text = (raw_text or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _normalize_source_urls(value):
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list):
        items = value
    else:
        items = []
    urls = []
    seen = set()
    for item in items:
        text = str(item or "").strip()
        if not text:
            continue
        md = re.match(r"^\[[^\]]+\]\((https?://[^)]+)\)$", text)
        if md:
            text = md.group(1).strip()
        else:
            m = re.search(r"(https?://[^\s)]+)", text)
            if m:
                text = m.group(1).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        urls.append(text)
    return urls


def _normalize_tags(value):
    if not isinstance(value, list):
        return []
    tags = []
    seen = set()
    for item in value:
        tag = str(item or "").strip()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)
    return tags


def _normalize_books_from_json(value):
    if not isinstance(value, list):
        return []
    books = []
    for item in value:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        author = str(item.get("author") or "").strip()
        reason = str(item.get("reason") or "").strip()
        source_urls = _normalize_source_urls(item.get("source_urls"))
        if not title:
            continue
        book = {"title": title, "author": author}
        if reason:
            book["reason"] = reason
        if source_urls:
            book["source_urls"] = source_urls
        books.append(book)
    return books


def _paragraphs(text: str):
    return [part.strip() for part in re.split(r"\n\s*\n", text or "") if part.strip()]


def _build_content_html_from_json(payload: dict, books: list):
    parts = []
    for para in _paragraphs(str(payload.get("body_intro") or "")):
        parts.append(f"<p>{_inline_format(html.escape(para))}</p>")
    if books:
        for idx, book in enumerate(books, start=1):
            title = html.escape(book.get("title") or "")
            author = html.escape(book.get("author") or "")
            reason = book.get("reason") or ""
            parts.append('<section class="curation-book-block">')
            if author:
                parts.append(f"<h4>{idx}. {title} ({author})</h4>")
            else:
                parts.append(f"<h4>{idx}. {title}</h4>")
            if reason:
                for para in _paragraphs(reason):
                    parts.append(f"<p>{_inline_format(html.escape(para))}</p>")
            parts.append("</section>")
    for para in _paragraphs(str(payload.get("body_outro") or "")):
        parts.append(f"<p>{_inline_format(html.escape(para))}</p>")
    return "\n".join(parts).strip()


@curation_bp.route("/curations")
def curations_page():
    curated = []
    for c in get_curations():
        item = dict(c)
        item["book_count"] = len(c.get("book_ids") or c.get("books") or [])
        curated.append(item)
    return render_template(
        "curations.html",
        curations=curated,
        show_topbar=True,
        topbar_desc="오늘의책",
        active_tab="curation",
    )


@curation_bp.route("/curation/<slug>")
def curation_detail(slug):
    curation = get_curation_map().get(slug)
    if not curation:
        abort(404)
    book_count = len(curation.get("book_ids") or curation.get("books") or [])
    return render_template(
        "curation_detail.html",
        curation=curation,
        book_count=book_count,
        show_topbar=True,
        topbar_desc="오늘의책",
        active_tab="curation",
    )


@curation_bp.route("/admin/curations")
def curation_admin():
    if not _curation_admin_allowed():
        abort(403)
    slug = (request.args.get("slug") or "").strip()
    selected = None
    content_html = ""
    book_ids_str = ""
    books_text = ""
    json_payload = ""

    curations = []
    for c in get_curations():
        item = dict(c)
        item["book_count"] = len(c.get("book_ids") or c.get("books") or [])
        curations.append(item)
        if slug and item.get("slug") == slug:
            selected = item

    if selected:
        book_ids = selected.get("book_ids") or []
        book_ids_str = ",".join(str(x) for x in book_ids)
        books = selected.get("books") or []
        if books:
            lines = []
            for b in books:
                title = (b.get("title") or "").strip()
                author = (b.get("author") or "").strip()
                if author:
                    lines.append(f"{title} | {author}")
                else:
                    lines.append(title)
            books_text = "\n".join(lines)
        template_ref = selected.get("content_template")
        if template_ref:
            template_path = Path(current_app.root_path) / "templates" / template_ref
            if template_path.exists():
                content_html = template_path.read_text(encoding="utf-8")

    return render_template(
        "curation_admin.html",
        curations=curations,
        selected=selected,
        content_html=content_html,
        book_ids_str=book_ids_str,
        books_text=books_text,
        home_style_options=HOME_STYLE_OPTIONS,
        json_payload=json_payload,
        raw_text="",
        status=request.args.get("status"),
        message=request.args.get("message"),
    )


@curation_bp.route("/admin/curations/save", methods=["POST"])
def curation_admin_save():
    if not _curation_admin_allowed():
        abort(403)
    form = request.form

    title = (form.get("title") or "").strip()
    summary = (form.get("summary") or "").strip()
    kicker = (form.get("kicker") or "").strip()
    home_enabled = form.get("home_enabled") == "1"
    home_style = (form.get("home_style") or "").strip().lower()
    home_order_raw = (form.get("home_order") or "").strip()
    feature_image = (form.get("feature_image") or "").strip()
    raw_slug = form.get("slug") or ""
    original_slug = (form.get("original_slug") or "").strip()
    raw_text = (form.get("raw_text") or "").strip()
    json_payload_text = (form.get("json_payload") or "").strip()
    auto_mode = form.get("auto_mode") == "1"

    book_ids = _parse_book_ids(form.get("book_ids") or "")
    books = _parse_books_text(form.get("books_text") or "")
    content_html = (form.get("content_html") or "")
    clear_content = form.get("clear_content") == "1"
    top_source_urls = []
    tags = []
    parsed_json_used = False
    auto_resolve_total = 0
    auto_resolve_ok = 0
    auto_resolve_unresolved = []

    auto_input = json_payload_text or raw_text
    if auto_input and (auto_mode or not content_html.strip()):
        parsed_json = _extract_json_payload(auto_input)
        if parsed_json:
            parsed_json_used = True
            if not title:
                title = str(parsed_json.get("title") or "").strip()
            if not summary:
                summary = str(parsed_json.get("summary") or "").strip()
            if not kicker:
                kicker = str(parsed_json.get("kicker") or "").strip()
            if not feature_image:
                feature_image = str(parsed_json.get("feature_image") or "").strip()
            parsed_books = _normalize_books_from_json(parsed_json.get("books"))
            if parsed_books and not book_ids:
                books = parsed_books
            if not content_html.strip():
                generated_html = _build_content_html_from_json(parsed_json, parsed_books)
                if generated_html:
                    content_html = generated_html
            top_source_urls = _normalize_source_urls(parsed_json.get("source_urls"))
            if not top_source_urls and parsed_books:
                combined = []
                for book in parsed_books:
                    combined.extend(book.get("source_urls") or [])
                top_source_urls = _normalize_source_urls(combined)
            tags = _normalize_tags(parsed_json.get("tags"))
        else:
            sections = _parse_sectioned_text(auto_input)
            body_source = sections.get("body") or auto_input
            generated_html = _text_to_html(body_source)
            if generated_html:
                content_html = generated_html
            if not title or not summary:
                if sections.get("title") and not title:
                    title = sections["title"].splitlines()[0].strip()
                if sections.get("summary") and not summary:
                    summary = sections["summary"].replace("\n", " ").strip()
            if not title or not summary:
                extracted_title, extracted_summary = _extract_title_summary(auto_input)
                if not title and extracted_title:
                    title = extracted_title
                if not summary and extracted_summary:
                    summary = extracted_summary
            if not book_ids and not books:
                books_source = sections.get("books") or auto_input
                extracted_books = _parse_books_text(books_source) or _extract_books_from_text(books_source)
                if extracted_books:
                    books = extracted_books

    # Auto-confirm: resolve title/author entries to fixed book_id at save-time.
    if not book_ids and books:
        auto_resolve_total = len(books)
        try:
            resolved_ids, unresolved = _resolve_book_ids_from_entries(books)
            book_ids = resolved_ids
            auto_resolve_ok = len(resolved_ids)
            auto_resolve_unresolved = unresolved
        except Exception:
            auto_resolve_total = 0
            auto_resolve_ok = 0
            auto_resolve_unresolved = []

    slug = _normalize_slug(raw_slug)
    if not slug:
        slug = _auto_slug_from_title(title)
    if not slug:
        slug = f"curation-{int(time.time())}"
    if not title:
        return redirect(
            url_for(
                "curation.curation_admin",
                status="error",
                message="제목을 입력해주세요.",
            )
        )

    curations = [dict(c) for c in get_curations()]
    existing = next((c for c in curations if c.get("slug") == slug), None)
    if original_slug and original_slug != slug:
        curations = [c for c in curations if c.get("slug") != original_slug]
        existing = None

    entry = dict(existing) if existing else {}
    entry.update(
        {
            "slug": slug,
            "title": title,
            "summary": summary,
        }
    )

    if kicker:
        entry["kicker"] = kicker
    else:
        entry.pop("kicker", None)

    entry["home_enabled"] = home_enabled
    if home_style in HOME_STYLE_VALUES:
        entry["home_style"] = home_style
    else:
        entry.pop("home_style", None)
    if home_order_raw:
        try:
            entry["home_order"] = int(home_order_raw)
        except Exception:
            pass
    else:
        entry.pop("home_order", None)

    if feature_image:
        entry["feature_image"] = feature_image
    else:
        entry.pop("feature_image", None)

    if parsed_json_used:
        if tags:
            entry["tags"] = tags
        else:
            entry.pop("tags", None)

        if top_source_urls:
            entry["source_urls"] = top_source_urls
        else:
            entry.pop("source_urls", None)

    if book_ids:
        book_ids = _dedupe_book_ids_by_group(book_ids)
        entry["book_ids"] = book_ids
    else:
        entry.pop("book_ids", None)

    if books:
        entry["books"] = books
    else:
        entry.pop("books", None)

    if clear_content:
        entry.pop("content_template", None)
        entry.pop("content_html", None)
        template_path = curation_template_path(slug)
        if template_path.exists():
            template_path.unlink()
    elif content_html.strip():
        template_path = curation_template_path(slug)
        template_path.parent.mkdir(parents=True, exist_ok=True)
        template_path.write_text(content_html.strip() + "\n", encoding="utf-8")
        entry["content_template"] = f"curations/{slug}.html"
        entry.pop("content_html", None)

    if existing:
        updated = []
        replaced = False
        for c in curations:
            if c.get("slug") == slug:
                updated.append(entry)
                replaced = True
            else:
                updated.append(c)
        if not replaced:
            updated.append(entry)
        curations = updated
    else:
        curations.append(entry)

    save_curations(curations)

    message = ""
    if auto_resolve_total:
        unresolved_count = len(auto_resolve_unresolved)
        if unresolved_count:
            message = f"book_id 자동확정: {auto_resolve_ok}/{auto_resolve_total} (미매칭 {unresolved_count}권)"
        else:
            message = f"book_id 자동확정: {auto_resolve_ok}/{auto_resolve_total}"

    return redirect(url_for("curation.curation_admin", slug=slug, status="saved", message=message))


@curation_bp.route("/admin/curations/delete", methods=["POST"])
def curation_admin_delete():
    if not _curation_admin_allowed():
        abort(403)
    slug = (request.form.get("slug") or "").strip()
    if not slug:
        return redirect(url_for("curation.curation_admin", status="error", message="slug_required"))

    curations = [c for c in get_curations() if c.get("slug") != slug]
    save_curations(curations)

    template_path = curation_template_path(slug)
    if template_path.exists():
        template_path.unlink()

    return redirect(url_for("curation.curation_admin", status="deleted"))

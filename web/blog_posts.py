import html
import os
import re
from datetime import datetime


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLOG_DIR = os.path.join(ROOT_DIR, "content", "blog")


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _parse_frontmatter(text):
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text
    raw_meta = text[4:end]
    body = text[end + 5 :]
    meta = {}
    for line in raw_meta.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip('"')
    return meta, body


def _inline(text):
    escaped = html.escape(text)

    def replace_link(match):
        label = html.escape(match.group(1))
        url = html.escape(match.group(2), quote=True)
        if not re.match(r"^https?://", url):
            return label
        return f'<a href="{url}" target="_blank" rel="noopener">{label}</a>'

    return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", replace_link, escaped)


def _render_body(body):
    blocks = []
    list_items = []

    def flush_list():
        nonlocal list_items
        if list_items:
            items = "".join(f"<li>{item}</li>" for item in list_items)
            blocks.append(f"<ul>{items}</ul>")
            list_items = []

    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            flush_list()
            continue
        if line.startswith("### "):
            flush_list()
            blocks.append(f"<h3>{_inline(line[4:])}</h3>")
        elif line.startswith("## "):
            flush_list()
            blocks.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.startswith("- "):
            list_items.append(_inline(line[2:]))
        else:
            flush_list()
            blocks.append(f"<p>{_inline(line)}</p>")
    flush_list()
    return "\n".join(blocks)


def _display_date(value):
    value = _clean(value)
    if not value:
        return ""
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%Y.%m.%d")
    except ValueError:
        return value


def _load_post(path):
    with open(path, "r", encoding="utf-8") as f:
        meta, body = _parse_frontmatter(f.read())
    slug = os.path.splitext(os.path.basename(path))[0]
    title = _clean(meta.get("title")) or slug
    return {
        "slug": slug,
        "title": title,
        "description": _clean(meta.get("description")),
        "category": _clean(meta.get("category")) or "가이드",
        "date": _clean(meta.get("date")),
        "date_label": _display_date(meta.get("date")),
        "html": _render_body(body),
    }


def get_blog_posts():
    if not os.path.isdir(BLOG_DIR):
        return []
    posts = []
    for name in os.listdir(BLOG_DIR):
        if name.startswith("_") or not name.endswith(".md"):
            continue
        try:
            posts.append(_load_post(os.path.join(BLOG_DIR, name)))
        except Exception as exc:
            print(f"[blog warning] failed to load {name}: {exc}")
    return sorted(posts, key=lambda post: (post.get("date") or "", post.get("title") or ""), reverse=True)


def get_blog_post(slug):
    slug = re.sub(r"[^0-9A-Za-z_-]", "", slug or "")
    if not slug:
        return None
    for post in get_blog_posts():
        if post["slug"] == slug:
            return post
    return None

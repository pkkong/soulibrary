import html
import os
import re
from datetime import datetime
from functools import lru_cache

try:
    from PIL import Image
except Exception:
    Image = None


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLOG_DIR = os.path.join(ROOT_DIR, "content", "blog")
BLOG_CATEGORIES = [
    {
        "slug": "guide",
        "title": "이용 안내",
        "description": "Soulib 사용법, 서울온 준비, 전자책 앱과 대출 상태를 정리합니다.",
    },
    {
        "slug": "recommendations",
        "title": "책 추천",
        "description": "신간, 베스트셀러, 주제별 추천 목록을 준비합니다.",
    },
]
CATEGORY_ALIASES = {
    "이용 안내": "guide",
    "Soulib 이용 가이드": "guide",
    "가이드": "guide",
    "사용법": "guide",
    "전자도서관 이용 팁": "guide",
    "전자도서관 팁": "guide",
    "책 추천": "recommendations",
    "서비스 소식": "guide",
}


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _category_for(meta):
    category = _clean(meta.get("category")) or "이용 안내"
    category_slug = re.sub(r"[^0-9A-Za-z_-]", "", _clean(meta.get("category_slug")))
    if not category_slug:
        category_slug = CATEGORY_ALIASES.get(category, "")
    if category_slug == "library":
        category_slug = "guide"
    if not category_slug:
        category_slug = "guide"
    category_title = next((item["title"] for item in BLOG_CATEGORIES if item["slug"] == category_slug), category)
    return category_slug, category_title


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

    rendered = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", replace_link, escaped)
    rendered = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", rendered)
    rendered = re.sub(r"__(.+?)__", r"<strong>\1</strong>", rendered)
    rendered = re.sub(r"==(.+?)==", r'<mark class="blog-highlight">\1</mark>', rendered)
    return rendered


@lru_cache(maxsize=64)
def _image_size(url):
    if not Image or not url.startswith("/static/"):
        return None, None
    path = os.path.join(ROOT_DIR, "web", url.lstrip("/").replace("/", os.sep))
    if not os.path.isfile(path):
        return None, None
    try:
        with Image.open(path) as img:
            return img.size
    except Exception:
        return None, None


def _render_image(line):
    match = re.fullmatch(r"!\[([^\]]*)\]\(([^)]+)\)", line)
    if not match:
        return None
    alt = _clean(match.group(1))
    url = _clean(match.group(2))
    if not (url.startswith("/static/") or re.match(r"^https?://", url)):
        return None
    safe_alt = html.escape(alt, quote=True)
    safe_url = html.escape(url, quote=True)
    width, height = _image_size(url)
    size_attrs = f' width="{width}" height="{height}"' if width and height else ""
    figure_class = "blog-figure"
    if width and height and height / max(width, 1) >= 1.6:
        figure_class += " blog-figure-tall"
    caption = f"<figcaption>{html.escape(alt)}</figcaption>" if alt else ""
    return f'<figure class="{figure_class}"><img src="{safe_url}" alt="{safe_alt}" loading="lazy"{size_attrs}>{caption}</figure>'


def _render_heading(level, text):
    anchor = ""
    match = re.search(r"\s+\{#([0-9A-Za-z_-]+)\}$", text)
    if match:
        anchor = match.group(1)
        text = text[: match.start()].rstrip()
    attr = f' id="{html.escape(anchor, quote=True)}"' if anchor else ""
    return f"<h{level}{attr}>{_inline(text)}</h{level}>"


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
        image_html = _render_image(line)
        if image_html:
            flush_list()
            blocks.append(image_html)
            continue
        if line.startswith("### "):
            flush_list()
            blocks.append(_render_heading(3, line[4:]))
        elif line.startswith("## "):
            flush_list()
            blocks.append(_render_heading(2, line[3:]))
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
    category_slug, category_title = _category_for(meta)
    return {
        "slug": slug,
        "title": title,
        "description": _clean(meta.get("description")),
        "category": category_title,
        "category_slug": category_slug,
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


def get_blog_categories(posts=None):
    posts = posts if posts is not None else get_blog_posts()
    counts = {}
    latest = {}
    for post in posts:
        slug = post.get("category_slug") or "guide"
        counts[slug] = counts.get(slug, 0) + 1
        if slug not in latest:
            latest[slug] = post
    return [
        {
            **category,
            "count": counts.get(category["slug"], 0),
            "latest": latest.get(category["slug"]),
        }
        for category in BLOG_CATEGORIES
    ]

import html
import os
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

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
BLOG_SEARCH_CARD_COVERS = {
    "13.67": "/static/img/blog/book-covers/thirteen-sixtyseven.jpg",
    "긴긴밤": "/static/img/blog/book-covers/long-night.jpg",
    "그리고 아무도 없었다": "/static/img/blog/book-covers/and-then-none.jpg",
    "달러구트 꿈 백화점": "/static/img/blog/book-covers/dollargut.jpg",
    "돈의 속성": "/static/img/blog/book-covers/money-attribute.jpg",
    "돌이킬 수 없는 약속": "/static/img/blog/book-covers/promise.jpg",
    "마당을 나온 암탉": "/static/img/blog/book-covers/hen.jpg",
    "마션": "/static/img/blog/book-covers/martian.jpg",
    "미드나잇 라이브러리": "/static/img/blog/book-covers/midnight-library.jpg",
    "부의 추월차선": "/static/img/blog/book-covers/millionaire-fastlane.jpg",
    "불편한 편의점": "/static/img/blog/book-covers/inconvenient-store.jpg",
    "살인자의 기억법": "/static/img/blog/book-covers/murderer-memory.jpg",
    "삼체 1부": "/static/img/blog/book-covers/three-body.jpg",
    "세이노의 가르침": "/static/img/blog/book-covers/sayno.jpg",
    "숨": "/static/img/blog/book-covers/exhalation.jpg",
    "십각관의 살인": "/static/img/blog/book-covers/deca-house.jpg",
    "아몬드": "/static/img/blog/book-covers/almond.jpg",
    "아주 작은 습관의 힘": "/static/img/blog/book-covers/atomic-habits.jpg",
    "역행자": "/static/img/blog/book-covers/counterflow.jpg",
    "완득이": "/static/img/blog/book-covers/wandeuk.jpg",
    "용의자 X의 헌신": "/static/img/blog/book-covers/suspect-x.jpg",
    "우리가 빛의 속도로 갈 수 없다면": "/static/img/blog/book-covers/kim-lightspeed.jpg",
    "원더": "/static/img/blog/book-covers/wonder.jpg",
    "원씽": "/static/img/blog/book-covers/one-thing.jpg",
    "클라라와 태양": "/static/img/blog/book-covers/klara-sun.jpg",
    "트렌드 코리아 2026": "/static/img/blog/book-covers/trend-korea-2026.jpg",
    "페인트": "/static/img/blog/book-covers/paint.jpg",
}
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


def _safe_image(value):
    url = _clean(value)
    if url.startswith("/static/") and _static_file_exists(url):
        return url
    if re.match(r"^https?://", url):
        return url
    return ""


def _static_file_exists(url):
    if not url.startswith("/static/"):
        return False
    path = os.path.join(ROOT_DIR, "web", url.lstrip("/").replace("/", os.sep))
    return os.path.isfile(path)


def _search_card_cover_url(title):
    url = BLOG_SEARCH_CARD_COVERS.get(title)
    if url and _static_file_exists(url):
        return url
    return ""


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
    if not url.startswith("/static/"):
        return None, None
    path = os.path.join(ROOT_DIR, "web", url.lstrip("/").replace("/", os.sep))
    if not os.path.isfile(path):
        return None, None
    if Path(path).suffix.lower() == ".svg":
        try:
            head = Path(path).read_text(encoding="utf-8")[:1000]
        except OSError:
            return None, None
        width_match = re.search(r'\bwidth="([0-9.]+)(?:px)?"', head)
        height_match = re.search(r'\bheight="([0-9.]+)(?:px)?"', head)
        if width_match and height_match:
            return int(float(width_match.group(1))), int(float(height_match.group(1)))
        viewbox_match = re.search(r'\bviewBox="([0-9.\s-]+)"', head)
        if viewbox_match:
            parts = [float(part) for part in viewbox_match.group(1).split()]
            if len(parts) == 4 and parts[2] > 0 and parts[3] > 0:
                return int(parts[2]), int(parts[3])
        return None, None
    if Path(path).suffix.lower() == ".png":
        try:
            with open(path, "rb") as image_file:
                header = image_file.read(24)
            if header.startswith(b"\x89PNG\r\n\x1a\n") and len(header) >= 24:
                return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")
        except OSError:
            return None, None
    if not Image:
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
    if url.startswith("/static/") and not _static_file_exists(url):
        return None
    safe_alt = html.escape(alt, quote=True)
    safe_url = html.escape(url, quote=True)
    width, height = _image_size(url)
    size_attrs = f' width="{width}" height="{height}"' if width and height else ""
    figure_class = "blog-figure"
    if width and height and height / max(width, 1) >= 1.25:
        figure_class += " blog-figure-tall"
    if width and height and width / max(height, 1) >= 1.25:
        figure_class += " blog-figure-wide"
    if url.startswith("/static/img/blog/seoul-on/"):
        figure_class += " blog-figure-wide"
    caption = f"<figcaption>{html.escape(alt)}</figcaption>" if alt else ""
    return f'<figure class="{figure_class}"><img src="{safe_url}" alt="{safe_alt}" loading="lazy"{size_attrs}>{caption}</figure>'


def _render_soulib_search_card(line):
    match = re.fullmatch(r"\[\[soulib-search:([^\]]+)\]\]", line)
    if not match:
        return None
    parts = [_clean(part) for part in match.group(1).split("|")]
    if len(parts) < 3:
        return None
    title, meta, note = parts[:3]
    query = parts[3] if len(parts) >= 4 and parts[3] else " ".join(part for part in (title, meta) if part)
    if not title or not query:
        return None
    href = f"/search?q={quote(query)}&field=title_author"
    safe_href = html.escape(href, quote=True)
    safe_query = html.escape(query, quote=True)
    safe_title = html.escape(title)
    safe_title_attr = html.escape(title, quote=True)
    safe_meta = html.escape(meta)
    safe_meta_attr = html.escape(meta, quote=True)
    safe_note = html.escape(note)
    cover_url = _search_card_cover_url(title)
    cover_attr = f' data-cover-url="{html.escape(cover_url, quote=True)}"' if cover_url else ""
    return (
        f'<a class="blog-search-card" href="{safe_href}" data-search-query="{safe_query}" '
        f'data-search-title="{safe_title_attr}" data-search-meta="{safe_meta_attr}"{cover_attr} '
        f'aria-label="Soulib에서 {safe_title} 검색">'
        '<span class="blog-search-card-cover" aria-hidden="true"></span>'
        '<span class="blog-search-card-copy">'
        f'<strong>{safe_title}</strong>'
        f'<span class="blog-search-card-meta">{safe_meta}</span>'
        f'<small class="blog-search-card-note">{safe_note}</small>'
        '</span>'
        '</a>'
    )


def _render_advice_paragraph(line):
    labels = {
        "왜 이 책이 맞는지": ("읽기 좋은 이유", "fit"),
        "이런 독자는 건너뛰세요": ("맞지 않을 수 있는 경우", "skip"),
    }
    label_pattern = "|".join(re.escape(label) for label in labels)
    match = re.match(rf"^({label_pattern})\s*[:：]\s*(.+)$", line)
    if not match:
        return None
    raw_label, body = match.group(1), match.group(2).strip()
    display_label, tone = labels[raw_label]
    return (
        f'<p class="blog-advice blog-advice-{tone}">'
        f'<strong class="blog-advice-label">{html.escape(display_label)}</strong>'
        f'<span class="blog-advice-copy">{_inline(body)}</span>'
        '</p>'
    )


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
    search_cards = []

    def flush_list():
        nonlocal list_items
        if list_items:
            items = "".join(f"<li>{item}</li>" for item in list_items)
            blocks.append(f"<ul>{items}</ul>")
            list_items = []

    def flush_search_cards():
        nonlocal search_cards
        if search_cards:
            blocks.append(f'<div class="blog-search-grid">{"".join(search_cards)}</div>')
            search_cards = []

    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            flush_list()
            flush_search_cards()
            continue
        search_card_html = _render_soulib_search_card(line)
        if search_card_html:
            flush_list()
            search_cards.append(search_card_html)
            continue
        image_html = _render_image(line)
        if image_html:
            flush_list()
            flush_search_cards()
            blocks.append(image_html)
            continue
        advice_html = _render_advice_paragraph(line)
        if advice_html:
            flush_list()
            flush_search_cards()
            blocks.append(advice_html)
            continue
        if line.startswith("### "):
            flush_list()
            flush_search_cards()
            blocks.append(_render_heading(3, line[4:]))
        elif line.startswith("## "):
            flush_list()
            flush_search_cards()
            blocks.append(_render_heading(2, line[3:]))
        elif line.startswith("- "):
            flush_search_cards()
            list_items.append(_inline(line[2:]))
        else:
            flush_list()
            flush_search_cards()
            blocks.append(f"<p>{_inline(line)}</p>")
    flush_list()
    flush_search_cards()
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
    image = _safe_image(meta.get("image"))
    return {
        "slug": slug,
        "title": title,
        "description": _clean(meta.get("description")),
        "image": image,
        "image_is_external": image.startswith("http://") or image.startswith("https://"),
        "image_alt": _clean(meta.get("image_alt")) or title,
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

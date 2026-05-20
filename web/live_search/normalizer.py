import re
from urllib.parse import urlencode


def normalize_text(value: str) -> str:
    text = str(value or "").lower()
    text = re.sub(r"[\u200b\ufeff]", "", text)
    text = re.sub(r"[\s\[\]\(\){}<>.,/|\\\-_:;\"'`~!?]", "", text)
    return text


_BRACKET_RE = re.compile(r"(\([^)]*\)|\[[^\]]*\])")
_VOLUME_MARKER_RE = re.compile(r"^(상|중|하|전|후|[0-9]+|[0-9]+권|[ivxlcdm]+)$", re.IGNORECASE)


def _strip_descriptive_bracket(match: re.Match) -> str:
    value = match.group(0)
    inner = value[1:-1].strip()
    compact = normalize_text(inner)
    if not compact or _VOLUME_MARKER_RE.match(compact):
        return value
    if re.search(r"[A-Za-z]", inner) or len(compact) >= 4:
        return " "
    return value


def normalize_title_for_group(value: str) -> str:
    text = str(value or "")
    text = _BRACKET_RE.sub(_strip_descriptive_bracket, text)
    left, separator, _right = text.partition(":")
    if not separator:
        left, separator, _right = text.partition("：")
    if not separator:
        left, separator, _right = text.partition(" - ")
    title = left if separator and len(normalize_text(left)) >= 3 else text
    return normalize_text(title) or normalize_text(value)


def normalize_author(value: str) -> str:
    text = str(value or "")
    text = re.split(r"[/,;|]", text, maxsplit=1)[0]
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"\[[^\]]*\]", "", text)
    text = re.sub(r"(지은이|지음|저자|저|글쓴이|글|옮긴이|옮김|역자|역)", "", text)
    normalized = normalize_text(text)
    author_aliases = {
        "andyweir": "앤디위어",
        "freidamcfadden": "프리다맥파든",
        "프라다맥파든": "프리다맥파든",
        "프리다맥파든김은영": "프리다맥파든",
        "프리다맥파든정미정": "프리다맥파든",
        "프리다맥파든황성연": "프리다맥파든",
    }
    return author_aliases.get(normalized, normalized)


def clean_author_display(value: str) -> str:
    text = str(value or "").strip()
    text = re.split(r"[/,;|]", text, maxsplit=1)[0]
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"\[[^\]]*\]", "", text)
    text = re.sub(r"(지은이|지음|저자|저|글쓴이|글|옮긴이|옮김|역자|역)", "", text)
    text = " ".join(text.split())
    if normalize_author(text) == "프리다맥파든":
        return "프리다 맥파든"
    return text


def _author_display_quality(value: str) -> int:
    text = str(value or "")
    score = 0
    if text:
        score += 10
    if "/" in text or "<" in text or ">" in text:
        score -= 4
    if any(token in text for token in ("지은이", "옮긴이", "저/", " 역", " 지음", " 옮김")):
        score -= 2
    if re.search(r"[A-Za-z]", text) and not re.search(r"[가-힣]", text):
        score -= 1
    return score


def result_group_key(item: dict) -> str:
    title = normalize_title_for_group(item.get("title"))
    author = normalize_author(item.get("author"))
    if title and author:
        return f"meta:{title}|{author}"
    isbn = normalize_text(item.get("isbn"))
    if isbn:
        return f"isbn:{isbn}"
    return "meta:{title}|{author}|{publisher}".format(
        title=title,
        author=author,
        publisher=normalize_text(item.get("publisher")),
    )


def platform_bucket(platform: str) -> str:
    if platform in {"Kyobo", "Kyobo_New"}:
        return "kyobo"
    if platform == "YES24":
        return "yes24"
    return "other"


def merge_live_results(results):
    grouped = {}
    for result in results:
        item = result.as_dict() if hasattr(result, "as_dict") else dict(result)
        title = (item.get("title") or "").strip()
        if not title:
            continue
        author_display = clean_author_display(item.get("author")) or item.get("author") or ""
        key = result_group_key(item)
        entry = grouped.get(key)
        if not entry:
            entry = {
                "book_id": None,
                "title": title,
                "author": author_display,
                "publisher": item.get("publisher") or "",
                "image_url": item.get("image_url") or "",
                "counts": {"kyobo": 0, "yes24": 0, "other": 0, "total": 0},
                "libraries": [],
                "_seen_library_codes": set(),
            }
            grouped[key] = entry

        if not entry.get("image_url") and item.get("image_url"):
            entry["image_url"] = item.get("image_url") or ""
        if item.get("author") and (
            not entry.get("author")
            or _author_display_quality(author_display) > _author_display_quality(entry.get("author"))
        ):
            entry["author"] = author_display
        if not entry.get("publisher") and item.get("publisher"):
            entry["publisher"] = item.get("publisher") or ""

        library_code = item.get("library_code") or item.get("library_name") or ""
        if library_code and library_code not in entry["_seen_library_codes"]:
            entry["_seen_library_codes"].add(library_code)
            bucket = platform_bucket(item.get("platform") or "")
            entry["counts"][bucket] += 1
            entry["counts"]["total"] += 1
            entry["libraries"].append(
                {
                    "code": item.get("library_code") or "",
                    "name": item.get("library_name") or "",
                    "short": item.get("library_short") or item.get("library_name") or "",
                    "platform_code": item.get("platform") or "",
                    "provider": item.get("provider") or "",
                    "service_type": item.get("service_type") or "",
                    "homepage_url": item.get("homepage_url") or "",
                    "detail_url": item.get("detail_url") or "",
                    **(item.get("identifiers") or {}),
                }
            )

    merged = []
    for entry in grouped.values():
        entry.pop("_seen_library_codes", None)
        params = {
            "title": entry.get("title") or "",
            "author": entry.get("author") or "",
            "publisher": entry.get("publisher") or "",
        }
        entry["live_detail_url"] = f"/live_book?{urlencode(params)}"
        merged.append(entry)
    merged.sort(key=lambda x: (-int(x["counts"].get("total") or 0), x.get("title") or ""))
    return merged

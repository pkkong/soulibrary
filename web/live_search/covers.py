import re
from typing import Optional


PLACEHOLDER_RE = re.compile(
    r"(no[-_]?image|no[-_]?book|default|blank|spacer|transparent|loading|ready\.gif)",
    re.IGNORECASE,
)
SMALL_HINT_RE = re.compile(
    r"(thumb|thumbnail|small|simg|_s\.|/s/|/small/|[?&](?:w|width|h|height)=(?:[1-9][0-9]|1[01][0-9])(?:&|$))",
    re.IGNORECASE,
)
LARGE_HINT_RE = re.compile(
    r"(covermsize|coverm|large|big|origin|original|[?&](?:w|width|h|height)=(?:2[4-9][0-9]|[3-9][0-9]{2,})(?:&|$))",
    re.IGNORECASE,
)
URL_SIZE_RE = re.compile(r"(?:^|[?&_/=-])(?:w|width|h|height)?(?:=|_)?([1-9][0-9]{2,3})(?:[&_.-/]|$)", re.IGNORECASE)

PLATFORM_SCORE = {
    "YES24": 24,
    "Bookers": 22,
    "SeoulLibrary": 21,
    "SeoulEducation": 21,
    "Sen": 21,
    "Kyobo_New": 18,
    "Kyobo": 17,
    "Bookcube": 14,
}


def clean_cover_url(value: str) -> str:
    url = str(value or "").strip()
    if not url or PLACEHOLDER_RE.search(url):
        return ""
    if url.startswith("//"):
        return "https:" + url
    if not (url.startswith("http://") or url.startswith("https://")):
        return ""
    return url


def _candidate_score(candidate: dict) -> int:
    url = clean_cover_url(candidate.get("url") or candidate.get("image_url"))
    if not url:
        return -1000

    score = 100
    platform = str(candidate.get("platform") or "")
    score += PLATFORM_SCORE.get(platform, 12)
    if url.startswith("https://"):
        score += 4
    if candidate.get("isbn"):
        score += 6
    if candidate.get("detail_url"):
        score += 3
    if candidate.get("content_id") or candidate.get("goods_id") or candidate.get("brcd"):
        score += 4

    hint = str(candidate.get("hint") or "")
    if "medium" in hint or "large" in hint:
        score += 18
    if "primary" in hint:
        score += 4

    if LARGE_HINT_RE.search(url):
        score += 16
    if SMALL_HINT_RE.search(url):
        score -= 10

    sizes = [int(value) for value in URL_SIZE_RE.findall(url) if value.isdigit()]
    if sizes:
        largest = max(sizes)
        if largest >= 500:
            score += 14
        elif largest >= 300:
            score += 8
        elif largest <= 160:
            score -= 8

    return score


def _as_candidate(value, base: Optional[dict] = None, hint: str = ""):
    if isinstance(value, dict):
        url = clean_cover_url(value.get("url") or value.get("image_url"))
        if not url:
            return None
        merged = {**(base or {}), **value, "url": url}
    else:
        url = clean_cover_url(value)
        if not url:
            return None
        merged = {**(base or {}), "url": url}
    if hint and not merged.get("hint"):
        merged["hint"] = hint
    merged["score"] = _candidate_score(merged)
    return merged


def cover_candidates_for_item(item: dict) -> list[dict]:
    identifiers = item.get("identifiers") or {}
    base = {
        "platform": item.get("platform") or item.get("platform_code") or "",
        "provider": item.get("provider") or "",
        "library_code": item.get("library_code") or item.get("code") or "",
        "isbn": item.get("isbn") or "",
        "detail_url": item.get("detail_url") or "",
        "content_id": identifiers.get("content_id") or item.get("content_id") or "",
        "goods_id": identifiers.get("goods_id") or item.get("goods_id") or "",
        "brcd": identifiers.get("brcd") or item.get("brcd") or "",
    }
    candidates = []
    for candidate in item.get("image_candidates") or []:
        parsed = _as_candidate(candidate, base)
        if parsed:
            candidates.append(parsed)
    primary = _as_candidate(item.get("image_url"), base, "primary")
    if primary:
        candidates.append(primary)
    return compact_cover_candidates(candidates)


def compact_cover_candidates(candidates: list[dict], limit: int = 8) -> list[dict]:
    by_url = {}
    for candidate in candidates or []:
        parsed = _as_candidate(candidate)
        if not parsed:
            continue
        url = parsed["url"]
        prev = by_url.get(url)
        if not prev or int(parsed.get("score") or 0) > int(prev.get("score") or 0):
            by_url[url] = parsed
    ranked = sorted(by_url.values(), key=lambda item: int(item.get("score") or 0), reverse=True)
    compacted = []
    for item in ranked[:limit]:
        compacted.append(
            {
                "url": item["url"],
                "platform": item.get("platform") or "",
                "provider": item.get("provider") or "",
                "library_code": item.get("library_code") or "",
                "hint": item.get("hint") or "",
                "score": int(item.get("score") or 0),
            }
        )
    return compacted


def best_cover_url(candidates: list[dict], fallback: str = "") -> str:
    ranked = compact_cover_candidates(candidates)
    if ranked:
        return ranked[0]["url"]
    return clean_cover_url(fallback)

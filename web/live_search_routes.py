import copy
import traceback
from urllib.parse import urlencode

from flask import Blueprint, jsonify, render_template, request

from live_search.normalizer import normalize_text
from live_search.service import get_cached_live_detail, live_search, set_cached_live_detail


live_search_bp = Blueprint("live_search", __name__)


def _counts_need_hydration(query: str, item: dict) -> bool:
    query_key = normalize_text(query)
    title_key = normalize_text(item.get("title"))
    return bool(query_key and title_key and query_key != title_key)


def _attach_summary_urls(payload: dict, query: str) -> dict:
    for item in payload.get("items") or []:
        if not isinstance(item, dict) or not item.get("title"):
            continue
        needs_hydration = _counts_need_hydration(query, item)
        item["counts_partial"] = needs_hydration
        if not needs_hydration:
            item.pop("summary_url", None)
            continue
        item.pop("summary_url", None)
        set_cached_live_detail(item.get("live_detail_key"), item)
    return payload


@live_search_bp.route("/api/live_search")
def api_live_search():
    query = (request.args.get("query") or "").strip()
    if not query:
        return jsonify({"total": 0, "items": [], "filters": {"providers": [], "libraries": []}})

    try:
        limit = int(request.args.get("limit", "20"))
    except ValueError:
        limit = 20
    try:
        offset = int(request.args.get("offset", "0"))
    except ValueError:
        offset = 0

    try:
        payload = live_search(
            query=query,
            field=(request.args.get("field") or "title_author").strip(),
            providers_raw=(request.args.get("providers") or "").strip(),
            libraries_raw=(request.args.get("libraries") or "").strip(),
            limit=limit,
            offset=offset,
            refine=(request.args.get("refine") or "").strip(),
        )
        payload = _attach_summary_urls(payload, query)
        return jsonify(payload)
    except Exception as exc:
        print(f"[live_search error] {exc}")
        print(traceback.format_exc())
        return jsonify({"error": "실시간 검색 처리 오류 발생", "total": 0, "items": []}), 502


def _match_score(target: dict, item: dict) -> int:
    target_title = normalize_text(target.get("title"))
    item_title = normalize_text(item.get("title"))
    target_author = normalize_text(target.get("author"))
    item_author = normalize_text(item.get("author"))
    target_publisher = normalize_text(target.get("publisher"))
    item_publisher = normalize_text(item.get("publisher"))

    score = 0
    if target_title and item_title:
        if target_title == item_title:
            score += 100
        elif target_title in item_title or item_title in target_title:
            score += 70
    if target_author and item_author:
        if target_author == item_author:
            score += 40
        elif target_author in item_author or item_author in target_author:
            score += 20
    if target_publisher and item_publisher:
        if target_publisher == item_publisher:
            score += 20
        elif target_publisher in item_publisher or item_publisher in target_publisher:
            score += 10
    return score


def _status_kind(lib: dict) -> str:
    platform = lib.get("platform_code") or ""
    code = lib.get("code") or ""
    if platform == "Kyobo_New":
        return "kyobo"
    if platform == "Kyobo" or code == "dobong":
        return "dobong"
    if platform == "YES24":
        return "yes24"
    if platform == "Bookcube":
        return "bookcube"
    if code == "gangnam" or platform == "Gangnam":
        return "gangnam"
    if code == "eunpyeong" or platform == "Eunpyeong":
        return "eunpyeong"
    if code == "seoul" or platform == "SeoulLibrary":
        return "seoul"
    if code in {"sen_owned", "sen_subs"} or platform == "SeoulEducation":
        return "sen"
    return ""


def _group_label(lib: dict) -> str:
    kind = lib.get("status_kind") or _status_kind(lib)
    if kind in {"kyobo", "dobong"}:
        return "교보"
    if kind == "yes24":
        return "YES24"
    return "기타"


GROUP_ORDER = {
    "교보": 0,
    "YES24": 1,
    "기타": 2,
}


def _decorate_live_book(book: dict | None):
    if not book:
        return None
    groups = []
    grouped = {}
    for lib in book.get("libraries") or []:
        lib["status_kind"] = _status_kind(lib)
        label = _group_label(lib)
        if label not in grouped:
            grouped[label] = {"label": label, "libraries": []}
            groups.append(grouped[label])
        grouped[label]["libraries"].append(lib)
    groups.sort(key=lambda group: GROUP_ORDER.get(group.get("label"), 99))
    book["library_groups"] = groups
    return book


def _library_count(book: dict | None) -> int:
    if not book:
        return 0
    try:
        return int((book.get("counts") or {}).get("total") or 0)
    except Exception:
        return len(book.get("libraries") or [])


def _find_complete_live_book(target: dict, fallback: dict | None = None):
    if not target.get("title"):
        return copy.deepcopy(fallback) if fallback else None
    payload = live_search(
        query=target["title"],
        field="title",
        providers_raw="",
        libraries_raw="",
        limit=100,
        offset=0,
    )
    items = payload.get("items") or []
    ranked = sorted(items, key=lambda item: _match_score(target, item), reverse=True)
    best = ranked[0] if ranked else None
    if not best or _match_score(target, best) < 70:
        return copy.deepcopy(fallback) if fallback else None
    if fallback and _library_count(fallback) > _library_count(best):
        return copy.deepcopy(fallback)
    return copy.deepcopy(best)


def _detail_hydrate_url(cache_key: str, target: dict, fallback: dict | None = None) -> str:
    params = {}
    if cache_key:
        params["key"] = cache_key
    title = (target.get("title") or "").strip() or ((fallback or {}).get("title") or "")
    author = (target.get("author") or "").strip() or ((fallback or {}).get("author") or "")
    publisher = (target.get("publisher") or "").strip() or ((fallback or {}).get("publisher") or "")
    if title:
        params["title"] = title
    if author:
        params["author"] = author
    if publisher:
        params["publisher"] = publisher
    return f"/api/live_book_detail?{urlencode(params)}" if params.get("title") else ""


def _placeholder_live_book(target: dict) -> dict | None:
    title = (target.get("title") or "").strip()
    if not title:
        return None
    return {
        "title": title,
        "author": (target.get("author") or "").strip(),
        "publisher": (target.get("publisher") or "").strip(),
        "image_url": "",
        "counts": {"kyobo": 0, "yes24": 0, "other": 0, "total": 0},
        "libraries": [],
        "counts_partial": True,
    }


@live_search_bp.route("/api/live_book_summary")
def api_live_book_summary():
    cache_key = (request.args.get("key") or "").strip()
    fallback = get_cached_live_detail(cache_key)
    target = {
        "title": (request.args.get("title") or "").strip() or ((fallback or {}).get("title") or ""),
        "author": (request.args.get("author") or "").strip() or ((fallback or {}).get("author") or ""),
        "publisher": (request.args.get("publisher") or "").strip() or ((fallback or {}).get("publisher") or ""),
    }
    if not target["title"]:
        return jsonify({"error": "도서 정보가 부족합니다."}), 400

    try:
        book = _find_complete_live_book(target, fallback)
        if not book:
            return jsonify({"error": "실시간 상세 정보를 찾지 못했습니다."}), 404
        return jsonify(
            {
                "title": book.get("title") or "",
                "author": book.get("author") or "",
                "publisher": book.get("publisher") or "",
                "counts": book.get("counts") or {},
                "live_detail_url": book.get("live_detail_url") or "",
                "live_detail_key": book.get("live_detail_key") or "",
            }
        )
    except Exception as exc:
        print(f"[live_book_summary error] {exc}")
        print(traceback.format_exc())
        return jsonify({"error": "실시간 요약 조회 중 오류가 발생했습니다."}), 502


@live_search_bp.route("/api/live_book_detail")
def api_live_book_detail():
    cache_key = (request.args.get("key") or "").strip()
    fallback = get_cached_live_detail(cache_key)
    target = {
        "title": (request.args.get("title") or "").strip() or ((fallback or {}).get("title") or ""),
        "author": (request.args.get("author") or "").strip() or ((fallback or {}).get("author") or ""),
        "publisher": (request.args.get("publisher") or "").strip() or ((fallback or {}).get("publisher") or ""),
    }
    if not target["title"]:
        return jsonify({"error": "도서 정보가 부족합니다."}), 400

    try:
        book = _find_complete_live_book(target, fallback)
        if not book:
            return jsonify({"error": "실시간 상세 정보를 찾지 못했습니다."}), 404
        book["counts_partial"] = False
        if cache_key:
            set_cached_live_detail(cache_key, book)
        decorated = _decorate_live_book(book)
        return jsonify(
            {
                "book": {
                    "title": decorated.get("title") or "",
                    "author": decorated.get("author") or "",
                    "publisher": decorated.get("publisher") or "",
                    "image_url": decorated.get("image_url") or "",
                    "counts": decorated.get("counts") or {},
                    "libraries": decorated.get("libraries") or [],
                    "live_detail_key": decorated.get("live_detail_key") or cache_key,
                    "live_detail_url": decorated.get("live_detail_url") or "",
                },
                "groups_html": render_template("partials/live_library_groups.html", book=decorated),
                "counts": decorated.get("counts") or {},
                "live_detail_key": decorated.get("live_detail_key") or cache_key,
            }
        )
    except Exception as exc:
        print(f"[live_book_detail error] {exc}")
        print(traceback.format_exc())
        return jsonify({"error": "실시간 상세 조회 중 오류가 발생했습니다."}), 502


@live_search_bp.route("/live_book")
def live_book_page():
    cache_key = (request.args.get("key") or "").strip()
    target = {
        "title": (request.args.get("title") or "").strip(),
        "author": (request.args.get("author") or "").strip(),
        "publisher": (request.args.get("publisher") or "").strip(),
    }

    cached_book = get_cached_live_detail(cache_key)
    if cached_book:
        detail_hydrate_url = ""
        if cached_book.get("counts_partial"):
            detail_hydrate_url = _detail_hydrate_url(cache_key, target, cached_book)
        return render_template(
            "live_book.html",
            book=_decorate_live_book(cached_book),
            error=None,
            detail_hydrate_url=detail_hydrate_url,
            show_topbar=False,
            topbar_desc="",
            active_tab="search",
        )

    if not target["title"]:
        return render_template(
            "live_book.html",
            book=None,
            error="도서 정보가 부족합니다. 다시 검색해주세요.",
            detail_hydrate_url="",
            show_topbar=False,
            topbar_desc="",
            active_tab="search",
        ), 400

    placeholder = _placeholder_live_book(target)
    return render_template(
        "live_book.html",
        book=_decorate_live_book(placeholder),
        error=None,
        detail_hydrate_url=_detail_hydrate_url("", target, placeholder),
        show_topbar=False,
        topbar_desc="",
        active_tab="search",
    )

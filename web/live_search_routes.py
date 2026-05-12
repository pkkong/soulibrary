import traceback

from flask import Blueprint, jsonify, render_template, request

from live_search.normalizer import normalize_text
from live_search.service import live_search


live_search_bp = Blueprint("live_search", __name__)


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


@live_search_bp.route("/live_book")
def live_book_page():
    target = {
        "title": (request.args.get("title") or "").strip(),
        "author": (request.args.get("author") or "").strip(),
        "publisher": (request.args.get("publisher") or "").strip(),
    }
    if not target["title"]:
        return render_template(
            "live_book.html",
            book=None,
            error="도서 정보가 부족합니다. 다시 검색해주세요.",
            show_topbar=False,
            topbar_desc="",
            active_tab="search",
        ), 400

    try:
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
            best = None
        best = _decorate_live_book(best)

        return render_template(
            "live_book.html",
            book=best,
            error=None if best else "실시간 상세 정보를 찾지 못했습니다. 다시 검색해주세요.",
            show_topbar=False,
            topbar_desc="",
            active_tab="search",
        ), 200 if best else 404
    except Exception as exc:
        print(f"[live_book error] {exc}")
        print(traceback.format_exc())
        return render_template(
            "live_book.html",
            book=None,
            error="실시간 상세 조회 중 오류가 발생했습니다.",
            show_topbar=False,
            topbar_desc="",
            active_tab="search",
        ), 502

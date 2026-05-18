import os
import time
import traceback
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from flask import Blueprint, jsonify, request

from adapters.status_parsers import (
    parse_bookcube_detail_status,
    parse_bookcube_status,
    parse_dobong_status,
    parse_eunpyeong_html_status,
    parse_eunpyeong_status,
    parse_gangnam_detail_status,
    parse_gangnam_status,
    parse_kyobo_status,
    parse_seoul_status,
    parse_sen_status,
    parse_sen_xml_status,
    parse_yes24_status,
)
from config import LIBRARIES
from utils.http import DEFAULT_HEADERS, DOBONG_HEADERS, get_status_session, http_fallback

status_api_bp = Blueprint("status_api", __name__)

STATUS_TTL_SEC = int(os.environ.get("KYOBO_STATUS_TTL", "120"))
STATUS_CACHE = {}


def _kyobo_base_url(library_code: str) -> str:
    info = LIBRARIES.get(library_code)
    if not info:
        return ""
    raw_url = info.get("homepage_url") or info.get("url_prefix") or info.get("total_count_url")
    if not raw_url:
        return ""
    parsed = urlparse(raw_url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def build_kyobo_detail_url(library_code: str, params: dict) -> str:
    base_url = _kyobo_base_url(library_code)
    if not base_url:
        return ""
    info = LIBRARIES.get(library_code) or {}
    content_path = info.get("content_path") or "/elibrary-front/content/contentView.ink"
    if not content_path.startswith("/"):
        content_path = "/" + content_path
    return f"{base_url}{content_path}?{urlencode(params)}"


def yes24_base_url(library_code: str) -> str:
    info = LIBRARIES.get(library_code)
    if not info:
        return ""
    raw_url = info.get("homepage_url") or info.get("total_count_url")
    if not raw_url:
        return ""
    parsed = urlparse(raw_url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def _yes24_list_url(library_code: str) -> str:
    info = LIBRARIES.get(library_code) or {}
    url = info.get("total_count_url")
    if url:
        return url.split("#", 1)[0]
    base_url = yes24_base_url(library_code)
    if not base_url:
        return ""
    return f"{base_url}/ebook/?mode=total&sort=pubdt&cate_id=&page_num=1"


def bookcube_base_url(library_code: str) -> str:
    info = LIBRARIES.get(library_code)
    if not info:
        return ""
    raw_url = info.get("homepage_url") or info.get("total_count_url")
    if not raw_url:
        return ""
    parsed = urlparse(raw_url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def _bookcube_list_url(library_code: str) -> str:
    info = LIBRARIES.get(library_code) or {}
    url = info.get("total_count_url")
    if url:
        return url.split("#", 1)[0]
    base_url = bookcube_base_url(library_code)
    if not base_url:
        return ""
    return (
        f"{base_url}/FxLibrary/product/list/?itemdv=1&sort=3&page=1&itemCount=20&pageCount=10"
        "&category=&middlecategory=&cateopt=total&group_num=recommand&catenavi=main&category_type=book"
        "&searchoption=&keyoption=&keyoption2=&keyword=&listfilter=all_list&selectview=list_on"
        "&searchType=&name=&publisher=&author=&terminal="
    )


def _bookcube_page_size(list_url: str) -> int:
    parsed = urlparse(list_url)
    qs = parse_qs(parsed.query)
    value = (qs.get("itemCount") or [""])[0]
    try:
        size = int(value)
        return max(1, size)
    except Exception as e:
        print(f"[status error] {e}")
        print(traceback.format_exc())
        return 20


def _bookcube_page_url(list_url: str, page: int) -> str:
    parsed = urlparse(list_url)
    qs = parse_qs(parsed.query)
    qs["page"] = [str(page)]
    new_query = urlencode(qs, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def _bookcube_status_list_url(list_url: str) -> str:
    if not list_url:
        return list_url
    parsed = urlparse(list_url)
    qs = parse_qs(parsed.query)
    qs["itemCount"] = ["200"]
    new_query = urlencode(qs, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def _bookcube_search_list_url(list_url: str, keyword: str, keyoption2: str = "1") -> str:
    if not list_url or not keyword:
        return list_url
    parsed = urlparse(list_url)
    qs = parse_qs(parsed.query)
    qs["page"] = ["1"]
    qs["itemCount"] = ["200"]
    qs["searchType"] = ["search"]
    qs["searchoption"] = ["1"]
    qs["keyoption2"] = [keyoption2]
    qs["keyword"] = [keyword]
    new_query = urlencode(qs, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def _gangnam_list_url(library_code: str) -> str:
    info = LIBRARIES.get(library_code) or {}
    url = info.get("total_count_url")
    if url:
        return url
    base_url = info.get("homepage_url")
    if not base_url:
        return ""
    return f"{base_url.rstrip('/')}/elibbook/book_category.asp?mode=&page_num=1&branch=99&supply_code=&strSort=p&ldav="


def _gangnam_page_url(list_url: str, page: int) -> str:
    parsed = urlparse(list_url)
    qs = parse_qs(parsed.query)
    qs["page_num"] = [str(page)]
    new_query = urlencode(qs, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


@status_api_bp.route("/api/kyobo_status")
def api_kyobo_status():
    library_code = (request.args.get("library_code") or "").strip()
    brcd = (request.args.get("brcd") or "").strip()
    ctts_dvsn_code = (request.args.get("ctts_dvsn_code") or "").strip()
    ctgr_id = (request.args.get("ctgr_id") or "").strip()
    sntn_auth_code = (request.args.get("sntn_auth_code") or "").strip()
    if not library_code or not brcd:
        return jsonify({"error": "missing_library_code_or_brcd"}), 400

    cache_key = f"kyobo:{library_code}:{brcd}:{ctts_dvsn_code}:{ctgr_id}:{sntn_auth_code}"
    cached = STATUS_CACHE.get(cache_key)
    if cached and (time.time() - cached["time"]) < STATUS_TTL_SEC:
        return jsonify(cached["payload"])

    params = {"cttsDvsnCode": ctts_dvsn_code, "brcd": brcd, "ctgrId": ctgr_id}
    if sntn_auth_code:
        params["sntnAuthCode"] = sntn_auth_code
    detail_url = build_kyobo_detail_url(library_code, params)
    if not detail_url:
        return jsonify({"error": "invalid_library"}), 400

    try:
        session = get_status_session()
        res = session.get(detail_url, timeout=7, headers=DEFAULT_HEADERS, verify=False)
        res.raise_for_status()
        status = parse_kyobo_status(res.text)
        if not status:
            raise RuntimeError("status_missing")
        payload = {"library_code": library_code, "brcd": brcd, "status": status}
        STATUS_CACHE[cache_key] = {"time": time.time(), "payload": payload}
        return jsonify(payload)
    except Exception as e:
        print(f"[status error] {e}")
        print(traceback.format_exc())
        return jsonify({"library_code": library_code, "brcd": brcd, "status": None}), 502


@status_api_bp.route("/api/yes24_status")
def api_yes24_status():
    library_code = (request.args.get("library_code") or "").strip()
    goods_id = (request.args.get("goods_id") or "").strip()
    if not library_code or not goods_id:
        return jsonify({"error": "missing_library_code_or_goods_id"}), 400

    cache_key = f"yes24:{library_code}:{goods_id}"
    cached = STATUS_CACHE.get(cache_key)
    if cached and (time.time() - cached["time"]) < STATUS_TTL_SEC:
        return jsonify(cached["payload"])

    list_url = _yes24_list_url(library_code)
    if not list_url:
        return jsonify({"error": "invalid_library"}), 400
    detail_url = f"{yes24_base_url(library_code)}/ebook/detail/?goods_id={goods_id}"
    fallback_url = list_url

    status = None
    try:
        session = get_status_session()
        res = session.get(detail_url, timeout=7, headers=DEFAULT_HEADERS, verify=False)
        res.raise_for_status()
        status = parse_yes24_status(res.text, goods_id)
    except Exception as e:
        print(f"[status error] {e}")
        print(traceback.format_exc())

    if not status:
        try:
            res = get_status_session().get(fallback_url, timeout=7, headers=DEFAULT_HEADERS, verify=False)
            res.raise_for_status()
            status = parse_yes24_status(res.text, goods_id)
        except Exception as e:
            print(f"[status error] {e}")
            print(traceback.format_exc())

    if not status:
        return jsonify({"library_code": library_code, "goods_id": goods_id, "status": None}), 502

    payload = {"library_code": library_code, "goods_id": goods_id, "status": status}
    STATUS_CACHE[cache_key] = {"time": time.time(), "payload": payload}
    return jsonify(payload)


@status_api_bp.route("/api/bookcube_status")
def api_bookcube_status():
    library_code = (request.args.get("library_code") or "").strip()
    content_id = (request.args.get("content_id") or "").strip()
    debug = request.args.get("debug") == "1"
    if not library_code or not content_id:
        return jsonify({"error": "missing_library_code_or_content_id"}), 400

    cache_key = f"bookcube:{library_code}:{content_id}"
    cached = STATUS_CACHE.get(cache_key)
    if cached and (time.time() - cached["time"]) < STATUS_TTL_SEC:
        return jsonify(cached["payload"])

    base_url = bookcube_base_url(library_code)
    if not base_url:
        return jsonify({"error": "invalid_library"}), 400

    detail_url = f"{base_url}/FxLibrary/product/view/?num={content_id}&category=&category_type=book"
    list_url = _bookcube_status_list_url(_bookcube_list_url(library_code))
    attempted = [detail_url]
    status = None
    source = None
    session = get_status_session()

    try:
        res = session.get(detail_url, timeout=7, headers=DEFAULT_HEADERS, verify=False)
        res.raise_for_status()
        status = parse_bookcube_detail_status(res.text)
        if status:
            source = "detail"
    except Exception as e:
        print(f"[status error] {e}")
        print(traceback.format_exc())

    if not status and list_url:
        attempted.append(list_url)
        try:
            res = session.get(list_url, timeout=7, headers=DEFAULT_HEADERS, verify=False)
            res.raise_for_status()
            status = parse_bookcube_status(res.text, content_id)
            if status:
                source = "list"
        except Exception as e:
            print(f"[status error] {e}")
            print(traceback.format_exc())

    if not status:
        payload = {"library_code": library_code, "content_id": content_id, "status": None}
        if debug:
            payload.update({"attempted": attempted, "source": source, "content_id": content_id})
        return jsonify(payload), 502

    payload = {"library_code": library_code, "content_id": content_id, "status": status}
    if debug:
        payload.update({"attempted": attempted, "source": source})
    STATUS_CACHE[cache_key] = {"time": time.time(), "payload": payload}
    return jsonify(payload)


@status_api_bp.route("/api/gangnam_status")
def api_gangnam_status():
    library_code = (request.args.get("library_code") or "").strip() or "gangnam"
    content_id = (request.args.get("content_id") or "").strip()
    title = (request.args.get("title") or "").strip()
    debug = request.args.get("debug") == "1"
    if not content_id:
        return jsonify({"error": "missing_content_id"}), 400

    cache_key = f"gangnam:{library_code}:{content_id}"
    cached = STATUS_CACHE.get(cache_key)
    if cached and (time.time() - cached["time"]) < STATUS_TTL_SEC:
        return jsonify(cached["payload"])

    attempted = []
    status = None
    try:
        session = get_status_session()
        base_url = bookcube_base_url(library_code)
        headers = dict(DEFAULT_HEADERS)
        if base_url:
            headers["Referer"] = f"{base_url}/elibbook/book_info.asp"
        detail_url = f"{base_url}/elibbook/book_detail.asp?book_num={content_id}"
        attempted.append(detail_url)
        res = session.get(detail_url, timeout=7, headers=headers, verify=False)
        res.raise_for_status()
        status = parse_gangnam_detail_status(res.content.decode("euc-kr", "replace"))
    except Exception as e:
        print(f"[status error] {e}")
        print(traceback.format_exc())

    if not status:
        try:
            list_url = _gangnam_list_url(library_code)
            if list_url:
                attempted.append(list_url)
                res = get_status_session().get(list_url, timeout=7, headers=DEFAULT_HEADERS, verify=False)
                res.raise_for_status()
                status = parse_gangnam_status(res.content.decode("euc-kr", "replace"), content_id)
        except Exception as e:
            print(f"[status error] {e}")
            print(traceback.format_exc())

    if not status and title:
        try:
            base_url = bookcube_base_url(library_code)
            search_url = f"{base_url}/elibbook/book_info.asp?{urlencode({'search': 'title', 'strSearch': title}, encoding='euc-kr')}"
            attempted.append(search_url)
            headers = dict(DEFAULT_HEADERS)
            headers["Referer"] = base_url
            res = get_status_session().get(search_url, timeout=7, headers=headers, verify=False)
            res.raise_for_status()
            status = parse_gangnam_status(res.content.decode("euc-kr", "replace"), content_id)
        except Exception as e:
            print(f"[status error] {e}")
            print(traceback.format_exc())

    if not status:
        payload = {"error": "parse_failed"}
        if debug:
            payload.update({"library_code": library_code, "content_id": content_id, "attempted": attempted})
        return jsonify(payload), 502
    payload = {"library_code": library_code, "content_id": content_id, "status": status}
    STATUS_CACHE[cache_key] = {"time": time.time(), "payload": payload}
    return jsonify(payload)


@status_api_bp.route("/api/seoul_status")
def api_seoul_status():
    content_id = (request.args.get("content_id") or "").strip()
    if not content_id:
        return jsonify({"error": "missing_content_id"}), 400

    cache_key = f"seoul:{content_id}"
    cached = STATUS_CACHE.get(cache_key)
    if cached and (time.time() - cached["time"]) < STATUS_TTL_SEC:
        return jsonify(cached["payload"])

    try:
        session = get_status_session()
        url = f"https://elib.seoul.go.kr/api/contents/{content_id}"
        res = session.get(url, timeout=15, headers=DEFAULT_HEADERS, verify=False)
        res.raise_for_status()
        data = res.json()
        status = parse_seoul_status(data)
        if not status:
            raise RuntimeError("status_missing")
        payload = {"content_id": content_id, "status": status}
        STATUS_CACHE[cache_key] = {"time": time.time(), "payload": payload}
        return jsonify(payload)
    except Exception as e:
        print(f"[status error] {e}")
        print(traceback.format_exc())
        return jsonify({"content_id": content_id, "status": None}), 502


@status_api_bp.route("/api/sen_status")
def api_sen_status():
    library_code = (request.args.get("library_code") or "").strip()
    content_id = (request.args.get("content_id") or "").strip()
    if not library_code:
        return jsonify({"error": "missing_library_code"}), 400
    if library_code == "sen_subs":
        status = {"loaned": 0, "total": 1, "reserved": 0}
        return jsonify({"library_code": library_code, "content_id": content_id, "status": status})
    if not content_id:
        return jsonify({"error": "missing_content_id"}), 400

    cache_key = f"sen:{library_code}:{content_id}"
    cached = STATUS_CACHE.get(cache_key)
    if cached and (time.time() - cached["time"]) < STATUS_TTL_SEC:
        return jsonify(cached["payload"])

    try:
        session = get_status_session()
        url = f"https://e-lib.sen.go.kr/api/contents/{content_id}/TY01"
        res = session.get(url, timeout=15, headers=DEFAULT_HEADERS, verify=False)
        res.raise_for_status()
        status = None
        data = None
        content_type = (res.headers.get("Content-Type", "") or "").lower()
        if "json" in content_type and not res.text.lstrip().startswith("<"):
            try:
                data = res.json()
            except Exception as e:
                print(f"[status error] {e}")
                print(traceback.format_exc())
                data = None
        if data is not None:
            status = parse_sen_status(data)
        if not status:
            status = parse_sen_xml_status(res.text)
        if not status:
            raise RuntimeError("status_missing")
        payload = {"library_code": library_code, "content_id": content_id, "status": status}
        STATUS_CACHE[cache_key] = {"time": time.time(), "payload": payload}
        return jsonify(payload)
    except Exception as e:
        print(f"[status error] {e}")
        print(traceback.format_exc())
        return jsonify({"library_code": library_code, "content_id": content_id, "status": None}), 502


@status_api_bp.route("/api/eunpyeong_status")
def api_eunpyeong_status():
    content_id = (request.args.get("content_id") or "").strip()
    content_type = (request.args.get("content_type") or request.args.get("contentType") or "EB").strip() or "EB"
    debug = request.args.get("debug") == "1"
    if not content_id:
        return jsonify({"error": "missing_content_id"}), 400

    cache_key = f"eunpyeong:{content_type}:{content_id}"
    cached = STATUS_CACHE.get(cache_key)
    if cached and (time.time() - cached["time"]) < STATUS_TTL_SEC:
        return jsonify(cached["payload"])

    attempted = []
    try:
        session = get_status_session()
        url = "https://epbook.eplib.or.kr/api/service/content/detail"
        params = {"contentType": content_type, "id": content_id, "libCode": "111042"}
        attempted.append(url)
        res = session.get(url, params=params, timeout=15, headers=DEFAULT_HEADERS, verify=False)
        res.raise_for_status()
        status = None
        data = None
        try:
            raw_data = res.json()
            data = raw_data.get("data") if isinstance(raw_data, dict) else raw_data
        except Exception as e:
            print(f"[status error] {e}")
            print(traceback.format_exc())
            data = None
        if data is not None:
            status = parse_eunpyeong_status(data)
        if not status:
            status = parse_eunpyeong_html_status(res.text)
        if not status:
            raise RuntimeError("status_missing")
        payload = {"content_id": content_id, "status": status}
        STATUS_CACHE[cache_key] = {"time": time.time(), "payload": payload}
        return jsonify(payload)
    except Exception as e:
        print(f"[status error] {e}")
        print(traceback.format_exc())
        payload = {"content_id": content_id, "status": None}
        if debug:
            payload.update({"attempted": attempted})
        return jsonify(payload), 502


@status_api_bp.route("/api/dobong_status")
def api_dobong_status():
    brcd = (request.args.get("brcd") or "").strip()
    requested_product_cd = (request.args.get("product_cd") or "").strip()
    category_id = (request.args.get("category_id") or "").strip()
    debug = request.args.get("debug") == "1"
    if not brcd:
        return jsonify({"error": "missing_brcd"}), 400

    product_candidates = [requested_product_cd] if requested_product_cd else ["001", "002"]
    cache_key = f"dobong:{brcd}:{','.join(product_candidates)}:{category_id}"
    cached = STATUS_CACHE.get(cache_key)
    if cached and (time.time() - cached["time"]) < STATUS_TTL_SEC:
        return jsonify(cached["payload"])

    attempted = []
    session = get_status_session()
    url = "https://elib.dobong.kr/Kyobo_T3_Mobile/Phone/Main/Ebook_Detail.asp"
    for product_cd in product_candidates:
        params = {
            "type": "EBOOK",
            "barcode": brcd,
            "classCode": "",
            "keyWord": "",
            "product_cd": product_cd,
            "kiduse_yn": "N",
            "borrowRadio": "",
            "sortType": "1",
        }
        pc_params = {"barcode": brcd, "product_cd": product_cd}
        if category_id:
            pc_params["category_id"] = category_id
        pc_paths = [
            "https://elib.dobong.kr/Kyobo_T3/Content/audio/audio_View.asp",
            "https://elib.dobong.kr/Kyobo_T3/Content/ebook/ebook_View.asp",
        ]
        if product_cd != "002":
            pc_paths.reverse()
        candidates = [(url, params), *[(pc_url, pc_params) for pc_url in pc_paths]]
        for candidate_url, candidate_params in candidates:
            attempted.append(f"{candidate_url}?{urlencode(candidate_params)}")
            try:
                res = session.get(candidate_url, params=candidate_params, timeout=15, headers=DOBONG_HEADERS, verify=False)
                res.raise_for_status()
                status = parse_dobong_status(res.text)
                if not status:
                    continue
                payload = {"brcd": brcd, "product_cd": product_cd, "status": status}
                STATUS_CACHE[cache_key] = {"time": time.time(), "payload": payload}
                return jsonify(payload)
            except Exception as e:
                print(f"[status error] {e}")
                print(traceback.format_exc())

    payload = {"brcd": brcd, "status": None}
    if debug:
        payload.update({"attempted": attempted})
    return jsonify(payload), 502

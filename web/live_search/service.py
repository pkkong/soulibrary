import os
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed
from urllib.parse import urlencode

from config import LIBRARIES, LIBRARY_SHORT
from live_search.cache import TTLMemoryCache
from live_search.connectors.bookers import BookersConnector
from live_search.connectors.bookcube import BookcubeConnector
from live_search.connectors.kyobo import KyoboNewConnector
from live_search.connectors.legacy import DobongKyoboConnector, EunpyeongConnector, GangnamConnector
from live_search.connectors.public_api import SenConnector, SeoulLibraryConnector
from live_search.connectors.yes24 import Yes24Connector
from live_search.normalizer import merge_live_results, normalize_text


LIVE_SEARCH_TTL_SEC = int(os.environ.get("LIVE_SEARCH_TTL_SEC", "600"))
LIVE_SEARCH_CACHE_SIZE = int(os.environ.get("LIVE_SEARCH_CACHE_SIZE", "256"))
LIVE_SEARCH_LIBRARY_TIMEOUT = float(os.environ.get("LIVE_SEARCH_LIBRARY_TIMEOUT", "4.5"))
LIVE_SEARCH_TOTAL_TIMEOUT = float(os.environ.get("LIVE_SEARCH_TOTAL_TIMEOUT", "5.8"))
LIVE_SEARCH_MAX_WORKERS = int(os.environ.get("LIVE_SEARCH_MAX_WORKERS", "40"))
LIVE_SEARCH_PER_LIBRARY_LIMIT = int(os.environ.get("LIVE_SEARCH_PER_LIBRARY_LIMIT", "10"))
LIVE_DETAIL_CACHE_SIZE = int(os.environ.get("LIVE_DETAIL_CACHE_SIZE", "1024"))

_CACHE = TTLMemoryCache(ttl_seconds=LIVE_SEARCH_TTL_SEC, max_items=LIVE_SEARCH_CACHE_SIZE)
_DETAIL_CACHE = TTLMemoryCache(ttl_seconds=LIVE_SEARCH_TTL_SEC, max_items=LIVE_DETAIL_CACHE_SIZE)

CONNECTOR_FACTORIES = {
    "Kyobo_New": KyoboNewConnector,
    "Kyobo": DobongKyoboConnector,
    "YES24": Yes24Connector,
    "Bookcube": BookcubeConnector,
    "Bookers": BookersConnector,
    "Mixed": None,
    "Unknown": None,
}

SPECIAL_CONNECTOR_FACTORIES = {
    "seoul": SeoulLibraryConnector,
    "sen_owned": SenConnector,
    "sen_subs": SenConnector,
    "gangnam": GangnamConnector,
    "eunpyeong": EunpyeongConnector,
}

PROVIDER_FILTER_ORDER = {
    "교보": 0,
    "YES24": 1,
    "기타": 2,
    "기타 도서관": 2,
}


def _split_csv(value: str) -> list[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def _cache_key(query: str, field: str, providers: list[str], libraries: list[str]) -> tuple:
    return (
        (query or "").strip().lower(),
        field or "title_author",
        tuple(sorted(providers or [])),
        tuple(sorted(libraries or [])),
    )


def _selected_library_codes(library_labels: list[str]) -> list[str]:
    selected = set(library_labels or [])
    codes = []
    for code, cfg in LIBRARIES.items():
        short = LIBRARY_SHORT.get(code, cfg.get("library_name") or code)
        if selected and short not in selected and code not in selected:
            continue
        codes.append(code)
    return codes


def _normalize_label(value: str) -> str:
    return str(value or "").strip().lower()


def _provider_display_label(value: str) -> str:
    raw = str(value or "").strip()
    key = raw.replace(" ", "").lower()
    if key in {"kyobo", "kyobo_new"} or "교보" in raw:
        return "교보"
    if "yes24" in key or "예스" in raw:
        return "YES24"
    if "bookcube" in key or "북큐브" in raw:
        return "기타"
    if key in {"al", "aladin"} or "알라딘" in raw:
        return "알라딘"
    if "opms" in key or "오피엠에스" in raw:
        return "OPMS"
    if "서울시교육청" in raw or "seouleducation" in key:
        return "서울교육청"
    if "서울도서관" in raw or "seoullibrary" in key:
        return "서울도서관"
    if "기타도서관" in key or key in {"other", "기타"}:
        return "기타"
    return raw


def _provider_filter_label(item: dict) -> str:
    platform = item.get("platform") or item.get("platform_code") or ""
    code = item.get("library_code") or item.get("code") or ""
    if platform in {"Kyobo", "Kyobo_New"} or code == "dobong":
        return "교보"
    if platform == "YES24":
        return "YES24"
    return "기타"


def _provider_allows_result(provider_labels: list[str], result) -> bool:
    if not provider_labels:
        return True
    wanted = {_normalize_label(_provider_display_label(label)) for label in provider_labels}
    item = result.as_dict() if hasattr(result, "as_dict") else dict(result)
    candidates = {
        _normalize_label(_provider_filter_label(item)),
        _normalize_label(_provider_display_label(item.get("platform"))),
    }
    return bool(wanted.intersection(candidates))


def _item_matches_refine(item: dict, refine: str) -> bool:
    tokens = [normalize_text(part) for part in str(refine or "").split() if normalize_text(part)]
    if not tokens:
        return True
    haystack = normalize_text(
        " ".join(
            [
                item.get("title") or "",
                item.get("author") or "",
                item.get("publisher") or "",
            ]
        )
    )
    return all(token in haystack for token in tokens)


def _detail_cache_key(item: dict) -> str:
    libraries = []
    for lib in item.get("libraries") or []:
        identifiers = {
            key: value
            for key, value in lib.items()
            if key in {
                "code",
                "platform_code",
                "detail_url",
                "brcd",
                "goods_id",
                "content_id",
                "ctts_dvsn_code",
                "ctgr_id",
                "sntn_auth_code",
                "product_cd",
                "category_id",
            }
            and value
        }
        libraries.append(identifiers)
    signature = {
        "title": item.get("title") or "",
        "author": item.get("author") or "",
        "publisher": item.get("publisher") or "",
        "libraries": sorted(libraries, key=lambda lib: json.dumps(lib, ensure_ascii=False, sort_keys=True)),
    }
    raw = json.dumps(signature, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def _attach_live_detail_urls(items: list[dict]) -> None:
    for item in items:
        if not isinstance(item, dict) or not (item.get("title") or "").strip():
            continue
        key = _detail_cache_key(item)
        params = {"key": key, "title": item.get("title") or ""}
        if item.get("author"):
            params["author"] = item.get("author") or ""
        if item.get("publisher"):
            params["publisher"] = item.get("publisher") or ""
        item["live_detail_key"] = key
        item["live_detail_url"] = f"/live_book?{urlencode(params)}"
        _DETAIL_CACHE.set(key, item)


def get_cached_live_detail(key: str):
    key = (key or "").strip()
    if not key:
        return None
    return _DETAIL_CACHE.get(key)


def set_cached_live_detail(key: str, item: dict) -> None:
    key = (key or "").strip()
    if key and item:
        _DETAIL_CACHE.set(key, item)


def _filters_from_items(items: list[dict]) -> dict:
    providers_filter = sorted(
        {
            _provider_filter_label(lib)
            for item in items
            for lib in item.get("libraries", [])
        },
        key=lambda label: (PROVIDER_FILTER_ORDER.get(label, 99), label),
    )
    libraries_filter = sorted(
        {
            lib.get("short") or lib.get("name")
            for item in items
            for lib in item.get("libraries", [])
            if lib.get("short") or lib.get("name")
        }
    )
    return {"providers": providers_filter, "libraries": libraries_filter}


def _slice_response(payload: dict, refine: str, limit: int, offset: int, cache_hit: bool) -> dict:
    base_items = payload.get("items") or []
    items = [item for item in base_items if _item_matches_refine(item, refine)]
    _attach_live_detail_urls(items)
    return {
        **payload,
        "total": len(items),
        "items": items[offset: offset + limit],
        "filters": _filters_from_items(items),
        "meta": {**payload.get("meta", {}), "cache_hit": cache_hit, "refine": bool((refine or "").strip())},
    }


def _connector_for_library(code: str, cfg: dict):
    special_factory = SPECIAL_CONNECTOR_FACTORIES.get(code)
    if special_factory:
        return special_factory()
    factory = CONNECTOR_FACTORIES.get(cfg.get("platform"))
    if not factory:
        return None
    return factory()


def _search_libraries(query: str, field: str, library_codes: list[str], provider_labels: list[str]) -> tuple[list, list[dict]]:
    if not library_codes:
        return [], []

    results = []
    errors = []
    tasks = []
    for code in library_codes:
        cfg = dict(LIBRARIES[code])
        cfg["short_name"] = LIBRARY_SHORT.get(code, cfg.get("library_name") or code)
        connector = _connector_for_library(code, cfg)
        if not connector:
            continue
        tasks.append((code, cfg, connector))

    max_workers = max(1, min(LIVE_SEARCH_MAX_WORKERS, len(tasks)))
    started = time.time()

    executor = ThreadPoolExecutor(max_workers=max_workers)
    futures = {}
    try:
        for code, cfg, connector in tasks:
            future = executor.submit(
                connector.search_library,
                code,
                cfg,
                query,
                field,
                LIVE_SEARCH_PER_LIBRARY_LIMIT,
                LIVE_SEARCH_LIBRARY_TIMEOUT,
            )
            futures[future] = (code, cfg.get("platform") or getattr(connector, "platform", ""))

        for future in as_completed(futures, timeout=LIVE_SEARCH_TOTAL_TIMEOUT):
            code, platform = futures[future]
            try:
                for result in future.result():
                    if _provider_allows_result(provider_labels, result):
                        results.append(result)
            except Exception as exc:
                errors.append({"library_code": code, "platform": platform, "error": str(exc)})
    except TimeoutError:
        for future, (code, platform) in futures.items():
            if not future.done():
                future.cancel()
                errors.append({"library_code": code, "platform": platform, "error": "search_timeout"})
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    elapsed_ms = int((time.time() - started) * 1000)
    if errors:
        errors = errors[:10]
    platforms = sorted({(LIBRARIES.get(code) or {}).get("platform") or "Unknown" for code in library_codes})
    return results, [{"platform": "all", "platforms": platforms, "elapsed_ms": elapsed_ms, "errors": errors}]


def live_search(
    query: str,
    field: str,
    providers_raw: str = "",
    libraries_raw: str = "",
    limit: int = 20,
    offset: int = 0,
    refine: str = "",
):
    query = (query or "").strip()
    field = field if field in {"title_author", "title", "author", "publisher"} else "title_author"
    providers = _split_csv(providers_raw)
    libraries = _split_csv(libraries_raw)
    limit = max(1, min(int(limit or 20), 100))
    offset = max(0, int(offset or 0))

    if not query:
        return {"total": 0, "items": [], "filters": {"providers": [], "libraries": []}, "meta": {"mode": "live"}}

    cache_key = _cache_key(query, field, providers, libraries)
    cached = _CACHE.get(cache_key)
    if cached:
        return _slice_response(cached, refine, limit, offset, True)

    library_codes = _selected_library_codes(libraries)
    raw_results, diagnostics = _search_libraries(query, field, library_codes, providers)
    merged_items = merge_live_results(raw_results)
    payload = {
        "total": len(merged_items),
        "items": merged_items,
        "filters": _filters_from_items(merged_items),
        "meta": {
            "mode": "live",
            "cache_hit": False,
            "connectors": sorted({(LIBRARIES.get(code) or {}).get("platform") or "Unknown" for code in library_codes}),
            "searched_libraries": len(library_codes),
            "diagnostics": diagnostics,
        },
    }
    _CACHE.set(cache_key, payload)
    return _slice_response(payload, refine, limit, offset, False)

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from live_search.connectors.common import make_session, request_headers
from live_search.models import LiveSearchResult


def _json_headers(referer: str) -> dict:
    headers = request_headers(referer)
    headers["Accept"] = "application/json, text/plain, */*"
    return headers


class SeoulLibraryConnector:
    platform = "SeoulLibrary"
    _categories = None
    _categories_lock = threading.Lock()

    def _fetch_categories(self, session, timeout: float):
        cls = type(self)
        if cls._categories is not None:
            return cls._categories
        with cls._categories_lock:
            if cls._categories is not None:
                return cls._categories
            response = session.get(
                "https://elib.seoul.go.kr/api/category/main",
                params={"contentType": "EB"},
                headers=_json_headers("https://elib.seoul.go.kr/"),
                timeout=timeout,
                verify=False,
            )
            response.raise_for_status()
            data = response.json()
            cls._categories = [
                item.get("categoryNo")
                for item in data.get("ContentDataList", [])
                if item.get("categoryNo")
            ]
            return cls._categories

    def search_library(self, lib_code: str, config: dict, query: str, field: str, limit: int, timeout: float):
        session = make_session()
        categories = self._fetch_categories(session, timeout)
        if not categories:
            return []

        results = []
        seen = set()
        max_workers = min(8, len(categories))
        per_category_limit = max(1, min(int(limit or 20), 10))

        def fetch_category(category_no: str):
            response = session.get(
                "https://elib.seoul.go.kr/api/contents/catesearch",
                params={
                    "libCode": "",
                    "majorCategory": category_no,
                    "subCategory": "",
                    "innerKeyword": query,
                    "orderOption": "1",
                    "loanable": "",
                    "currentCount": "1",
                    "pageCount": str(per_category_limit),
                    "_": int(time.time() * 1000),
                },
                headers=_json_headers("https://elib.seoul.go.kr/"),
                timeout=timeout,
                verify=False,
            )
            response.raise_for_status()
            return response.json().get("ContentDataList") or []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(fetch_category, category_no) for category_no in categories]
            for future in as_completed(futures):
                for item in future.result():
                    content_id = item.get("contentsKey") or ""
                    title = item.get("title") or ""
                    if not title or not content_id or content_id in seen:
                        continue
                    seen.add(content_id)
                    results.append(
                        LiveSearchResult(
                            title=title,
                            author=item.get("author") or "",
                            publisher=item.get("publisher") or "",
                            library_code=lib_code,
                            library_name=config.get("library_name") or config.get("name") or lib_code,
                            library_short=config.get("short_name") or "",
                            platform=self.platform,
                            provider=item.get("ownerCode") or "서울도서관",
                            image_url=item.get("coverUrl") or item.get("coverMSizeUrl") or "",
                            detail_url=f"https://elib.seoul.go.kr/contents/detail?no={content_id}",
                            isbn=item.get("isbn") or "",
                            identifiers={"content_id": content_id},
                        )
                    )
                    if len(results) >= limit:
                        return results
        return results[:limit]


class SenConnector:
    platform = "SeoulEducation"

    def search_library(self, lib_code: str, config: dict, query: str, field: str, limit: int, timeout: float):
        if lib_code == "sen_subs":
            return self._search_subs(lib_code, config, query, limit, timeout)
        return self._search_owned(lib_code, config, query, limit, timeout)

    def _search_owned(self, lib_code: str, config: dict, query: str, limit: int, timeout: float):
        search_query = re.sub(r"\s+", "", query or "")
        response = make_session().get(
            "https://e-lib.sen.go.kr/api/contents/page-data",
            params={
                "contentType": "TY01",
                "majorCategory": "",
                "subCategory": "",
                "tinyCategory": "",
                "ownerCategory": "",
                "innerSearchYN": "Y",
                "innerKeyword": search_query,
                "orderOption": "1",
                "typeOption": "1",
                "currentCount": "1",
                "pageCount": str(max(1, min(int(limit or 20), 100))),
                "loanable": "N",
                "_": int(time.time() * 1000),
            },
            headers=_json_headers("https://e-lib.sen.go.kr/"),
            timeout=timeout,
            verify=False,
        )
        response.raise_for_status()
        data = response.json()
        items = (((data.get("pageData") or {}).get("contents") or {}).get("ContentDataList") or [])
        return [self._owned_result(lib_code, config, item) for item in items if item.get("title")][:limit]

    def _search_subs(self, lib_code: str, config: dict, query: str, limit: int, timeout: float):
        search_query = re.sub(r"\s+", "", query or "")
        response = make_session().get(
            "https://e-lib.sen.go.kr/api/contents/catesearch",
            params={
                "contentType": "TY02",
                "majorCategory": "",
                "subCategory": "",
                "tinyCategory": "",
                "ownerCategory": "",
                "innerSearchYN": "Y",
                "innerKeyword": search_query,
                "orderOption": "1",
                "typeOption": "1",
                "currentCount": "1",
                "pageCount": str(max(1, min(int(limit or 20), 100))),
                "loanable": "N",
                "_": int(time.time() * 1000),
            },
            headers=_json_headers("https://e-lib.sen.go.kr/"),
            timeout=timeout,
            verify=False,
        )
        response.raise_for_status()
        data = response.json()
        container = data.get("CategoryDataList") or {}
        items = container.get("responses") or []
        return [self._subs_result(lib_code, config, item) for item in items if item.get("ucm_title")][:limit]

    def _owned_result(self, lib_code: str, config: dict, item: dict):
        content_id = item.get("contentsKey") or ""
        return LiveSearchResult(
            title=item.get("title") or "",
            author=item.get("author") or "",
            publisher=item.get("publisher") or "",
            library_code=lib_code,
            library_name=config.get("library_name") or config.get("name") or lib_code,
            library_short=config.get("short_name") or "",
            platform=self.platform,
            provider=item.get("ownerDesc") or "서울시교육청",
            image_url=item.get("coverUrl") or "",
            detail_url=f"https://e-lib.sen.go.kr/contents/detail?no={content_id}&type=TY01" if content_id else "",
            isbn=(item.get("isbn") or "").strip(),
            identifiers={"content_id": content_id},
        )

    def _subs_result(self, lib_code: str, config: dict, item: dict):
        content_id = item.get("ucm_code") or ""
        return LiveSearchResult(
            title=item.get("ucm_title") or "",
            author=item.get("ucm_writer") or "",
            publisher=item.get("ucp_brand") or "",
            library_code=lib_code,
            library_name=config.get("library_name") or config.get("name") or lib_code,
            library_short=config.get("short_name") or "",
            platform=self.platform,
            provider=item.get("ucm_publisher") or "서울시교육청",
            image_url=item.get("ucm_cover_url") or "",
            detail_url=f"https://e-lib.sen.go.kr/contents/detail?no={content_id}&type=TY02" if content_id else "",
            isbn=item.get("ucm_ebook_isbn") or item.get("isbn") or "",
            identifiers={"content_id": content_id},
        )

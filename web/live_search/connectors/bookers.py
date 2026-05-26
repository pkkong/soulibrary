import re
import time
from urllib.parse import urlencode

from live_search.connectors.common import make_session, request_headers
from live_search.models import LiveSearchResult


BOOKERS_CATALOG_URL = "https://e-lib.sen.go.kr/api/contents/catesearch"
BOOKERS_DETAIL_URL = "https://www.bookers.life/front/home/bookDetail.do"
BOOKERS_LOGIN_URL = "https://www.bookers.life/login.do"


def _json_headers() -> dict:
    headers = request_headers("https://e-lib.sen.go.kr/")
    headers["Accept"] = "application/json, text/plain, */*"
    return headers


def _search_keyword(query: str) -> str:
    return re.sub(r"\s+", "", query or "")


def _login_url(config: dict) -> str:
    org_name = (config.get("bookers_org_name") or "").strip()
    org_code = (config.get("bookers_org_code") or "").strip()
    if not org_name or not org_code:
        return BOOKERS_LOGIN_URL
    return f"{BOOKERS_LOGIN_URL}?{urlencode({'requestOrgName': org_name, 'requestCode': org_code})}"


def _detail_url(config: dict, content_id: str) -> str:
    uis_code = (config.get("bookers_uis_code") or config.get("bookers_org_code") or "").strip()
    if not content_id or not uis_code:
        return _login_url(config)
    return f"{BOOKERS_DETAIL_URL}?{urlencode({'ucm_code': content_id, 'paramUisCode': uis_code})}"


class BookersConnector:
    platform = "Bookers"

    def search_library(self, lib_code: str, config: dict, query: str, field: str, limit: int, timeout: float):
        keyword = _search_keyword(query)
        if not keyword:
            return []

        response = make_session().get(
            BOOKERS_CATALOG_URL,
            params={
                "contentType": "TY02",
                "majorCategory": "",
                "subCategory": "",
                "tinyCategory": "",
                "ownerCategory": "",
                "innerSearchYN": "Y",
                "innerKeyword": keyword,
                "orderOption": "1",
                "typeOption": "1",
                "currentCount": "1",
                "pageCount": str(max(1, min(int(limit or 20), 100))),
                "loanable": "N",
                "_": int(time.time() * 1000),
            },
            headers=_json_headers(),
            timeout=timeout,
            verify=False,
        )
        response.raise_for_status()
        data = response.json()
        items = (data.get("CategoryDataList") or {}).get("responses") or []
        return [self._result(lib_code, config, item) for item in items if item.get("ucm_title")][:limit]

    def _result(self, lib_code: str, config: dict, item: dict):
        content_id = item.get("ucm_code") or ""
        return LiveSearchResult(
            title=item.get("ucm_title") or "",
            author=item.get("ucm_writer") or "",
            publisher=item.get("ucp_brand") or "",
            library_code=lib_code,
            library_name=config.get("library_name") or config.get("name") or lib_code,
            library_short=config.get("short_name") or "",
            platform=self.platform,
            provider="부커스",
            image_url=item.get("ucm_cover_url") or "",
            image_candidates=[{"url": item.get("ucm_cover_url") or "", "hint": "primary"}],
            detail_url=_detail_url(config, content_id),
            isbn=item.get("ucm_ebook_isbn") or item.get("isbn") or "",
            service_type=config.get("service_type") or "",
            identifiers={"content_id": content_id},
        )

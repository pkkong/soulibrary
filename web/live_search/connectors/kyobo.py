import re
from urllib.parse import urlencode, urlparse

import requests
from lxml import html as lxml_html

from live_search.models import LiveSearchResult
from utils.http import DEFAULT_HEADERS, TLSAdapter, _build_ssl_context


CLICK_PATTERN = re.compile(
    r"fnContentClick\([^,]*,\s*'([^']*)'\s*,\s*'([^']*)'\s*,\s*'([^']*)'(?:\s*,\s*'([^']*)')?"
)

FIELD_TO_SCH_CLSTS = {
    "title_author": ("ctts", "autr"),
    "title": ("ctts",),
    "author": ("autr",),
    "publisher": ("pbcm",),
}


def _text(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _base_from_config(config: dict) -> tuple[str, str]:
    raw_url = config.get("homepage_url") or config.get("total_count_url") or ""
    parsed = urlparse(raw_url)
    if not parsed.scheme or not parsed.netloc:
        return "", ""
    total_url = config.get("total_count_url") or raw_url
    total_parsed = urlparse(total_url)
    return f"{parsed.scheme}://{parsed.netloc}", total_parsed.path or parsed.path or ""


def _search_path(path: str) -> str:
    return "/elibrary-front/search/searchList.ink" if path.startswith("/elibrary-front/") else "/search/searchList.ink"


def _absolute_url(url: str, base_url: str) -> str:
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return base_url + url
    return url


def _detail_url(base_url: str, content_path: str, ctts_dvsn_code: str, brcd: str, ctgr_id: str, sntn_auth_code: str) -> str:
    if not base_url or not brcd:
        return ""
    path = content_path or "/elibrary-front/content/contentView.ink"
    if not path.startswith("/"):
        path = "/" + path
    params = {
        "cttsDvsnCode": ctts_dvsn_code,
        "brcd": brcd,
        "ctgrId": ctgr_id,
    }
    if sntn_auth_code:
        params["sntnAuthCode"] = sntn_auth_code
    return f"{base_url}{path}?{urlencode(params)}"


class KyoboNewConnector:
    platform = "Kyobo_New"

    def _session(self):
        session = requests.Session()
        session.trust_env = False
        session.mount("https://", TLSAdapter(ssl_context=_build_ssl_context()))
        return session

    def search_library(self, lib_code: str, config: dict, query: str, field: str, limit: int, timeout: float):
        base_url, base_path = _base_from_config(config)
        if not base_url:
            return []

        url = f"{base_url}{_search_path(base_path)}"
        results = []
        seen = set()
        for sch_clst in FIELD_TO_SCH_CLSTS.get(field, FIELD_TO_SCH_CLSTS["title_author"]):
            params = {
                "schTxt": query,
                "schClst": sch_clst,
                "pageIndex": "1",
                "recordCount": str(max(1, min(int(limit or 20), 50))),
                "dvsnCheck": "001",
            }
            response = self._session().get(
                url,
                params=params,
                headers=DEFAULT_HEADERS,
                timeout=timeout,
                verify=False,
            )
            response.raise_for_status()
            for result in self._parse_results(
                response.text,
                base_url=base_url,
                lib_code=lib_code,
                config=config,
            ):
                identifiers = result.identifiers or {}
                key = identifiers.get("brcd") or f"{result.title}|{result.author}|{result.publisher}"
                if key in seen:
                    continue
                seen.add(key)
                results.append(result)
        return results

    def _parse_results(self, html: str, base_url: str, lib_code: str, config: dict):
        doc = lxml_html.fromstring(html)
        nodes = doc.xpath(
            "//li[.//li[contains(@class, 'tit')] and .//li[contains(@class, 'writer')]]"
        )
        results = []
        for node in nodes:
            title = _text(node.xpath("string(.//li[contains(@class, 'tit')]/a)"))
            if not title:
                continue

            writer_texts = [
                _text(value)
                for value in node.xpath(".//li[contains(@class, 'writer')]/text()")
                if _text(value)
            ]
            writer_spans = [
                _text(value)
                for value in node.xpath(".//li[contains(@class, 'writer')]//span/text()")
                if _text(value)
            ]
            author = writer_texts[0] if writer_texts else ""
            publisher = writer_spans[0] if writer_spans else ""
            provider = _text(node.xpath("string(.//span[contains(@class, 'store')])")) or "교보문고"
            image_url = _absolute_url(
                _text(node.xpath("string(.//div[contains(@class, 'img')]//img/@src)")),
                base_url,
            )

            ctts_dvsn_code = ""
            brcd = ""
            ctgr_id = ""
            sntn_auth_code = ""
            onclick = _text(node.xpath("string(.//a[contains(@onclick, 'fnContentClick')]/@onclick)"))
            match = CLICK_PATTERN.search(onclick)
            if match:
                groups = [value or "" for value in match.groups()]
                while len(groups) < 4:
                    groups.append("")
                ctts_dvsn_code, brcd, ctgr_id, sntn_auth_code = groups[:4]

            results.append(
                LiveSearchResult(
                    title=title,
                    author=author,
                    publisher=publisher,
                    library_code=lib_code,
                    library_name=config.get("library_name") or config.get("name") or lib_code,
                    library_short=config.get("short_name") or "",
                    platform=self.platform,
                    provider=provider,
                    image_url=image_url,
                    detail_url=_detail_url(
                        base_url,
                        config.get("content_path") or "",
                        ctts_dvsn_code,
                        brcd,
                        ctgr_id,
                        sntn_auth_code,
                    ),
                    identifiers={
                        "brcd": brcd,
                        "ctts_dvsn_code": ctts_dvsn_code,
                        "ctgr_id": ctgr_id,
                        "sntn_auth_code": sntn_auth_code,
                    },
                )
            )
        return results

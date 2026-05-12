import re
from urllib.parse import urlencode

from lxml import html as lxml_html

from live_search.connectors.common import absolute_url, make_session, origin_from_url, request_headers, text
from live_search.models import LiveSearchResult


FIELD_TO_ORDER = {
    "title_author": ("total",),
    "title": ("title",),
    "author": ("author",),
    "publisher": ("publisher",),
}

PROVIDER_MAP = {
    "예스24": "YES24",
    "예스이십사": "YES24",
    "yes24": "YES24",
    "교보문고": "교보",
    "교보": "교보",
    "kyobo": "교보",
    "알라딘": "알라딘",
    "aladin": "알라딘",
    "북큐브": "북큐브",
    "bookcube": "북큐브",
    "웅진씽크빅": "웅진",
    "웅진": "웅진",
    "opms": "OPMS",
    "오피엠에스": "OPMS",
}


def normalize_provider(raw: str) -> str:
    key = re.sub(r"\s+", "", raw or "").lower()
    for source, target in PROVIDER_MAP.items():
        if key == re.sub(r"\s+", "", source).lower():
            return target
    return raw.strip() if raw else "YES24"


class Yes24Connector:
    platform = "YES24"

    def search_library(self, lib_code: str, config: dict, query: str, field: str, limit: int, timeout: float):
        base_url = origin_from_url(config.get("homepage_url") or config.get("total_count_url") or "")
        if not base_url:
            return []

        session = make_session()
        results = []
        seen = set()
        for srch_order in FIELD_TO_ORDER.get(field, FIELD_TO_ORDER["title_author"]):
            params = {
                "srch_order": srch_order,
                "src_key": query,
            }
            url = f"{base_url}/search/?{urlencode(params)}"
            response = session.get(
                url,
                headers=request_headers(base_url),
                timeout=timeout,
                verify=False,
            )
            response.raise_for_status()
            for result in self._parse_results(response.text, base_url, lib_code, config):
                goods_id = (result.identifiers or {}).get("goods_id") or ""
                key = goods_id or f"{result.title}|{result.author}|{result.publisher}"
                if key in seen:
                    continue
                seen.add(key)
                results.append(result)
                if len(results) >= limit:
                    return results
        return results

    def _parse_results(self, html: str, base_url: str, lib_code: str, config: dict):
        doc = lxml_html.fromstring(html)
        nodes = doc.xpath("//div[contains(concat(' ', normalize-space(@class), ' '), ' bx ')]")
        results = []
        for node in nodes:
            title = text(node.xpath("string(.//p[contains(@class, 'tit')]/a)"))
            if not title:
                continue

            href = text(
                node.xpath("string(.//p[contains(@class, 'tit')]/a/@href)")
                or node.xpath("string(.//a[contains(@class, 'thumb')]/@href)")
            )
            goods_id = ""
            match = re.search(r"goods_id=([0-9]+)", href)
            if match:
                goods_id = match.group(1)

            writer = text(node.xpath("string(.//p[contains(@class, 'writer')])"))
            author = writer.split("/")[0].replace(" 저", "").strip() if writer else ""
            details = [text(value) for value in node.xpath(".//p[contains(@class, 'detail')]/span/text()")]
            publisher = details[0] if details else ""
            provider = normalize_provider(details[2] if len(details) >= 3 else "")
            image_url = absolute_url(text(node.xpath("string(.//a[contains(@class, 'thumb')]//img/@src)")), base_url)

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
                    detail_url=f"{base_url}/ebook/detail/?goods_id={goods_id}" if goods_id else "",
                    identifiers={"goods_id": goods_id},
                )
            )
        return results

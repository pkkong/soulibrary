import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from lxml import html as lxml_html

from live_search.connectors.common import absolute_url, make_session, origin_from_url, request_headers, text
from live_search.models import LiveSearchResult


FIELD_TO_KEYOPTION2 = {
    "title_author": ("1", "2"),
    "title": ("1",),
    "author": ("2",),
    "publisher": ("3",),
}


def _search_url(list_url: str, keyword: str, keyoption2: str, limit: int) -> str:
    parsed = urlparse(list_url)
    qs = parse_qs(parsed.query)
    qs["page"] = ["1"]
    qs["itemCount"] = [str(max(1, min(int(limit or 20), 200)))]
    qs["searchType"] = ["search"]
    qs["searchoption"] = ["1"]
    qs["keyoption2"] = [keyoption2]
    qs["keyword"] = [keyword]
    qs.setdefault("selectview", ["list_on"])
    return urlunparse(parsed._replace(query=urlencode(qs, doseq=True)))


def _base_list_url(config: dict) -> str:
    if config.get("total_count_url"):
        return config["total_count_url"].split("#", 1)[0]
    base_url = origin_from_url(config.get("homepage_url") or "")
    if not base_url:
        return ""
    return (
        f"{base_url}/FxLibrary/product/list/?itemdv=1&sort=3&page=1&itemCount=20&pageCount=10"
        "&category=&middlecategory=&cateopt=total&group_num=recommand&catenavi=main&category_type=book"
        "&searchoption=&keyoption=&keyoption2=&keyword=&listfilter=all_list&selectview=list_on"
        "&searchType=&name=&publisher=&author=&terminal="
    )


class BookcubeConnector:
    platform = "Bookcube"

    def search_library(self, lib_code: str, config: dict, query: str, field: str, limit: int, timeout: float):
        list_url = _base_list_url(config)
        base_url = origin_from_url(list_url or config.get("homepage_url") or "")
        if not list_url or not base_url:
            return []

        session = make_session()
        results = []
        seen = set()
        search_fields = FIELD_TO_KEYOPTION2.get(field, FIELD_TO_KEYOPTION2["title_author"])
        for keyoption2 in search_fields:
            url = _search_url(list_url, query, keyoption2, limit)
            response = session.get(url, headers=request_headers(base_url), timeout=timeout, verify=False)
            response.raise_for_status()
            for result in self._parse_results(response.text, base_url, lib_code, config):
                content_id = (result.identifiers or {}).get("content_id") or ""
                key = content_id or f"{result.title}|{result.author}|{result.publisher}"
                if key in seen:
                    continue
                seen.add(key)
                results.append(result)
                if len(results) >= limit:
                    return results
            if field == "title_author" and results:
                return results[:limit]
        return results

    def _parse_results(self, html: str, base_url: str, lib_code: str, config: dict):
        doc = lxml_html.fromstring(html)
        nodes = doc.xpath("//li[contains(concat(' ', normalize-space(@class), ' '), ' item ')]")
        results = []
        for node in nodes:
            title = text(node.xpath("string(.//div[contains(@class, 'subject')]/a)"))
            if not title:
                continue

            node_html = lxml_html.tostring(node, encoding="unicode")
            content_id = ""
            match = re.search(r"goView\('([A-Za-z0-9]+)'", node_html)
            if match:
                content_id = match.group(1)
            if not content_id:
                match = re.search(r"num=([A-Za-z0-9]+)", node_html)
                if match:
                    content_id = match.group(1)

            info_lists = node.xpath(".//div[contains(@class, 'info')]//ul[contains(@class, 'i1')]")
            author = ""
            publisher = ""
            provider = "북큐브"
            if info_lists:
                first_items = info_lists[0].xpath("./li")
                if first_items:
                    author = text(first_items[0].xpath("string(.)")).removesuffix(" 저").strip()
                if len(first_items) >= 2:
                    publisher = text(first_items[1].xpath("string(.)"))
            if len(info_lists) >= 2:
                supply_text = text(info_lists[1].xpath("string(.//li[1])"))
                match = re.search(r"공급\s*:\s*([^(]+)", supply_text)
                if match:
                    provider = match.group(1).strip() or provider

            image_url = absolute_url(text(node.xpath("string(.//div[contains(@class, 'thumb')]//img/@src)")), base_url)
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
                    detail_url=f"{base_url}/FxLibrary/product/view/?num={content_id}&category=&category_type=book" if content_id else "",
                    service_type=config.get("service_type") or "",
                    identifiers={"content_id": content_id},
                )
            )
        return results

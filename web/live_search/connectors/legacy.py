import re
from urllib.parse import parse_qs, urlencode, urlparse

from lxml import html as lxml_html

from live_search.connectors.common import absolute_url, make_session, origin_from_url, request_headers, text
from live_search.models import LiveSearchResult
from utils.http import DOBONG_HEADERS


class DobongKyoboConnector:
    platform = "Kyobo"

    def search_library(self, lib_code: str, config: dict, query: str, field: str, limit: int, timeout: float):
        base_url = origin_from_url(config.get("homepage_url") or config.get("total_count_url") or "")
        if not base_url:
            return []

        params = {"total_search_keyword": query}
        url = f"{base_url}/Kyobo_T3/Content/Content_Search.asp?{urlencode(params)}"
        response = make_session().get(url, headers=DOBONG_HEADERS, timeout=timeout, verify=False)
        response.raise_for_status()
        return self._parse_results(response.text, base_url, lib_code, config)[:limit]

    def _parse_results(self, html: str, base_url: str, lib_code: str, config: dict):
        doc = lxml_html.fromstring(html)
        nodes = doc.xpath("//li[starts-with(@id, 'content_')]")
        results = []
        for node in nodes:
            title = text(node.xpath("string(.//dt/a)"))
            if not title:
                continue

            detail_href = text(node.xpath("string(.//p[contains(@class, 'pic')]/a/@href)"))
            detail_url = absolute_url(detail_href, base_url)
            query = parse_qs(urlparse(detail_href).query)
            brcd = ""
            match = re.search(r"barcode=([A-Za-z0-9]+)", detail_href)
            if match:
                brcd = match.group(1)
            if not brcd:
                brcd = text(node.xpath("string(@id)")).replace("content_", "")
            product_cd = (query.get("product_cd") or ["001"])[0] or "001"
            category_id = (query.get("category_id") or [""])[0]

            em_text = text(node.xpath("string(.//dd/em)"))
            author = ""
            publisher = ""
            match = re.search(r"^(.*?)\s*/\s*\[\s*(.*?)\s*/", em_text)
            if match:
                author = match.group(1).strip()
                publisher = match.group(2).strip()

            image_url = absolute_url(text(node.xpath("string(.//p[contains(@class, 'pic')]//img/@src)")), base_url)
            results.append(
                LiveSearchResult(
                    title=title,
                    author=author,
                    publisher=publisher,
                    library_code=lib_code,
                    library_name=config.get("library_name") or config.get("name") or lib_code,
                    library_short=config.get("short_name") or "",
                    platform=self.platform,
                    provider="교보문고",
                    image_url=image_url,
                    detail_url=detail_url,
                    identifiers={"brcd": brcd, "product_cd": product_cd, "category_id": category_id},
                )
            )
        return results


class GangnamConnector:
    platform = "Gangnam"

    FIELD_TO_SEARCH = {
        "title_author": ("title", "author"),
        "title": ("title",),
        "author": ("author",),
        "publisher": ("publisher",),
    }

    def search_library(self, lib_code: str, config: dict, query: str, field: str, limit: int, timeout: float):
        base_url = origin_from_url(config.get("homepage_url") or config.get("total_count_url") or "")
        if not base_url:
            return []

        session = make_session()
        results = []
        seen = set()
        search_fields = self.FIELD_TO_SEARCH.get(field, self.FIELD_TO_SEARCH["title_author"])
        for search_type in search_fields:
            query_string = urlencode({"search": search_type, "strSearch": query}, encoding="euc-kr")
            url = f"{base_url}/elibbook/book_info.asp?{query_string}"
            response = session.get(url, headers=request_headers(base_url), timeout=timeout, verify=False)
            response.raise_for_status()
            decoded = response.content.decode("euc-kr", "replace")
            for result in self._parse_results(decoded, base_url, lib_code, config):
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
        nodes = doc.xpath(
            "//div[contains(concat(' ', normalize-space(@class), ' '), ' book ')][.//div[contains(@class, 'book_title')]]"
        )
        results = []
        for node in nodes:
            title = text(node.xpath("string(.//div[contains(@class, 'book_title')]/a)"))
            if not title:
                continue

            detail_href = text(node.xpath("string(.//div[contains(@class, 'book_title')]/a/@href)"))
            detail_url = absolute_url(detail_href, f"{base_url}/elibbook/")
            content_id = ""
            match = re.search(r"book_num=([A-Za-z0-9]+)", detail_href)
            if match:
                content_id = match.group(1)

            author = text(node.xpath("string(.//div[contains(@class, 'writer')])"))
            publish_text = text(node.xpath("string(.//div[contains(@class, 'publish_date')])"))
            publisher = re.split(r"\s*[·ㆍ]\s*", publish_text)[0].strip() if publish_text else ""
            provider = text(node.xpath("string(.//div[contains(@class, 'current')]/strong)")) or "기타"
            image_url = absolute_url(text(node.xpath("string(.//div[contains(@class, 'book_frame')]//img/@src)")), base_url)

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
                    detail_url=detail_url,
                    identifiers={"content_id": content_id},
                )
            )
        return results


class EunpyeongConnector:
    platform = "Eunpyeong"

    FIELD_TO_SEARCH_TYPE = {
        "title_author": "total",
        "title": "title",
        "author": "author",
        "publisher": "publisher",
    }

    PROVIDER_BY_CODE = {
        "AL": "알라딘",
        "YE": "YES24",
        "YES24": "YES24",
        "EC": "ECO MOA",
        "BX": "OPMS",
        "OPMS": "OPMS",
    }

    def search_library(self, lib_code: str, config: dict, query: str, field: str, limit: int, timeout: float):
        base_url = origin_from_url(config.get("homepage_url") or config.get("total_count_url") or "")
        if not base_url:
            return []

        compact_query = re.sub(r"\s+", "", query)
        params = {
            "contentType": "EB",
            "searchType": self.FIELD_TO_SEARCH_TYPE.get(field, "total"),
            "keyword": compact_query,
            "sort": "title",
            "asc": "desc",
            "loanable": "N",
            "page": "1",
            "size": str(max(1, min(int(limit or 20), 50))),
        }
        response = make_session().get(
            f"{base_url}/api/service/search/simple",
            params=params,
            headers=request_headers(base_url),
            timeout=timeout,
            verify=False,
        )
        response.raise_for_status()
        data = response.json()
        items = ((data.get("data") or {}).get("content") or []) if isinstance(data, dict) else []

        results = []
        for item in items:
            title = item.get("title") or ""
            content_id = item.get("contentKey") or ""
            content_type = item.get("contentType") or "EB"
            owner_code = (item.get("ownerCode") or "").strip().upper()
            provider = self.PROVIDER_BY_CODE.get(owner_code) or item.get("ownerCodeDesc") or ""
            if not title:
                continue
            results.append(
                LiveSearchResult(
                    title=title,
                    author=item.get("author") or "",
                    publisher=item.get("publisher") or "",
                    library_code=lib_code,
                    library_name=config.get("library_name") or config.get("name") or lib_code,
                    library_short=config.get("short_name") or "",
                    platform=self.platform,
                    provider=provider,
                    image_url=item.get("coverUrl") or "",
                    detail_url=f"{base_url}/content/detail?id={content_id}&contentType={content_type}" if content_id else "",
                    identifiers={"content_id": content_id, "content_type": content_type},
                )
            )
        return results

import json
import math
from typing import Optional
from urllib.parse import urlencode

import scrapy


class EunpyeongNativeSpider(scrapy.Spider):
    name = "eunpyeong_native"
    allowed_domains = ["epbook.eplib.or.kr"]
    base_url = "https://epbook.eplib.or.kr/ebookPlatform/Homepage/TotalEbook.do"
    library_name = "은평구립도서관"
    page_size = 100
    max_pages_fallback = 1500

    custom_settings = {
        "FEED_EXPORT_ENCODING": "utf-8-sig",
    }

    def start_requests(self):
        yield self._make_request(1, total_pages=None)

    def _make_request(self, page: int, total_pages: Optional[int]):
        params = {
            "libCode": "111042",
            "userId": "null",
            "majorCategory": "000",
            "subCategory": "",
            "collection": "1",
            "orderOption": "1",
            "currentCount": str(page),
            "pageCount": str(self.page_size),
        }
        url = f"{self.base_url}?{urlencode(params)}"
        return scrapy.Request(
            url,
            callback=self.parse,
            meta={"page": page, "total_pages": total_pages},
            dont_filter=True,
        )

    def _load_json(self, response):
        # 우선 UTF-8, 안 되면 EUC-KR/CP949 순으로 디코딩 시도
        for enc in ("utf-8", "euc-kr", "cp949"):
            try:
                return json.loads(response.body.decode(enc))
            except Exception:
                continue
        try:
            return response.json()
        except Exception:
            return {}

    def _normalize_provider(self, code: str, raw: str) -> str:
        code = (code or "").strip().upper()
        map_by_code = {
            "AL": "알라딘",
            "YE": "YES24",
            "EC": "ECO MOA",
            "BX": "OPMS",
        }
        if code in map_by_code:
            return map_by_code[code]

        if not raw:
            return ""
        raw = raw.strip()
        if "\ufffd" in raw and "24" in raw:
            return "YES24"
        if "YES24" in raw or "예스24" in raw or "yes24" in raw.lower():
            return "YES24"
        if "교보" in raw:
            return "교보"
        if "북큐브" in raw or "BOOKCUBE" in raw.upper():
            return "북큐브"
        if "알라딘" in raw or "aladin" in raw.lower():
            return "알라딘"
        if "OPMS" in raw.upper():
            return "OPMS"
        if "ECO" in raw.upper():
            return "ECO MOA"
        return raw

    def parse(self, response):
        page = response.meta.get("page", 1)
        total_pages = response.meta.get("total_pages")

        data = self._load_json(response)
        if not data:
            self.logger.error("Failed to parse JSON on page %s", page)
            return

        contents = data.get("Contents", {}) if isinstance(data, dict) else {}

        if total_pages is None and page == 1:
            total_count = contents.get("TotalCount")
            try:
                total_count_int = int(str(total_count).replace(",", ""))
                total_pages = math.ceil(total_count_int / self.page_size)
            except Exception:
                total_pages = contents.get("TotalPage")
                try:
                    total_pages = int(str(total_pages).replace(",", ""))
                except Exception:
                    total_pages = self.max_pages_fallback
            self.logger.info("Total pages detected: %s", total_pages)
        elif total_pages is None:
            total_pages = self.max_pages_fallback

        items = contents.get("ContentDataList") or []
        if not items:
            self.logger.info("Empty list on page %s, stopping", page)
            return

        for item in items:
            title = (item.get("ContentTitle") or "").strip()
            author = (item.get("ContentAuthor") or "").strip()
            publisher = (item.get("ContentPublisher") or "").strip()
            image_url = (
                item.get("ContentCoverUrl")
                or item.get("ContentCoverUrlM")
                or item.get("ContentCoverUrlS")
                or ""
            )
            owner_code = item.get("OwnerCode") or ""
            provider_raw = (item.get("OwnerCodeDesc") or "").strip()
            provider = self._normalize_provider(owner_code, provider_raw)

            if title:
                yield {
                    "title": title,
                    "author": author,
                    "publisher": publisher,
                    "library": self.library_name,
                    "platform": "Unknown",
                    "provider": provider,
                    "image_url": image_url,
                    "isbn": "",
                }

        next_page = page + 1
        if total_pages and next_page <= total_pages:
            yield self._make_request(next_page, total_pages=total_pages)

# -*- coding: utf-8 -*-
import math
import re
from urllib.parse import urlencode

import scrapy


class BookcubeBaseSpider(scrapy.Spider):
    """Common Bookcube/FxLibrary list crawler base."""

    custom_settings = {
        "FEED_EXPORT_ENCODING": "utf-8-sig",
    }

    page_size = 200  # itemCount
    max_pages_fallback = 1000
    provider_default = "북큐브"
    platform = "Bookcube"
    export_content_id = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._seen_ids = set()

    def start_requests(self):
        yield self._make_request(1, total_pages=None)

    def _make_request(self, page: int, total_pages: int | None):
        params = {
            "itemdv": "1",
            "sort": "3",
            "page": str(page),
            "itemCount": str(self.page_size),
            "pageCount": "10",
            "category": "",
            "middlecategory": "",
            "cateopt": "total",
            "group_num": "recommand",
            "catenavi": "main",
            "category_type": "book",
            "searchoption": "",
            "keyoption": "",
            "keyoption2": "",
            "keyword": "",
            "listfilter": "all_list",
            "selectview": "list_on",
            "searchType": "",
            "name": "",
            "publisher": "",
            "author": "",
            "terminal": "",
        }
        url = f"{self.base_url}?{urlencode(params)}"
        return scrapy.Request(
            url,
            callback=self.parse,
            meta={"page": page, "total_pages": total_pages},
            dont_filter=True,
        )

    def parse_total_count(self, response):
        text = response.css("h2 span em::text").get() or ""
        m = re.search(r"총\s*([\d,]+)종", text)
        if not m:
            return None
        try:
            return int(m.group(1).replace(",", ""))
        except Exception:
            return None

    def parse(self, response):
        page = response.meta.get("page", 1)
        total_pages = response.meta.get("total_pages")

        if total_pages is None and page == 1:
            total_count = self.parse_total_count(response)
            if total_count:
                total_pages = math.ceil(total_count / self.page_size)
            else:
                total_pages = self.max_pages_fallback
            self.logger.info("[Bookcube] total_pages=%s (page_size=%s)", total_pages, self.page_size)

        books = response.css("li.item")
        if not books:
            self.logger.info("[Bookcube] page %s empty, stop", page)
            return

        if page % 10 == 0:
            self.logger.info("[Bookcube] page %s: %s items", page, len(books))

        for book in books:
            content_id = ""
            for href in book.css("a::attr(href)").getall():
                m = re.search(r"goView\('(\d+)'", href)
                if m:
                    content_id = m.group(1)
                    break
            if not content_id:
                img_try = book.css("img::attr(src)").get() or ""
                m = re.search(r"/(\d(5,))", img_try)
                if m:
                    content_id = m.group(1)

            if content_id and content_id in self._seen_ids:
                continue
            if content_id:
                self._seen_ids.add(content_id)

            title = (book.css(".subject a::text").get() or "").strip()
            author = (book.css(".info ul.i1:nth-of-type(1) li:nth-child(1) ::text").get() or "").strip()
            publisher = (book.css(".info ul.i1:nth-of-type(1) li:nth-child(2) ::text").get() or "").strip()

            supply_text = "".join(book.css(".info ul.i1:nth-of-type(2) li:first-child ::text").getall())
            provider = self.provider_default
            m = re.search(r"공급\s*:\s*([^\(]+)", supply_text)
            if m:
                provider = m.group(1).strip()
            provider = provider or self.provider_default

            image_url = book.css(".thumb img::attr(src)").get()
            if image_url and image_url.startswith("//"):
                image_url = "https:" + image_url

            isbn = ""

            if title:
                item = {
                    "title": title,
                    "author": author,
                    "publisher": publisher,
                    "library": self.library_name,
                    "image_url": image_url or "",
                    "isbn": isbn,
                    "provider": provider,
                    "platform": self.platform,
                }
                if self.export_content_id:
                    item["content_id"] = content_id
                yield item

        next_page = page + 1
        if total_pages and next_page <= total_pages:
            yield self._make_request(next_page, total_pages)

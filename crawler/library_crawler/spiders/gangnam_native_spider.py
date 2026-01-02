import math
from urllib.parse import urlencode

import scrapy


class GangnamNativeSpider(scrapy.Spider):
    name = "gangnam_native"
    allowed_domains = ["ebook.gangnam.go.kr"]
    base_url = "https://ebook.gangnam.go.kr/elibbook/book_category.asp"
    library_name = "강남구 전자도서관"
    platform = "Unknown"
    page_size = 20
    total_pages = None

    def start_requests(self):
        yield self._make_request(1)

    def _make_request(self, page: int):
        params = {
            "mode": "",
            "page_num": str(page),
            "branch": "99",
            "supply_code": "",
            "strSort": "p",  # 최신출판일순
            "ldav": "",
        }
        url = f"{self.base_url}?{urlencode(params)}"
        return scrapy.Request(url, callback=self.parse, meta={"page": page}, dont_filter=True)

    def _extract_total_pages(self, response):
        text = response.css("div.list_header strong::text").get()
        if not text:
            return None
        try:
            total_count = int(text.replace(",", "").strip())
        except ValueError:
            return None
        return math.ceil(total_count / self.page_size)

    def parse(self, response):
        page = response.meta.get("page", 1)

        if self.total_pages is None and page == 1:
            detected = self._extract_total_pages(response)
            if detected:
                self.total_pages = detected
                self.logger.info("Total pages detected: %s", self.total_pages)

        books = response.css("div.book")
        if not books:
            self.logger.info("No books on page %s, stopping.", page)
            return

        for book in books:
            title = book.css("div.book_title a::text").get()
            author = (book.css("div.writer::text").get() or "").strip()

            publish_text = book.css("div.publish_date::text").get() or ""
            publisher = publish_text.split("·")[0].strip() if "·" in publish_text else publish_text.strip()

            provider = (book.css("div.book_info div.current strong::text").get() or "").strip() or "강남전자도서관"

            image_url = book.css("div.book_frame img::attr(src)").get()
            if image_url:
                if image_url.startswith("//"):
                    image_url = "https:" + image_url
                elif image_url.startswith("/"):
                    image_url = "https://ebook.gangnam.go.kr" + image_url

            isbn = ""  # 목록에서는 제공되지 않음

            if title:
                yield {
                    "title": title.strip(),
                    "author": author,
                    "publisher": publisher,
                    "library": self.library_name,
                    "platform": self.platform,
                    "provider": provider,
                    "image_url": image_url,
                    "isbn": isbn,
                }

        next_page = page + 1
        page_limit = self.total_pages or (page + 1)  # fallback: stop when empty
        if next_page <= page_limit:
            yield self._make_request(next_page)

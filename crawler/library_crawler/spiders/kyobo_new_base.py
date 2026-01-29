import math
import re
from urllib.parse import urlencode

import scrapy

CLICK_PATTERN = re.compile(
    r"fnContentClick\([^,]*,\s*'([^']*)'\s*,\s*'([^']*)'\s*,\s*'([^']*)'"
)


class KyoboNewBaseSpider(scrapy.Spider):
    """
    Base spider for Kyobo (new version).
    Subclasses set: name, base_url, allowed_domains, library_name.
    Optional overrides: image_prefix, page_size, max_pages_cap, user_agent.
    """

    page_size = 80
    max_pages_cap = 600
    image_prefix = None
    provider = "교보문고"
    platform = "Kyobo_New"
    user_agent = "Mozilla/5.0 (compatible; KyoboNewCrawler/1.0)"
    total_pages = None

    def start_requests(self):
        yield self._make_request(1)

    def _make_request(self, page: int):
        params = {
            "brcd": "",
            "sntnAuthCode": "",
            "contentAll": "Y",
            "cttsDvsnCode": "001",
            "ctgrId": "",
            "orderByKey": "publDate",
            "selViewCnt": str(self.page_size),
            "pageIndex": str(page),
            "recordCount": str(self.page_size),
        }
        url = f"{self.base_url}?{urlencode(params)}"
        return scrapy.Request(
            url,
            callback=self.parse,
            meta={"page": page},
            headers={"User-Agent": self.user_agent},
            dont_filter=True,
        )

    def _extract_total_pages(self, response):
        """
        Parse total pages using the same idea as admin: total count text -> pages.
        Falls back to #totalPage when count is missing.
        """
        # 1) Strong texts in book_resultTxt: pick max numeric value as total count.
        total_count = None
        strong_texts = response.css("div.book_resultTxt strong::text").getall()
        counts = []
        for text in strong_texts:
            digits = re.sub(r"[^\d,]", "", text)
            if digits:
                counts.append(int(digits.replace(",", "")))
        if counts:
            total_count = max(counts)

        total_pages = None
        if total_count is not None:
            total_pages = math.ceil(total_count / self.page_size)

        # 2) Fallback: explicit totalPage element if present.
        if total_pages is None:
            total_page_text = response.css("#totalPage::text").get()
            if total_page_text:
                match_page = re.search(r"([\d,]+)", total_page_text)
                if match_page:
                    total_pages = int(match_page.group(1).replace(",", ""))

        if total_pages is None:
            return None

        return min(total_pages, self.max_pages_cap)

    def parse(self, response):
        page = response.meta.get("page", 1)

        # On the first page, detect total pages from HTML to avoid hard caps.
        if self.total_pages is None and page == 1:
            detected_total = self._extract_total_pages(response)
            if detected_total:
                self.total_pages = detected_total
                self.logger.info("Total pages detected: %s", self.total_pages)

        books = response.xpath('//li[.//li[@class="tit"]]') or []
        if not books:
            self.logger.info("No books on page %s, stopping.", page)
            return

        if page % 10 == 0:
            self.logger.info("[Page %s] %s items collected", page, len(books))

        for book in books:
            title = book.css("li.tit a::text").get()
            writer_texts = book.css("li.writer::text").getall()
            author = writer_texts[0].strip() if writer_texts else ""
            publisher = book.css("li.writer span::text").get() or ""
            provider = book.css("span.store::text").get() or self.provider
            onclick = book.css("a[onclick*='fnContentClick']::attr(onclick)").get() or ""
            ctts_dvsn_code = ""
            brcd = ""
            ctgr_id = ""
            match = CLICK_PATTERN.search(onclick)
            if match:
                ctts_dvsn_code, brcd, ctgr_id = match.groups()

            image_url = book.css("div.img a img::attr(src)").get()
            if image_url:
                if image_url.startswith("//"):
                    image_url = "https:" + image_url
                elif self.image_prefix and image_url.startswith("/"):
                    image_url = f"{self.image_prefix}{image_url}"
            if not brcd and image_url:
                match = re.search(r"/ebook/(\d{10,13})/", image_url)
                if match:
                    brcd = match.group(1)
            # Kyobo New image URLs do not embed ISBN; leave blank.
            isbn = ""

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
                    "brcd": brcd,
                    "ctts_dvsn_code": ctts_dvsn_code,
                    "ctgr_id": ctgr_id,
                }

        # Schedule next page lazily; obey detected total pages if available.
        next_page = page + 1
        page_limit = self.total_pages or self.max_pages_cap
        if next_page <= page_limit:
            yield self._make_request(next_page)

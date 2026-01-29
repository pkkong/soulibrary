import re
from urllib.parse import urlencode

import scrapy


class DobongKyoboSpider(scrapy.Spider):
    name = "dobong_kyobo"
    allowed_domains = ["elib.dobong.kr"]

    # 도봉구 전자도서관 (교보 구버전 T3)
    base_url = "https://elib.dobong.kr/Kyobo_T3/Content/ebook/ebook_Main.asp"
    library_name = "도봉구립도서관"
    page_size = 80  # listnum

    def start_requests(self):
        params = {
            "product_cd": "001",
            "category_id": "",
            "content_all": "Y",
            "order_key": "STOCK_YMD",
            "search_keyword": "",
            "search_type": "",
            "search_product_cd": "",
            "list_type": "",
            "now_page": "1",
            "listnum": str(self.page_size),
        }
        url = f"{self.base_url}?{urlencode(params)}"
        yield scrapy.Request(
            url,
            callback=self.parse,
            meta={"page": 1},
            headers={"User-Agent": "Mozilla/5.0 (compatible; DobongCrawler/1.0)"},
            dont_filter=True,
        )

    def parse(self, response):
        page = response.meta.get("page", 1)

        books = response.css("ul.books_wrap > li[id^='content_'], ul.list_type01 > li[id^='content_'], ul#content_list > li[id^='content_']")
        if not books:
            self.logger.info("No books on page %s, stopping.", page)
            return

        if page % 10 == 0:
            self.logger.info("[도봉 T3] Page %s: %s권 수집 중", page, len(books))

        for book in books:
            title = book.css("dt a::text").get()
            em_text = book.css("dd em::text").get() or ""
            em_text = " ".join(em_text.split())

            # "김미희 / [ 다그림책(키다리) / 2025-07-21 ]" 형태에서 저자/출판사 추출
            author = ""
            publisher = ""
            m = re.search(r"^(.*?)\s*/\s*\[\s*(.*?)\s*/", em_text)
            if m:
                author = m.group(1).strip()
                publisher = m.group(2).strip()

            isbn = ""
            brcd = ""
            detail_href = book.css("p.pic a::attr(href)").get() or ""
            m = re.search(r"barcode=([A-Za-z0-9]+)", detail_href)
            if m:
                brcd = m.group(1)
            if not brcd:
                img_url = book.css("p.pic img::attr(src)").get() or ""
                m = re.search(r"/([A-Za-z0-9]{10,})/", img_url)
                if m:
                    brcd = m.group(1)

            image_url = book.css("p.pic img::attr(src)").get()
            if image_url and image_url.startswith("//"):
                image_url = "https:" + image_url

            if title:
                yield {
                    "title": title.strip(),
                    "author": author,
                    "publisher": publisher,
                    "library": self.library_name,
                    "platform": "Kyobo",
                    "provider": "교보문고",
                    "image_url": image_url,
                    "isbn": isbn,
                    "brcd": brcd,
                }

        next_page = page + 1
        params = {
            "product_cd": "001",
            "category_id": "",
            "content_all": "Y",
            "order_key": "STOCK_YMD",
            "search_keyword": "",
            "search_type": "",
            "search_product_cd": "",
            "list_type": "",
            "now_page": str(next_page),
            "listnum": str(self.page_size),
        }
        url = f"{self.base_url}?{urlencode(params)}"
        yield scrapy.Request(
            url,
            callback=self.parse,
            meta={"page": next_page},
            headers={"User-Agent": "Mozilla/5.0 (compatible; DobongCrawler/1.0)"},
            dont_filter=True,
        )

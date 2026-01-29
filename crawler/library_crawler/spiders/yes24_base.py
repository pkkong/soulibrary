import re
from urllib.parse import urlencode

import scrapy


class Yes24BaseSpider(scrapy.Spider):
    """
    공통 YES24 스파이더 베이스.
    자식 클래스는 아래 속성을 지정해야 함:
      - name
      - allowed_domains
      - base_url (예: https://ebook.gdlibrary.or.kr/ebook/)
      - library_name (예: "강동구립도서관")
    """

    custom_settings = {
        "FEED_EXPORT_ENCODING": "utf-8-sig",  # 윈도우/엑셀에서 깨짐 방지
    }
    batch_size = 200  # 한 번에 스케줄할 최대 페이지 수

    PROVIDER_MAP = {
        "예스24": "YES24",
        "예스이십사": "YES24",
        "yes24": "YES24",
        "예스": "YES24",
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

    @classmethod
    def normalize_provider(cls, raw: str) -> str:
        """원본 공급사 표기를 표준값으로 정규화."""
        if not raw:
            return "YES24"
        key = re.sub(r"\s+", "", raw).lower()
        for k, v in cls.PROVIDER_MAP.items():
            if key == re.sub(r"\s+", "", k).lower():
                return v
        return "YES24"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.total_pages = None
        self.scheduled_up_to = None

    def start_requests(self):
        params = {
            "mode": "total",
            "sort": "pubdt",
            "cate_id": "",
            "page_num": "1",
        }
        url = f"{self.base_url}?{urlencode(params)}"
        yield scrapy.Request(url, callback=self.parse, meta={"page": 1, "scheduled": False})

    def schedule_batch(self, start_page):
        """start_page부터 batch_size만큼 스케줄링."""
        if self.total_pages is None:
            return
        end_page = min(self.total_pages, start_page + self.batch_size - 1)
        for next_page in range(start_page, end_page + 1):
            params = {
                "mode": "total",
                "sort": "pubdt",
                "cate_id": "",
                "page_num": str(next_page),
            }
            url = f"{self.base_url}?{urlencode(params)}"
            yield scrapy.Request(url, callback=self.parse, meta={"page": next_page, "scheduled": True})
        self.scheduled_up_to = end_page

    def schedule_total_pages(self, response):
        """총 페이지 수를 계산하고 첫 배치를 스케줄링."""
        total_text = response.css("div.total::text").getall()
        if total_text:
            joined = " ".join(t.strip() for t in total_text if t.strip())
            m = re.search(r"\(\s*\d+\s*/\s*(\d+)\s*\)", joined)
            if m:
                self.total_pages = int(m.group(1))
        if not self.total_pages:
            self.total_pages = 200  # 파싱 실패 시 기본값

        # 첫 배치: 2페이지부터 batch_size만큼 스케줄
        yield from self.schedule_batch(start_page=2)

    def parse(self, response):
        page = response.meta["page"]
        books = response.css("div.bx")
        if not books:
            return

        if page == 1 and not response.meta.get("scheduled"):
            yield from self.schedule_total_pages(response)

        print(f"--- [{self.library_name}] Page {page}: {len(books)}권 ---")

        # 마지막으로 스케줄한 페이지에 도달했고 남은 페이지가 있으면 다음 배치를 스케줄
        if (
            self.total_pages
            and self.scheduled_up_to
            and page == self.scheduled_up_to
            and self.scheduled_up_to < self.total_pages
        ):
            next_start = self.scheduled_up_to + 1
            yield from self.schedule_batch(start_page=next_start)

        for book in books:
            title = book.css(".tit a::text").get()
            goods_href = book.css(".tit a::attr(href)").get() or book.css(".thumb::attr(href)").get() or ""
            goods_id = ""
            if goods_href:
                match = re.search(r"goods_id=(\d+)", goods_href)
                if match:
                    goods_id = match.group(1)
            writer_text = book.css(".writer::text").get()
            author = ""
            if writer_text:
                first_part = writer_text.split("/")[0]
                author = first_part.replace(" 저", "").strip()

            details = book.css(".detail span::text").getall()
            publisher = details[0].strip() if details else ""
            provider_raw = details[2].strip() if len(details) >= 3 else ""
            provider = self.normalize_provider(provider_raw)

            image_url = book.css(".thumb img::attr(src)").get()

            # ISBN 제공 없음 -> 항상 빈 값
            isbn = ""

            if title:
                yield {
                    "title": title.strip(),
                    "author": author,
                    "publisher": publisher,
                    "library": self.library_name,
                    "provider": provider,
                    "platform": "YES24",
                    "image_url": image_url,
                    "isbn": isbn,
                    "goods_id": goods_id,
                }

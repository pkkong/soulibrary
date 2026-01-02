from .yes24_base import Yes24BaseSpider


class YeongdeungpoYes24Spider(Yes24BaseSpider):
    name = "yeongdeungpo_yes24"
    allowed_domains = ["ebook.ydplib.or.kr"]
    base_url = "https://ebook.ydplib.or.kr/ebook/"
    library_name = "영등포구 도서관"

from .yes24_base import Yes24BaseSpider


class GangdongYes24Spider(Yes24BaseSpider):
    name = "gangdong_yes24"
    allowed_domains = ["ebook.gdlibrary.or.kr"]
    base_url = "https://ebook.gdlibrary.or.kr/ebook/"
    library_name = "강동구립도서관"

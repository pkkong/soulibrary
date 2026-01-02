from .yes24_base import Yes24BaseSpider


class GangseoYes24Spider(Yes24BaseSpider):
    name = "gangseo_yes24"
    allowed_domains = ["ebook.gangseo.seoul.kr"]
    base_url = "https://ebook.gangseo.seoul.kr/ebook/"
    library_name = "강서구 전자도서관"

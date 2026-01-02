from .yes24_base import Yes24BaseSpider


class GwanakYes24Spider(Yes24BaseSpider):
    name = "gwanak_yes24"
    allowed_domains = ["e-lib.gwanak.go.kr"]
    base_url = "https://e-lib.gwanak.go.kr/ebook/"
    library_name = "관악구통합도서관"

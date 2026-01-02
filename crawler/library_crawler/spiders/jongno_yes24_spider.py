from .yes24_base import Yes24BaseSpider


class JongnoYes24Spider(Yes24BaseSpider):
    name = "jongno_yes24"
    allowed_domains = ["elib.jongno.go.kr"]
    base_url = "https://elib.jongno.go.kr/ebook/"
    library_name = "종로구 전자도서관"

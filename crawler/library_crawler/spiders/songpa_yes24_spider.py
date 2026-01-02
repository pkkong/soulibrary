from .yes24_base import Yes24BaseSpider


class SongpaYes24Spider(Yes24BaseSpider):
    name = "songpa_yes24"
    allowed_domains = ["ebook.splib.or.kr"]
    base_url = "https://ebook.splib.or.kr/ebook/"
    library_name = "송파구 도서관 (소장)"

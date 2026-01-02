from .kyobo_new_base import KyoboNewBaseSpider


class JungnangKyoboSpider(KyoboNewBaseSpider):
    name = "jungnang_kyobo"
    allowed_domains = ["ebook.jungnanglib.seoul.kr"]
    base_url = "https://ebook.jungnanglib.seoul.kr/elibrary-front/content/contentList.ink"
    library_name = "중랑구립정보도서관"
    user_agent = "Mozilla/5.0 (compatible; JungnangCrawler/1.0)"

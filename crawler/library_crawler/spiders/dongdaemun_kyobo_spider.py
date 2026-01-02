from .kyobo_new_base import KyoboNewBaseSpider


class DongdaemunKyoboSpider(KyoboNewBaseSpider):
    name = "dongdaemun_kyobo"
    allowed_domains = ["e-book.l4d.or.kr"]
    base_url = "https://e-book.l4d.or.kr/elibrary-front/content/contentList.ink"
    library_name = "동대문구 도서관"
    user_agent = "Mozilla/5.0 (compatible; DongdaemunCrawler/1.0)"

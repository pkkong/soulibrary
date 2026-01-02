from .kyobo_new_base import KyoboNewBaseSpider


class SeongbukKyoboSpider(KyoboNewBaseSpider):
    name = "seongbuk_kyobo"
    allowed_domains = ["elibrary.sblib.seoul.kr"]
    base_url = "https://elibrary.sblib.seoul.kr/elibrary-front/content/contentList.ink"
    library_name = "성북구 도서관"
    user_agent = "Mozilla/5.0 (compatible; SeongbukCrawler/1.0)"

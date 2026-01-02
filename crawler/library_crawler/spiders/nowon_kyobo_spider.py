from .kyobo_new_base import KyoboNewBaseSpider


class NowonKyoboSpider(KyoboNewBaseSpider):
    name = "nowon_kyobo"
    allowed_domains = ["eb.nowonlib.kr"]
    base_url = "https://eb.nowonlib.kr/elibrary-front/content/contentList.ink"
    library_name = "노원구립도서관"
    user_agent = "Mozilla/5.0 (compatible; NowonCrawler/1.0)"

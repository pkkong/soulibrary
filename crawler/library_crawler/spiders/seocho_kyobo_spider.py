from .kyobo_new_base import KyoboNewBaseSpider


class SeochoKyoboSpider(KyoboNewBaseSpider):
    name = "seocho_kyobo"
    allowed_domains = ["ebook.seocholib.or.kr"]
    base_url = "https://ebook.seocholib.or.kr/elibrary-front/content/contentList.ink"
    library_name = "서초구 전자도서관"
    user_agent = "Mozilla/5.0 (compatible; SeochoCrawler/1.0)"

from .kyobo_new_base import KyoboNewBaseSpider


class DongjakKyoboSpider(KyoboNewBaseSpider):
    name = "dongjak_kyobo"
    allowed_domains = ["ebook.dongjak.go.kr"]
    base_url = "https://ebook.dongjak.go.kr/elibrary-front/content/contentList.ink"
    library_name = "동작구 구립도서관"
    user_agent = "Mozilla/5.0 (compatible; DongjakCrawler/1.0)"

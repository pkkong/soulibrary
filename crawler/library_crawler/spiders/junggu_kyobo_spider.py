from .kyobo_new_base import KyoboNewBaseSpider


class JungguKyoboSpider(KyoboNewBaseSpider):
    name = "junggu_kyobo"
    allowed_domains = ["ebook.junggulib.or.kr"]
    base_url = "https://ebook.junggulib.or.kr/elibrary-front/content/contentList.ink"
    library_name = "중구통합전자도서관"
    user_agent = "Mozilla/5.0 (compatible; JungguCrawler/1.0)"

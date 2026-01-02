from .kyobo_new_base import KyoboNewBaseSpider


class MapoKyoboSpider(KyoboNewBaseSpider):
    name = "mapo_kyobo"
    allowed_domains = ["ebook.mapo.go.kr"]
    base_url = "https://ebook.mapo.go.kr/elibrary-front/content/contentList.ink"
    library_name = "마포구 전자도서관"
    user_agent = "Mozilla/5.0 (compatible; MapoCrawler/1.0)"

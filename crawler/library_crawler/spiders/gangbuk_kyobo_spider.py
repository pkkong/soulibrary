from .kyobo_new_base import KyoboNewBaseSpider


class GangbukKyoboSpider(KyoboNewBaseSpider):
    name = "gangbuk_kyobo"
    allowed_domains = ["ebook.gblib.or.kr"]
    base_url = "https://ebook.gblib.or.kr/elibrary-front/content/contentList.ink"
    library_name = "강북문화정보도서관"
    user_agent = "Mozilla/5.0 (compatible; GangbukCrawler/1.0)"

from .kyobo_new_base import KyoboNewBaseSpider


class YongsanKyoboSpider(KyoboNewBaseSpider):
    name = "yongsan_kyobo"
    allowed_domains = ["ebook.yslibrary.or.kr"]
    base_url = "https://ebook.yslibrary.or.kr/elibrary-front/content/contentList.ink"
    library_name = "용산구 전자도서관"
    image_prefix = "https://ebook.yslibrary.or.kr"
    user_agent = "Mozilla/5.0 (compatible; YongsanCrawler/1.0)"

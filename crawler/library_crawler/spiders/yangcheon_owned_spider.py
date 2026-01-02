from .kyobo_new_base import KyoboNewBaseSpider


class YangcheonOwnedSpider(KyoboNewBaseSpider):
    name = "yangcheon_owned"
    allowed_domains = ["ebook.yangcheon.or.kr"]
    base_url = "https://ebook.yangcheon.or.kr/elibrary-front/content/contentList.ink"
    library_name = "양천구립도서관 (소장)"
    user_agent = "Mozilla/5.0 (compatible; YangcheonOwnedCrawler/1.0)"

from .kyobo_new_base import KyoboNewBaseSpider


class SeodaemunOwnedSpider(KyoboNewBaseSpider):
    name = "seodaemun_owned"
    allowed_domains = ["ebook.sdm.or.kr"]
    base_url = "https://ebook.sdm.or.kr/elibrary-front/content/contentList.ink"
    library_name = "서대문구립도서관 (소장)"
    user_agent = "Mozilla/5.0 (compatible; SeodaemunOwnedCrawler/1.0)"

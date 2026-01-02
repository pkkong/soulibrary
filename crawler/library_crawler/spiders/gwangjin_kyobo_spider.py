from .kyobo_new_base import KyoboNewBaseSpider


class GwangjinKyoboSpider(KyoboNewBaseSpider):
    name = "gwangjin_kyobo"
    allowed_domains = ["ebook.gwangjinlib.seoul.kr"]
    base_url = "https://ebook.gwangjinlib.seoul.kr:446/elibrary-front/content/contentList.ink"
    library_name = "광진구립도서관 (소장)"
    user_agent = "Mozilla/5.0 (compatible; GwangjinCrawler/1.0)"

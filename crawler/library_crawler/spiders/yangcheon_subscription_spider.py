from .kyobo_new_base import KyoboNewBaseSpider


class YangcheonSubscriptionSpider(KyoboNewBaseSpider):
    name = "yangcheon_subscription"
    allowed_domains = ["yclib.dkyobobook.co.kr"]
    base_url = "https://yclib.dkyobobook.co.kr/content/contentList.ink"
    library_name = "양천구립도서관 (구독)"
    user_agent = "Mozilla/5.0 (compatible; YangcheonSubsCrawler/1.0)"
    # 대규모 소장분(19만권대) 대비 페이지 상한 확장
    max_pages_cap = 3000

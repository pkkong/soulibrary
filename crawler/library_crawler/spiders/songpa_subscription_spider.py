from .kyobo_new_base import KyoboNewBaseSpider


class SongpaSubscriptionSpider(KyoboNewBaseSpider):
    name = "songpa_subscription"
    allowed_domains = ["splib.dkyobobook.co.kr"]
    base_url = "https://splib.dkyobobook.co.kr/content/contentList.ink"
    library_name = "송파구립도서관 (구독)"
    user_agent = "Mozilla/5.0 (compatible; SongpaSubsCrawler/1.0)"
    # 대규모 소장분(19만권대) 대비 페이지 상한 확장
    max_pages_cap = 3000

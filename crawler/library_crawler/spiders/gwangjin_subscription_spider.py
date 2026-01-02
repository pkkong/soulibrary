from .kyobo_new_base import KyoboNewBaseSpider


class GwangjinSubscriptionSpider(KyoboNewBaseSpider):
    name = "gwangjin_subscription"
    allowed_domains = ["gwangjin.dkyobobook.co.kr"]
    base_url = "https://gwangjin.dkyobobook.co.kr/content/contentList.ink"
    library_name = "광진구립도서관 (구독)"
    # Large collection (~190k), so raise page cap from default 600 to avoid truncation.
    max_pages_cap = 3000
    user_agent = "Mozilla/5.0 (compatible; GwangjinSubCrawler/1.0)"

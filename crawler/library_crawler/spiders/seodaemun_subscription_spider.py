from .kyobo_new_base import KyoboNewBaseSpider


class SeodaemunSubscriptionSpider(KyoboNewBaseSpider):
    name = "seodaemun_subscription"
    allowed_domains = ["sdmlib.dkyobobook.co.kr"]
    base_url = "https://sdmlib.dkyobobook.co.kr/content/contentList.ink"
    library_name = "서대문구립도서관 (구독)"
    # Large collection (~195k), so raise page cap from default 600 to avoid truncation.
    max_pages_cap = 3000
    user_agent = "Mozilla/5.0 (compatible; SeodaemunSubsCrawler/1.0)"

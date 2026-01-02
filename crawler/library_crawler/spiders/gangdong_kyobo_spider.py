from .kyobo_new_base import KyoboNewBaseSpider


class GangdongKyoboSpider(KyoboNewBaseSpider):
    name = "gangdong_kyobo"
    allowed_domains = ["gdlib.dkyobobook.co.kr"]
    base_url = "https://gdlib.dkyobobook.co.kr/content/contentList.ink"
    library_name = "강동구립도서관 (구독)"
    # Large collection (~180k), so raise page cap from default 600 to avoid truncation.
    max_pages_cap = 3000
    user_agent = "Mozilla/5.0 (compatible; GangdongSubsCrawler/1.0)"

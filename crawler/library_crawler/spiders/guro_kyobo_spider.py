from .kyobo_new_base import KyoboNewBaseSpider


class GuroKyoboSpider(KyoboNewBaseSpider):
    name = "guro_kyobo"
    allowed_domains = ["ebook.guro.go.kr"]
    base_url = "https://ebook.guro.go.kr/elibrary-front/content/contentList.ink"
    # 구로는 recordCount=20 으로 동작 확인됨
    page_size = 20
    library_name = "구로구립도서관"
    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    # TLS 호환성 문제를 완화하기 위해 seclevel=0, TLSv1.2 강제 (구로 전용)
    custom_settings = {
        "DOWNLOADER_CLIENT_TLS_METHOD": "TLSv1.2",
        "DOWNLOADER_CLIENT_TLS_CIPHERS": "DEFAULT:@SECLEVEL=0",
    }

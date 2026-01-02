"""
Kyobo 신버전 도서관 빠른 건강검진 스크립트.
- web/config.py에서 platform == "Kyobo_New"인 도서관만 대상으로 함
- 총 장서수 표기(total_count_url)와 1페이지 목록 요청을 테스트
- 결과: 성공/실패, 총 권수 파싱, 첫 페이지 도서 샘플(title/author/isbn) 출력

실행:
    python crawler/test_kyobo_new.py
"""

import json
import sys
from importlib import import_module
from urllib.parse import urlencode, urlparse, urlunparse

import requests
import urllib3
import ssl
from requests.adapters import HTTPAdapter
import re

# HTTPS 검증을 끈 요청을 사용하므로 경고 숨김
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class TLSAdapter(HTTPAdapter):
    """커스텀 SSL 컨텍스트를 쓰기 위한 어댑터."""

    def __init__(self, ssl_context=None, **kwargs):
        self.ssl_context = ssl_context
        super().__init__(**kwargs)

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        pool_kwargs["ssl_context"] = self.ssl_context
        return super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)

sys.path.append(".")
sys.path.append("..")
sys.path.append("../..")

try:
    from web.config import LIBRARIES
except ImportError:
    print("[ERROR] web.config import 실패. 작업 디렉터리를 프로젝트 루트로 맞춰주세요.")
    sys.exit(1)

# 대상 스파이더 모듈/클래스 경로
SPIDER_PATHS = {
    "yongsan": "crawler.library_crawler.spiders.yongsan_kyobo_spider.YongsanKyoboSpider",
    "mapo": "crawler.library_crawler.spiders.mapo_kyobo_spider.MapoKyoboSpider",
    "gangbuk": "crawler.library_crawler.spiders.gangbuk_kyobo_spider.GangbukKyoboSpider",
    "gwangjin": "crawler.library_crawler.spiders.gwangjin_kyobo_spider.GwangjinKyoboSpider",
    "gwangjin_subs": "crawler.library_crawler.spiders.gwangjin_subscription_spider.GwangjinSubscriptionSpider",
    "gangdong_subs": "crawler.library_crawler.spiders.gangdong_kyobo_spider.GangdongKyoboSpider",
    "junggu": "crawler.library_crawler.spiders.junggu_kyobo_spider.JungguKyoboSpider",
    "jungnang": "crawler.library_crawler.spiders.jungnang_kyobo_spider.JungnangKyoboSpider",
    "nowon": "crawler.library_crawler.spiders.nowon_kyobo_spider.NowonKyoboSpider",
    "guro": "crawler.library_crawler.spiders.guro_kyobo_spider.GuroKyoboSpider",
    "seodaemun_owned": "crawler.library_crawler.spiders.seodaemun_owned_spider.SeodaemunOwnedSpider",
    "seodaemun_subs": "crawler.library_crawler.spiders.seodaemun_subscription_spider.SeodaemunSubscriptionSpider",
}


def load_spider_info(lib_code):
    """
    spider 클래스에서 base_url 등 속성을 읽어온다.
    """
    path = SPIDER_PATHS.get(lib_code)
    if not path:
        return None
    module_path, class_name = path.rsplit(".", 1)
    module = import_module(module_path)
    klass = getattr(module, class_name)
    return {
        "base_url": klass.base_url,
        "page_size": getattr(klass, "page_size", 80),
        "ua": getattr(klass, "user_agent", "Mozilla/5.0 (compatible; KyoboNewTest/1.0)"),
    }


def fetch_total_count(url, ua):
    def _parse_total(html):
        try:
            import lxml.html
            doc = lxml.html.fromstring(html)
            texts = doc.xpath('//div[contains(@class,"book_resultTxt")]//strong/text()')
            candidates = []
            for t in texts:
                digits = re.sub(r"[^\d,]", "", t)
                if digits:
                    candidates.append(int(digits.replace(",", "")))
            if candidates:
                return max(candidates)
        except Exception:
            pass
        m = re.search(r"총[\s\u00a0]*([\d,]+)[\s\u00a0]*개", html)
        if m:
            return int(m.group(1).replace(",", ""))
        return None

    try:
        parsed = urlparse(url)
        is_guro = "ebook.guro.go.kr" in parsed.netloc

        if is_guro:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            try:
                ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
            except ssl.SSLError:
                try:
                    ctx.set_ciphers("DEFAULT")
                except ssl.SSLError:
                    pass
            session = requests.Session()
            adapter = TLSAdapter(ssl_context=ctx)
            session.mount("https://", adapter)
            res = session.get(
                url,
                headers={"User-Agent": ua},
                timeout=8,
                verify=False,
                allow_redirects=True,
            )
        else:
            res = requests.get(
                url,
                headers={"User-Agent": ua},
                timeout=8,
            )
        res.raise_for_status()
        total = _parse_total(res.text)
        if total is not None:
            return total
    except Exception as e:
        return f"error: {e}"
    return "parse-fail"


def fetch_first_page(base_url, page_size, ua):
    params = {
        "brcd": "",
        "sntnAuthCode": "",
        "contentAll": "Y",
        "cttsDvsnCode": "001",
        "ctgrId": "",
        "orderByKey": "publDate",
        "selViewCnt": str(page_size),
        "pageIndex": "1",
        "recordCount": str(page_size),
    }
    url = f"{base_url}?{urlencode(params)}"
    try:
        parsed = urlparse(url)
        is_guro = parsed.hostname == "ebook.guro.go.kr"

        # 구로: https + TLS seclevel 완화
        if is_guro:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            try:
                ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
            except ssl.SSLError:
                try:
                    ctx.set_ciphers("DEFAULT")
                except ssl.SSLError:
                    pass
            session = requests.Session()
            adapter = TLSAdapter(ssl_context=ctx)
            session.mount("https://", adapter)
            res = session.get(
                url,
                headers={"User-Agent": ua},
                timeout=8,
                verify=False,
                allow_redirects=True,
            )
        else:
            res = requests.get(
                url,
                headers={"User-Agent": ua},
                timeout=8,
                verify=False,
                allow_redirects=True,
            )
        res.raise_for_status()
        # 간단히 제목 3개 추출
        import lxml.html

        doc = lxml.html.fromstring(res.content)
        titles = doc.xpath('//li[.//li[@class="tit"]]//li[@class="tit"]/a/text()')
        return {"count": len(titles), "titles": titles[:3]}
    except Exception as e:
        return {"error": str(e)}


def main():
    kyobo_new_libs = {
        code: info
        for code, info in LIBRARIES.items()
        if info.get("platform") == "Kyobo_New"
    }
    results = {}
    for code, info in kyobo_new_libs.items():
        spider_info = load_spider_info(code)
        if not spider_info:
            results[code] = {"error": "spider path missing"}
            continue
        ua = spider_info["ua"]
        total_url = info.get("total_count_url")
        total = fetch_total_count(total_url, ua) if total_url else "no-total-url"
        first_page = fetch_first_page(
            spider_info["base_url"], spider_info["page_size"], ua
        )
        results[code] = {
            "name": info.get("name"),
            "total_count": total,
            "first_page": first_page,
        }

    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

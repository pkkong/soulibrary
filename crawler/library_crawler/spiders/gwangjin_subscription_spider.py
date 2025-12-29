import scrapy
import re
from urllib.parse import urlencode

class GwangjinSubscriptionSpider(scrapy.Spider):
    name = "gwangjin_subscription"
    allowed_domains = ["gwangjin.dkyobobook.co.kr"]
    
    # 광진구 구독형 전자도서관 (교보 신버전)
    base_url = "https://gwangjin.dkyobobook.co.kr/content/contentList.ink"
    
    def start_requests(self):
        # 🚀 [속도 최적화] 1~500페이지
        max_page = 500
        
        for page in range(1, max_page + 1):
            params = {
                'contentAll': 'Y',      # 전체 보기
                'cttsDvsnCode': '001',  # 전자책
                'orderByKey': 'publDate', # 최신순
                'selViewCnt': '80',       # URL 기준 80개
                'pageIndex': str(page),
                'recordCount': '20'
            }
            url = f"{self.base_url}?{urlencode(params)}"
            yield scrapy.Request(url, callback=self.parse, meta={'page': page})

    def parse(self, response):
        page = response.meta['page']
        
        # 🎯 교보문고 신버전 공통 XPath
        books = response.xpath('//li[.//li[@class="tit"]]')
        
        if not books:
            return

        if page % 10 == 0:
            print(f"--- [광진구(구독)] Page {page}: {len(books)}권 수집 중 ---")

        for book in books:
            # 1. 제목
            title = book.css("li.tit a::text").get()
            
            # 2. 저자 / 출판사
            # 구조: <li class="writer">백승원 (핑크소이)<span>덱스(DEX)</span>2025-12-29</li>
            writer_texts = book.css("li.writer::text").getall()
            author = writer_texts[0].strip() if writer_texts else ""
            publisher = book.css("li.writer span::text").get() or ""

            # 3. 이미지 URL
            image_url = book.css("div.img a img::attr(src)").get()
            if image_url and image_url.startswith("//"):
                image_url = "https:" + image_url
            
            # 4. ISBN (이미지 URL에서 추출)
            isbn = ""
            if image_url:
                # 구독형은 ID에 알파벳(N 등)이 섞일 수 있음 (\w+)
                match = re.search(r'/(\w+)/L\1', image_url)
                if match:
                    isbn = match.group(1)
            
            if title:
                yield {
                    'title': title.strip(),
                    'author': author,
                    'publisher': publisher,
                    'library': "광진구립도서관(구독)",
                    'platform': "교보문고(구독)",
                    'image_url': image_url,
                    'isbn': isbn
                }
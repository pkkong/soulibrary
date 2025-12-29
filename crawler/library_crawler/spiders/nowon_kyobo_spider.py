import scrapy
import re
from urllib.parse import urlencode

class NowonKyoboSpider(scrapy.Spider):
    name = "nowon_kyobo"
    allowed_domains = ["eb.nowonlib.kr"]
    
    # 노원구 전자도서관 (교보 신버전)
    base_url = "https://eb.nowonlib.kr/elibrary-front/content/contentList.ink"
    
    def start_requests(self):
        # 🚀 [속도 최적화] 1~500페이지 (약 2.4만 권 예상)
        max_page = 500
        
        for page in range(1, max_page + 1):
            params = {
                'brcd': '',
                'sntnAuthCode': '',
                'contentAll': 'Y',      # 전체 보기
                'cttsDvsnCode': '001',  # 전자책
                'ctgrId': '',
                'orderByKey': 'publDate', # 최신순
                'selViewCnt': '80',       # 80개씩 (URL 기준)
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
            print(f"--- [노원구] Page {page}: {len(books)}권 수집 중 ---")

        for book in books:
            # 1. 제목
            title = book.css("li.tit a::text").get()
            
            # 2. 저자 / 출판사 파싱
            # 구조: <li class="writer">헨리 키신저<span>윌북</span>2025-08-14</li>
            
            # (1) 저자
            writer_texts = book.css("li.writer::text").getall()
            author = writer_texts[0].strip() if writer_texts else ""
            
            # (2) 출판사
            publisher = book.css("li.writer span::text").get() or ""

            # 3. 이미지 URL
            image_url = book.css("div.img a img::attr(src)").get()
            
            # 프로토콜 처리
            if image_url and image_url.startswith("//"):
                image_url = "https:" + image_url
            
            # 4. ISBN (이미지 URL에서 추출)
            # 예: .../4801155818443/L4801155818443.jpg
            isbn = ""
            if image_url:
                match = re.search(r'/(\d+)/L\1', image_url)
                if match:
                    isbn = match.group(1)
            
            if title:
                yield {
                    'title': title.strip(),
                    'author': author,
                    'publisher': publisher,
                    'library': "노원구립도서관",
                    'platform': "교보문고(신버전)",
                    'image_url': image_url,
                    'isbn': isbn
                }
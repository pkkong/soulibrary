import scrapy
import re
from urllib.parse import urlencode

class JungnangKyoboSpider(scrapy.Spider):
    name = "jungnang_kyobo"
    allowed_domains = ["ebook.jungnanglib.seoul.kr"]
    
    # 중랑구 전자도서관 기본 주소
    base_url = "https://ebook.jungnanglib.seoul.kr/elibrary-front/content/contentList.ink"
    
    def start_requests(self):
        # 🚀 [속도 최적화] 1~500페이지 (약 2.5만 권 예상)
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
            print(f"--- [중랑구] Page {page}: {len(books)}권 수집 중 ---")

        for book in books:
            # 1. 제목
            title = book.css("li.tit a::text").get()
            
            # 2. 저자 / 출판사 파싱
            # 예: "크러스너호르커이 라슬로 저자, 노승영 번역<span>알마</span>2025-11-20"
            
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
            # 예: .../480D251018340/L480D251018340.jpg
            isbn = ""
            if image_url:
                match = re.search(r'/(\w+)/L\1', image_url)
                if match:
                    isbn = match.group(1)
            
            if title:
                yield {
                    'title': title.strip(),
                    'author': author,
                    'publisher': publisher,
                    'library': "중랑구립정보도서관",
                    'platform': "교보문고(신버전)",
                    'image_url': image_url,
                    'isbn': isbn
                }
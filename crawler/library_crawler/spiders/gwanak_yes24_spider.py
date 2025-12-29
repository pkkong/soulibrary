import scrapy
import re
from urllib.parse import urlencode

class GwanakYes24Spider(scrapy.Spider):
    name = "gwanak_yes24"
    allowed_domains = ["e-lib.gwanak.go.kr"]
    
    # 관악구 통합도서관(YES24) 기본 주소
    base_url = "https://e-lib.gwanak.go.kr/ebook/"
    
    def start_requests(self):
        # 🚀 [속도 최적화] 1~200페이지 (약 4000권 예상)
        max_page = 200
        
        for page in range(1, max_page + 1):
            params = {
                'mode': 'total',
                'sort': 'pubdt', # 최신순
                'cate_id': '',
                'page_num': str(page)
            }
            url = f"{self.base_url}?{urlencode(params)}"
            yield scrapy.Request(url, callback=self.parse, meta={'page': page})

    def parse(self, response):
        page = response.meta['page']
        
        # 🎯 YES24 표준 선택자 (div.bx)
        books = response.css("div.bx")
        
        if not books:
            return

        if page % 10 == 0:
            print(f"--- [관악구] Page {page}: {len(books)}권 수집 중 ---")

        for book in books:
            # 1. 제목: p.tit 안의 a 태그 텍스트
            # (앞에 있는 <strong>[카테고리]</strong>는 제외됨)
            title = book.css("p.tit a::text").get()
            
            # 2. 저자: p.writer 텍스트
            # 예: "뤽 크루제 저/김경수 역"
            writer_text = book.css("p.writer::text").get()
            author = ""
            if writer_text:
                parts = writer_text.split('/')
                author = parts[0].replace(' 저', '').strip()

            # 3. 출판사: p.detail 안의 첫 번째 span
            # <span>부크온</span><span>2025-10-10</span>...
            publisher = book.css("p.detail span:nth-child(1)::text").get()

            # 4. 이미지 URL
            image_url = book.css("a.thumb img::attr(src)").get()
            
            # 5. ISBN (이미지 URL의 숫자 부분 추출)
            # 예: https://image.yes24.com/goods/154298576/XL -> 154298576
            isbn = ""
            if image_url:
                match = re.search(r'/goods/(\d+)/', image_url)
                if not match:
                    # goods가 없는 패턴일 수도 있으니 숫자만 추출
                    match = re.search(r'(\d+)', image_url)
                
                if match:
                    isbn = match.group(1)
            
            if title:
                yield {
                    'title': title.strip(),
                    'author': author,
                    'publisher': publisher,
                    'library': "관악구통합도서관",
                    'platform': "YES24",
                    'image_url': image_url,
                    'isbn': isbn
                }
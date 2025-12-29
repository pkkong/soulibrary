import scrapy
import re
from urllib.parse import urlencode

class GangbukKyoboSpider(scrapy.Spider):
    name = "gangbuk_kyobo"
    allowed_domains = ["ebook.gblib.or.kr"]
    
    # 강북구는 구버전(T3) 주소를 사용합니다.
    base_url = "https://ebook.gblib.or.kr/Kyobo_T3/Content/ebook/ebook_Main.asp"
    
    def start_requests(self):
        # 🚀 [속도 최적화] 1~500페이지 (약 1~2만 권 예상)
        max_page = 500
        
        for page in range(1, max_page + 1):
            params = {
                'product_cd': '001',       # 전자책
                'category_id': '',
                'content_all': 'Y',        # 전체 보기
                'order_key': 'STOCK_YMD',  # 최신순
                'now_page': str(page)      # 페이지 번호
            }
            url = f"{self.base_url}?{urlencode(params)}"
            yield scrapy.Request(url, callback=self.parse, meta={'page': page})

    def parse(self, response):
        page = response.meta['page']
        
        # 🎯 구버전(T3) 표준 선택자: id가 content_로 시작하는 li 태그
        books = response.css('li[id^="content_"]')
        
        if not books:
            return

        if page % 10 == 0:
            print(f"--- [강북구] Page {page}: {len(books)}권 수집 중 ---")

        for book in books:
            # 1. 제목: <dl> -> <dt> -> <a> 텍스트
            title = book.css("dl dt a::text").get()
            
            # 2. 저자/출판사 파싱: <dl> -> <dd> -> <em> 텍스트
            # 예: "김미희 / [ 다그림책(키다리) / 2025-07-21 ]"
            meta_text = book.css("dl dd em::text").get()
            author = ""
            publisher = ""
            
            if meta_text:
                meta_text = meta_text.strip()
                parts = meta_text.split('/')
                
                # 저자 (첫 번째 조각)
                if len(parts) >= 1:
                    author = parts[0].strip()
                
                # 출판사 (두 번째 조각)
                if len(parts) >= 2:
                    raw_pub = parts[1].strip()
                    # 대괄호 '[' 제거
                    publisher = raw_pub.replace('[', '').replace(']', '').strip()

            # 3. 이미지 URL: <p class="pic"> -> <img> src
            image_url = book.css("p.pic img::attr(src)").get()
            
            # 4. ISBN 추출 (이미지 URL 활용)
            isbn = ""
            if image_url:
                match = re.search(r'(\d{13})', image_url)
                if match:
                    isbn = match.group(1)
            
            if title:
                yield {
                    'title': title.strip(),
                    'author': author,
                    'publisher': publisher,
                    'library': "강북문화정보도서관",
                    'platform': "교보문고", # 구버전은 그냥 '교보문고'로 표기해도 무방
                    'image_url': image_url,
                    'isbn': isbn
                }
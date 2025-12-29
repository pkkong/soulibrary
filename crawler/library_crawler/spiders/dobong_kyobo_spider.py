import scrapy
import re
from urllib.parse import urlencode

class DobongKyoboSpider(scrapy.Spider):
    name = "dobong_kyobo"
    allowed_domains = ["elib.dobong.kr"]
    
    # 기본 주소 (도봉구 교보문고 T3)
    base_url = "https://elib.dobong.kr/Kyobo_T3/Content/ebook/ebook_Main.asp"
    
    def start_requests(self):
        # 🚀 [속도 최적화] 1~500페이지 병렬 요청 (약 1만 권 수집 예상)
        # 도봉구 장서 규모에 따라 max_page를 조절하세요.
        max_page = 500 
        
        for page in range(1, max_page + 1):
            params = {
                'product_cd': '001',       # 전자책
                'category_id': '',
                'content_all': 'Y',        # 전체 보기
                'order_key': 'STOCK_YMD',  # 최신순
                'now_page': str(page)      # 페이지 번호
            }
            # urlencode를 쓰면 파라미터를 안전하게 합쳐줍니다.
            url = f"{self.base_url}?{urlencode(params)}"
            yield scrapy.Request(url, callback=self.parse, meta={'page': page})

    def parse(self, response):
        page = response.meta['page']
        
        # 🎯 [핵심] 우리가 분석한 'li id="content_..."' 선택자
        books = response.css('li[id^="content_"]')
        
        if not books:
            return

        # 로그 출력 (10페이지마다)
        if page % 10 == 0:
            print(f"--- [도봉구] Page {page}: {len(books)}권 수집 중 ---")

        for book in books:
            # 1. 제목: <dl> -> <dt> -> <a> 텍스트
            title = book.css("dl dt a::text").get()
            
            # 2. 저자/출판사 파싱: <dl> -> <dd> -> <em> 텍스트
            # 예: "김미희 / [ 다그림책(키다리) / 2025-07-21 ]"
            meta_text = book.css("dl dd em::text").get()
            author = ""
            publisher = ""
            
            if meta_text:
                # 불필요한 공백 제거
                meta_text = meta_text.strip()
                # '/' 기준으로 자르기
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
            
            # 4. ISBN (이미지 URL에서 추출)
            # 예: .../ebook/4801198960123/L4801198960123.jpg -> 4801198960123
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
                    'library': "도봉구립도서관",
                    'platform': "교보문고",
                    'image_url': image_url,
                    'isbn': isbn
                }
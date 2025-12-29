import scrapy
import re
from urllib.parse import urlencode

class SeongdongFxSpider(scrapy.Spider):
    name = "seongdong_fx"
    allowed_domains = ["ebook.sdlib.or.kr"]
    base_url = "https://ebook.sdlib.or.kr/FxLibrary/product/list/"
    
    def start_requests(self):
        # 🚀 [속도 최적화] 
        # 한 페이지에 100권씩 요청
        # 총 7만 권 이상이므로 넉넉하게 1,000페이지(10만 권 분량)까지 돌립니다.
        max_page = 1000 
        
        for page in range(1, max_page + 1):
            params = {
                'itemdv': '1',
                'sort': '3',        # 최신순
                'page': str(page),
                'itemCount': '100', # 👈 100권씩 요청 (고속 모드)
                'pageCount': '10',
                'cateopt': 'total'
            }
            url = f"{self.base_url}?{urlencode(params)}"
            yield scrapy.Request(url, callback=self.parse, meta={'page': page})

    def parse(self, response):
        page = response.meta['page']
        
        # 성동구(FxLibrary) 리스트 선택자
        books = response.css("li.item")
        
        if not books:
            return

        # 로그 출력 (10페이지마다 한 번씩만 출력해서 로그창 도배 방지)
        if page % 10 == 0:
            print(f"--- [성동구] Page {page}: {len(books)}권 수집 중 ---")

        for book in books:
            # 1. 제목
            title = book.css(".subject a::text").get()
            
            # 2. 저자 / 출판사 / 플랫폼
            # 구조: <div class="info"> <ul class="i1"> ... </ul> </div>
            # 첫 번째 ul.i1: [저자, 출판사, 날짜]
            # 두 번째 ul.i1: [공급사, 지원단말기]
            
            author = ""
            publisher = ""
            platform = "FxLibrary" # 기본값
            
            # (1) 저자 (첫 번째 ul의 첫 번째 li)
            # "강희중 저" -> "강희중"
            author_text = "".join(book.css(".info ul.i1:nth-of-type(1) li:nth-child(1) ::text").getall())
            author = author_text.replace('저', '').strip()
            
            # (2) 출판사 (첫 번째 ul의 두 번째 li)
            publisher = book.css(".info ul.i1:nth-of-type(1) li:nth-child(2) a::text").get()
            if not publisher:
                publisher = "".join(book.css(".info ul.i1:nth-of-type(1) li:nth-child(2) ::text").getall()).strip()

            # (3) 플랫폼 (두 번째 ul의 첫 번째 li)
            # "공급 : 교보문고 전자책 (2025...)" -> "교보문고 전자책"
            supply_text = "".join(book.css(".info ul.i1:nth-of-type(2) li:first-child ::text").getall())
            if "공급" in supply_text:
                # "공급 : " 제거 및 괄호 앞부분만 추출
                parts = supply_text.split(':')
                if len(parts) > 1:
                    platform = parts[1].split('(')[0].strip()

            # 3. 이미지 URL
            image_url = book.css(".thumb img::attr(src)").get()
            
            # 4. ISBN 추출 (이미지 URL에서)
            # 예: .../4801166546724/L4801166546724.jpg
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
                    'library': f"성동구립도서관({platform})", # 플랫폼 정보 포함
                    'platform': platform,
                    'image_url': image_url,
                    'isbn': isbn
                }
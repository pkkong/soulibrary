import scrapy
import re
from urllib.parse import urlencode

class GangdongYes24Spider(scrapy.Spider):
    name = "gangdong_yes24"
    allowed_domains = ["ebook.gdlibrary.or.kr"]
    
    # 강동구 소장형 메인 주소
    base_url = "https://ebook.gdlibrary.or.kr/ebook/"
    
    def start_requests(self):
        # 🚀 [속도 최적화] 1~100페이지 병렬 요청
        max_page = 100 
        
        for page in range(1, max_page + 1):
            # 강동구 URL 패턴
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
        
        # 🎯 [핵심 수정] 책 한 권을 감싸는 껍데기는 'div.bx' 입니다!
        books = response.css("div.bx")
        
        if not books:
            return

        print(f"--- [강동구(소장)] Page {page}: {len(books)}권 수집 중 ---")

        for book in books:
            # 1. 제목: class="tit" 안에 있는 a 태그의 텍스트
            title = book.css(".tit a::text").get()
            
            # 2. 저자: class="writer" 텍스트 (예: "민디 펠츠 저/이영래 역/...")
            writer_text = book.css(".writer::text").get()
            author = ""
            if writer_text:
                # '/'로 쪼개서 첫 번째 덩어리("민디 펠츠 저") 가져오기
                first_part = writer_text.split('/')[0]
                # ' 저' 글자 제거
                author = first_part.replace(' 저', '').strip()

            # 3. 출판사: class="detail" 안의 첫 번째 span
            # <p class="detail"> <span>북드림</span> ... </p>
            details = book.css(".detail span::text").getall()
            publisher = ""
            if details:
                publisher = details[0].strip() # 첫 번째 span이 출판사

            # 4. 이미지 URL
            image_url = book.css(".thumb img::attr(src)").get()
            
            # 5. ISBN 추출 (이미지 URL에서 13자리 숫자 찾기)
            # 예: https://image.yes24.com/goods/159536888/M -> 이건 상품번호라 ISBN 아님
            # 정규식으로 978로 시작하는 13자리만 엄격하게 찾습니다.
            isbn = ""
            if image_url:
                match = re.search(r'(97[89]\d{10})', image_url)
                if match:
                    isbn = match.group(1)
            
            if title:
                yield {
                    'title': title.strip(),
                    'author': author,
                    'publisher': publisher,
                    'library': "강동구립도서관", # (소장)
                    'platform': "YES24",
                    'image_url': image_url,
                    'isbn': isbn # (없으면 빈칸으로 들어감 -> app.py가 이름으로 묶어줌)
                }
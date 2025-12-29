import scrapy
import re
from urllib.parse import urlencode

class SeodaemunSubscriptionSpider(scrapy.Spider):
    name = "seodaemun_subscription"
    allowed_domains = ["sdmlib.dkyobobook.co.kr"]
    
    # 서대문구 구독형 기본 주소
    base_url = "https://sdmlib.dkyobobook.co.kr/content/contentList.ink"
    
    def start_requests(self):
        # 🚀 [속도 최적화] 1~500페이지 (약 2만 권 예상)
        max_page = 500
        
        for page in range(1, max_page + 1):
            params = {
                'brcd': '',
                'sntnAuthCode': '',
                'contentAll': 'Y',      # 전체 보기
                'cttsDvsnCode': '001',  # 전자책 코드
                'ctgrId': '',
                'orderByKey': 'publDate', # 최신순 정렬
                'selViewCnt': '40',       # 40개씩 보기
                'pageIndex': str(page),
                'recordCount': '40'
            }
            url = f"{self.base_url}?{urlencode(params)}"
            yield scrapy.Request(url, callback=self.parse, meta={'page': page})

    def parse(self, response):
        page = response.meta['page']
        
        # 🎯 리스트 아이템 선택 (제공해주신 HTML의 li 태그)
        # 구체적으로 ul.list_type01 > li 또는 div.list_book > ul > li 구조일 가능성이 높음
        # 일단 광범위하게 li.tit를 가진 li를 찾습니다.
        books = response.xpath('//li[.//li[@class="tit"]]')
        
        if not books:
            return

        if page % 10 == 0:
            print(f"--- [서대문구(구독)] Page {page}: {len(books)}권 수집 중 ---")

        for book in books:
            # 1. 제목: ul > li.tit > a 텍스트
            title = book.css("li.tit a::text").get()
            
            # 2. 저자 / 출판사 파싱
            # 구조: <li class="writer">저자<span>출판사</span>날짜</li>
            
            # (1) 저자: li.writer의 바로 아래 텍스트 노드
            # ::text를 쓰면 ["중앙일보S", "2025-12-29"] 처럼 리스트로 나옴
            writer_texts = book.css("li.writer::text").getall()
            author = writer_texts[0].strip() if writer_texts else ""
            
            # (2) 출판사: li.writer > span 텍스트
            publisher = book.css("li.writer span::text").get() or ""

            # 3. 이미지 URL: div.img > a > img src
            image_url = book.css("div.img a img::attr(src)").get()
            # 프로토콜 없는 URL(//...) 처리
            if image_url and image_url.startswith("//"):
                image_url = "https:" + image_url
            
            # 4. ISBN (이미지 URL에서 추출)
            # 예: .../480N251285480/L480N251285480.jpg -> 480N251285480
            # 숫자+알파벳 혼합일 수 있으므로 \w+ 사용
            isbn = ""
            if image_url:
                match = re.search(r'/(\w+)/L\1', image_url) # 파일명 패턴 활용
                if match:
                    isbn = match.group(1)
            
            if title:
                yield {
                    'title': title.strip(),
                    'author': author,
                    'publisher': publisher,
                    'library': "서대문구립도서관(구독)",
                    'platform': "교보문고(신버전)",
                    'image_url': image_url,
                    'isbn': isbn
                }
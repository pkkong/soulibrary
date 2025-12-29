import scrapy
import re
from urllib.parse import urlencode

class SeodaemunOwnedSpider(scrapy.Spider):
    name = "seodaemun_owned"
    allowed_domains = ["ebook.sdm.or.kr"]
    
    # 서대문구 소장형 기본 주소 (URL이 다름)
    base_url = "https://ebook.sdm.or.kr/elibrary-front/content/contentList.ink"
    
    def start_requests(self):
        # 🚀 [속도 최적화] 1~200페이지 (약 1.6만 권 예상)
        # 소장형은 보통 구독형보다 권수가 적으므로 200페이지 정도면 충분할 것입니다.
        max_page = 200
        
        for page in range(1, max_page + 1):
            params = {
                'brcd': '',
                'sntnAuthCode': '',
                'contentAll': 'Y',      # 전체 보기
                'cttsDvsnCode': '001',  # 전자책 코드
                'ctgrId': '',
                'orderByKey': 'publDate', # 최신순
                'selViewCnt': '80',       # 80개씩 보기 (URL에 80으로 되어 있어 효율적)
                'pageIndex': str(page),
                'recordCount': '20'
            }
            url = f"{self.base_url}?{urlencode(params)}"
            yield scrapy.Request(url, callback=self.parse, meta={'page': page})

    def parse(self, response):
        page = response.meta['page']
        
        # 🎯 리스트 아이템 선택 (구독형과 동일한 XPath 사용)
        books = response.xpath('//li[.//li[@class="tit"]]')
        
        if not books:
            return

        if page % 10 == 0:
            print(f"--- [서대문구(소장)] Page {page}: {len(books)}권 수집 중 ---")

        for book in books:
            # 1. 제목: ul > li.tit > a 텍스트
            title = book.css("li.tit a::text").get()
            
            # 2. 저자 / 출판사 파싱
            # 구조: <li class="writer">장승진<span>프랙티쿠스</span>2025-10-21</li>
            
            # (1) 저자: li.writer의 바로 아래 텍스트 노드들 중 첫 번째
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
            # 예: .../4808968930461/L4808968930461.jpg -> 4808968930461
            isbn = ""
            if image_url:
                # 숫자(\d)만으로 구성된 ID 찾기
                match = re.search(r'/(\d+)/L\1', image_url) 
                if match:
                    isbn = match.group(1)
            
            if title:
                yield {
                    'title': title.strip(),
                    'author': author,
                    'publisher': publisher,
                    'library': "서대문구립도서관(소장)",
                    'platform': "교보문고(신버전)",
                    'image_url': image_url,
                    'isbn': isbn
                }
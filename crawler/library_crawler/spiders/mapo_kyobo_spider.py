import scrapy
import re
from urllib.parse import urlencode

class MapoKyoboSpider(scrapy.Spider):
    name = "mapo_kyobo"
    allowed_domains = ["ebook.mapo.go.kr"]
    
    # 마포구 전자도서관 (교보 신버전 주소 적용)
    base_url = "https://ebook.mapo.go.kr/elibrary-front/content/contentList.ink"
    
    def start_requests(self):
        # 🚀 [속도 최적화] 1~500페이지
        max_page = 500
        
        for page in range(1, max_page + 1):
            params = {
                'brcd': '',
                'sntnAuthCode': '',
                'contentAll': 'Y',      # 전체 보기
                'cttsDvsnCode': '001',  # 전자책
                'ctgrId': '',
                'orderByKey': 'publDate', # 최신순
                'selViewCnt': '80',       # 80개씩
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
            print(f"--- [마포구] Page {page}: {len(books)}권 수집 중 ---")

        for book in books:
            # 1. 제목
            title = book.css("li.tit a::text").get()
            
            # 2. 저자 / 출판사 파싱
            writer_texts = book.css("li.writer::text").getall()
            author = writer_texts[0].strip() if writer_texts else ""
            publisher = book.css("li.writer span::text").get() or ""

            # 3. 이미지 URL
            image_url = book.css("div.img a img::attr(src)").get()
            if image_url and image_url.startswith("//"):
                image_url = "https:" + image_url
            
            # 4. ISBN 추출
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
                    'library': "마포구 전자도서관",
                    'platform': "교보문고(신버전)",
                    'image_url': image_url,
                    'isbn': isbn
                }
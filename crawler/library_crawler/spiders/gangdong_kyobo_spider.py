import scrapy
import re
from urllib.parse import urlencode

class GangdongKyoboSpider(scrapy.Spider):
    name = "gangdong_kyobo"
    allowed_domains = ["gdlib.dkyobobook.co.kr"]
    base_url = "https://gdlib.dkyobobook.co.kr"
    
    def start_requests(self):
        # 🚀 [18만 권 대응] 
        # 총 181,015권 / 20권씩 = 약 9051페이지
        # 넉넉하게 9200페이지까지 돌립니다.
        max_page = 9200 
        
        for page in range(1, max_page + 1):
            params = {
                'contentAll': 'Y',
                'cttsDvsnCode': '001', 
                'orderByKey': 'publDate', 
                'selViewCnt': '80', # 20개씩 (안전 모드)
                'pageIndex': str(page)
            }
            url = f"{self.base_url}/content/contentList.ink?{urlencode(params)}"
            yield scrapy.Request(url, callback=self.parse, meta={'page': page})

    def parse(self, response):
        page = response.meta['page']
        
        # 🎯 [수정된 선택자] XPath 사용
        # "내부에 class='tit'인 li를 가지고 있는 모든 li 태그"를 찾습니다.
        # (강동구의 복잡한 중첩 구조를 뚫는 만능 열쇠입니다)
        books = response.xpath('//li[.//li[@class="tit"]]')
        
        if not books:
            # 데이터가 없으면(페이지 끝) 로그 남기고 종료
            # print(f"--- [강동구] Page {page}: 데이터 없음 ---")
            return

        # 1000페이지 단위로 로그 찍기 (너무 많이 찍히면 정신없으니까요)
        if page % 10 == 0:
            print(f"--- [강동구(구독)] Page {page}/{9200}: 수집 진행 중... ---")

        for book in books:
            # 1. 제목 (li.tit 안의 a 태그)
            title = book.css("li.tit a::text").get()
            
            # 2. 저자 (li.writer의 텍스트 노드)
            writer_nodes = book.css("li.writer::text").getall()
            author = writer_nodes[0].strip() if writer_nodes else ""
            
            # 3. 출판사 (li.writer 안의 span 태그)
            publisher = book.css("li.writer span::text").get() or ""

            # 4. 이미지 URL
            image_url = book.css("div.img img::attr(src)").get()
            
            # 5. ISBN 추출
            isbn = ""
            if image_url:
                match = re.search(r'(\d{13})', image_url)
                if match:
                    isbn = match.group(1)
            
            if title:
                yield {
                    'title': title.strip(),
                    'author': author.strip(),
                    'publisher': publisher.strip(),
                    'library': "강동구립도서관(구독)",
                    'platform': "교보문고",
                    'image_url': image_url,
                    'isbn': isbn
                }
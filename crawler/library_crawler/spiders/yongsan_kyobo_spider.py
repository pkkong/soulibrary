import scrapy
from urllib.parse import urlencode

class YongsanKyoboSpider(scrapy.Spider):
    """
    [DB 구축용] 용산구(교보). 1000개씩 전체 긁기 + 이미지 URL 추가.
    """
    name = "yongsan_kyobo"
    base_url = "https://ebook.yslibrary.or.kr"
    common_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Referer': base_url 
    }

    def start_requests(self):
        content_path = "/elibrary-front/content/contentList.ink"
        params = {
            'contentAll': 'Y',
            'cttsDvsnCode': '001',
            'orderByKey': 'publDate',
            'selViewCnt': '1000',    # 1000개씩
            'pageIndex': '1'
        }
        start_url = f"{self.base_url}{content_path}?{urlencode(params)}"
        print(f"--- [용산] 1000개씩 DB 구축 시작 (이미지 포함) ---")
        yield scrapy.Request(url=start_url, headers=self.common_headers, callback=self.parse_search_results, meta={'pageIndex': 1})

    def parse_search_results(self, response):
        pageIndex = response.meta['pageIndex']
        books = response.css("#container > div > ul > li")
        
        if not books:
            print(f"--- [용산] Page {pageIndex}: 끝 (더 이상 데이터 없음) ---")
            return

        print(f"--- [용산] Page {pageIndex}: {len(books)}권 수집 중... ---")

        for book in books:
            title = book.css("li.tit a::text").get()
            if not title: continue

            # [이미지 URL 추출]
            # 보통 <div class="thumb"> <img src="..."> </div> 구조입니다.
            image_url = book.css("div.thumb img::attr(src)").get()
            
            writer_li = book.css("li.writer")
            all_info = writer_li.css("::text").getall()
            info_list = [t.strip() for t in all_info if t.strip() and t.strip() != '|']
            
            author = info_list[0] if len(info_list) > 0 else "저자 미상"
            publisher = info_list[1] if len(info_list) > 1 else "출판사 미상"

            yield {
                'title': title.strip(),
                'author': author,
                'publisher': publisher,
                'image_url': image_url, # 이미지 컬럼 추가!
                'library': "용산구 전자도서관 (교보)"
            }
        
        # 다음 페이지 요청
        next_idx = pageIndex + 1
        params = {'contentAll': 'Y', 'cttsDvsnCode': '001', 'orderByKey': 'publDate', 'selViewCnt': '1000', 'pageIndex': next_idx}
        next_url = f"{self.base_url}/elibrary-front/content/contentList.ink?{urlencode(params)}"
        yield scrapy.Request(url=next_url, headers=self.common_headers, callback=self.parse_search_results, meta={'pageIndex': next_idx})
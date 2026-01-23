# -*- coding: utf-8 -*-
from .bookcube_base import BookcubeBaseSpider


class SeongdongBookcubeSpider(BookcubeBaseSpider):
    name = "seongdong_bookcube"
    allowed_domains = ["ebook.sdlib.or.kr", "bookimg.bookcube.com"]
    base_url = "https://ebook.sdlib.or.kr/FxLibrary/product/list/"
    library_name = "성동구립도서관"
    export_content_id = False

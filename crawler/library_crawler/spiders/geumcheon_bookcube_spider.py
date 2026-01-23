# -*- coding: utf-8 -*-
from .bookcube_base import BookcubeBaseSpider


class GeumcheonBookcubeSpider(BookcubeBaseSpider):
    name = "geumcheon_bookcube"
    allowed_domains = ["elib.geumcheonlib.seoul.kr", "bookimg.bookcube.com"]
    base_url = "https://elib.geumcheonlib.seoul.kr/FxLibrary/product/list/"
    library_name = "금천구립도서관"
    export_content_id = False

# web/config.py (홈페이지 URL 추가됨)

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
DATA_DIR = os.path.join(ROOT_DIR, 'data')
CRAWLER_DIR = os.path.join(ROOT_DIR, "crawler")
STATUS_FILE = os.path.join(DATA_DIR, "crawler_status.json")

# API 키
ODCLOUD_API_KEY = "0R7RBsF2YmoEs3gIwDmbZyv/SYGXCeJwZWyhhlsvX3qcSuGu89uzFL9/sODpXk3tmHa2nt7DP7yZJ/4RJ14FEA=="
SEOUL_API_KEY = "745942496d6b6f6e383774624c4c56"

LIBRARIES = {
    # --- Scrapy ---
    "yongsan": {
        "name": "용산구 (교보)",
        "type": "scrapy",
        "db_file": os.path.join(DATA_DIR, "yongsan_db.csv"),
        "cmd": ["scrapy", "crawl", "yongsan_kyobo", "-O", "../data/yongsan_db.csv"],
        "url_prefix": "https://ebook.yslibrary.or.kr",
        "isbn_map": None,
        "library_name": "용산구 전자도서관 (교보)",
        "homepage_url": "https://ebook.yslibrary.or.kr/" # 👈 추가됨
    },

    # --- Custom API ---
    "seoul": {
        "name": "서울도서관 (교보)",
        "type": "custom",
        "db_file": os.path.join(DATA_DIR, "seoul_ebook_db.json"),
        "cmd": ["python", "collect_seoul.py"],
        "url_prefix": None,
        "isbn_map": None,
        "library_name": "서울도서관 (교보)",
        "homepage_url": "https://elib.seoul.go.kr/" # 👈
    },
    "sen_owned": {
        "name": "서울시교육청 (소장/YES24)",
        "type": "custom", 
        "db_file": os.path.join(DATA_DIR, "sen_owned_db.csv"),
        "cmd": ["python", "download_sen_owned_db.py"],
        "url_prefix": None,
        "isbn_map": None,
        "library_name": "서울시교육청 (소장/YES24)",
        "homepage_url": "https://e-lib.sen.go.kr/" # 👈
    },
    "sen_subs": {
        "name": "서울시교육청 (구독)",
        "type": "custom",
        "db_file": os.path.join(DATA_DIR, "sen_subs_db.csv"),
        "cmd": ["python", "download_sen_subs_db.py"],
        "url_prefix": None,
        "isbn_map": None,
        "library_name": "서울시교육청 (구독)",
        "homepage_url": "https://e-lib.sen.go.kr/" # 👈
    },

    # --- Odcloud API ---
    "seongbuk": {
        "name": "성북구 (교보)",
        "type": "odcloud",
        "db_file": os.path.join(DATA_DIR, "seongbuk_db.csv"),
        "cmd": ["python", "odcloud_downloader.py", "seongbuk"],
        "api_url": "https://api.odcloud.kr/api/15112699/v1/uddi:29e375a7-80b6-4f0d-8318-d6d26e71c42c",
        "column_map": {'제목': 'title', '저자': 'author', '출판사': 'publisher', '콘텐츠 유형': 'format'},
        "format_filter_column": "format",
        "library_name": "성북구 도서관 (교보)",
        "isbn_map": "국제표준도서번호",
        "homepage_url": "https://elib.sblib.seoul.kr/" # 👈
    },
    "gangnam": {
        "name": "강남구 (교보)",
        "type": "odcloud",
        "db_file": os.path.join(DATA_DIR, "gangnam_db.csv"),
        "cmd": ["python", "odcloud_downloader.py", "gangnam"],
        "api_url": "https://api.odcloud.kr/api/15112734/v1/uddi:e7b16135-62b4-4e02-8776-e842f96878fa",
        "column_map": {'도서명': 'title', '저자명': 'author', '출판사': 'publisher', '표지주소': 'image_url', '형식(전자책)': 'format'},
        "format_filter_column": "format",
        "library_name": "강남구 도서관 (교보)",
        "isbn_map": "국제표준도서번호",
        "homepage_url": "http://ebook.gangnam.go.kr/" # 👈
    },
    "yeongdeungpo": {
        "name": "영등포구 (교보)",
        "type": "odcloud",
        "db_file": os.path.join(DATA_DIR, "yeongdeungpo_db.csv"),
        "cmd": ["python", "odcloud_downloader.py", "yeongdeungpo"],
        "api_url": "https://api.odcloud.kr/api/15112603/v1/uddi:04d1126f-ea1f-4483-ac19-ffca6b489359",
        "column_map": {'제목': 'title', '저자': 'author', '출판사': 'publisher', '상품종류': 'format'},
        "format_filter_column": "format",
        "library_name": "영등포구 도서관 (교보)",
        "url_prefix": "https://ebook.ydplib.or.kr",
        "isbn_map": "국제표준도서번호",
        "homepage_url": "https://ebook.ydplib.or.kr/" # 👈
    },
    "dongdaemun": {
        "name": "동대문구 (교보)",
        "type": "odcloud",
        "db_file": os.path.join(DATA_DIR, "dongdaemun_db.csv"),
        "cmd": ["python", "odcloud_downloader.py", "dongdaemun"],
        "api_url": "https://api.odcloud.kr/api/15112707/v1/uddi:ade71320-94a4-433b-976f-eaaaa166602a",
        "column_map": {'도서명': 'title', '저자': 'author', '출판사': 'publisher', '자료유형': 'format'},
        "format_filter_column": "format",
        "library_name": "동대문구 도서관 (교보)",
        "isbn_map": "국제표준도서번호",
        "homepage_url": "https://e-book.l4d.or.kr/" # 👈
    },
    "dongjak": {
        "name": "동작구 (교보)",
        "type": "odcloud",
        "db_file": os.path.join(DATA_DIR, "dongjak_db.csv"),
        "cmd": ["python", "odcloud_downloader.py", "dongjak"],
        "api_url": "https://api.odcloud.kr/api/15112685/v1/uddi:fca8b6b1-1352-4453-8601-ea3aca1ec259",
        "column_map": {'제목': 'title', '저자': 'author', '출판사': 'publisher', '콘텐츠 유형': 'format'},
        "format_filter_column": "format",
        "library_name": "동작구 구립도서관 (교보)",
        "isbn_map": "국제표준도서번호",
        "homepage_url": "https://ebook.dongjaklib.sookmyung.ac.kr/" # 👈
    },
    "gangseo": {
        "name": "강서구 (교보)",
        "type": "odcloud",
        "db_file": os.path.join(DATA_DIR, "gangseo_db.csv"),
        "cmd": ["python", "odcloud_downloader.py", "gangseo"],
        "api_url": "https://api.odcloud.kr/api/15112683/v1/uddi:c2a03e68-32dd-41aa-9b84-eab6814f4c92",
        "column_map": {'도서명': 'title', '저자명': 'author', '출판사': 'publisher', '표지이미지주소': 'image_url'},
        "format_filter_column": None,
        "library_name": "강서구 전자도서관 (교보)",
        "isbn_map": "국제표준도서번호",
        "homepage_url": "https://ebook.gangseo.seoul.kr/" # 👈
    },
    "seocho": {
        "name": "서초구 (YES24)",
        "type": "odcloud",
        "db_file": os.path.join(DATA_DIR, "seocho_db.csv"),
        "cmd": ["python", "odcloud_downloader.py", "seocho"],
        "api_url": "https://api.odcloud.kr/api/15112631/v1/uddi:a0e9252b-5ad3-4ec8-b965-d9a4b5c912c7",
        "column_map": {'도서명': 'title', '저자명': 'author', '출판사': 'publisher', '표지 주소(url)': 'image_url', '형식': 'format'},
        "format_filter_column": "format",
        "library_name": "서초구 전자도서관 (YES24)",
        "isbn_map": "국제 표준 도서 번호(isbn)",
        "homepage_url": "https://ebook.seocholib.or.kr/" # 👈
    },
    "eunpyeong": {
        "name": "은평구 (교보)",
        "type": "odcloud",
        "db_file": os.path.join(DATA_DIR, "eunpyeong_db.csv"),
        "cmd": ["python", "odcloud_downloader.py", "eunpyeong"],
        "api_url": "https://api.odcloud.kr/api/15112554/v1/uddi:b596ed90-3410-450d-8f40-9899203fb2a9",
        "column_map": {'도서명': 'title', '저자명': 'author', '출판사': 'publisher', '표지주소(URL)': 'image_url'},
        "format_filter_column": None,
        "library_name": "은평구립도서관 (교보)",
        "isbn_map": "국제표준도서번호(ISBN)",
        "homepage_url": "https://ebook.eplib.or.kr/" # 👈
    },
    "jongno": {
        "name": "종로구 (API)",
        "type": "odcloud",
        "db_file": os.path.join(DATA_DIR, "jongno_db.csv"),
        "cmd": ["python", "odcloud_downloader.py", "jongno"],
        "api_url": "https://api.odcloud.kr/api/15112922/v1/uddi:e3d4db2a-3a4d-46a2-8c3d-c87ad7f09773",
        "column_map": {'도서명': 'title', '서명': 'title', '저자': 'author', '저자명': 'author', '출판사': 'publisher', '발행처': 'publisher'},
        "format_filter_column": None,
        "library_name": "종로구 전자도서관 (API)",
        "url_prefix": None,
        "isbn_map": None,
        "homepage_url": "https://lib.jongno.go.kr/" # 👈
    },
    "songpa": {
        "name": "송파구 (API)",
        "type": "odcloud",
        "db_file": os.path.join(DATA_DIR, "songpa_db.csv"),
        "cmd": ["python", "odcloud_downloader.py", "songpa"],
        "api_url": "https://api.odcloud.kr/api/15112642/v1/uddi:253ba864-742b-4ee3-8a8a-bb8662eacd02",
        "column_map": {'제목': 'title', '출판사': 'publisher', '형식': 'format'},
        "format_filter_column": "format",
        "library_name": "송파구 도서관 (API)",
        "url_prefix": None,
        "isbn_map": None,
        "homepage_url": "https://www.splib.or.kr/" # 👈
    },
    "geumcheon": {
        "name": "금천구 (API)",
        "type": "odcloud",
        "db_file": os.path.join(DATA_DIR, "geumcheon_db.csv"),
        "cmd": ["python", "odcloud_downloader.py", "geumcheon"],
        "api_url": "https://api.odcloud.kr/api/15112687/v1/uddi:fe4d39aa-7188-4919-a85e-b8befd3040b8",
        "column_map": {'도서명': 'title', '저자명': 'author', '출판사': 'publisher', '형식': 'format'},
        "format_filter_column": "format",
        "library_name": "금천구 도서관 (API)",
        "url_prefix": None,
        "isbn_map": None,
        "homepage_url": "https://geumcheonlib.seoul.kr/" # 👈
    },
    "yangcheon": {
        "name": "양천구 (API)",
        "type": "odcloud",
        "db_file": os.path.join(DATA_DIR, "yangcheon_db.csv"),
        "cmd": ["python", "odcloud_downloader.py", "yangcheon"],
        "api_url": "https://api.odcloud.kr/api/15112714/v1/uddi:4b8d4010-e054-42fe-b99c-e7a337bb2dc5",
        "column_map": {'도서명': 'title', '저자명': 'author', '출판사명': 'publisher', '형식': 'format'},
        "format_filter_column": "format",
        "library_name": "양천구 도서관 (API)",
        "url_prefix": None,
        "isbn_map": None,
        "homepage_url": "https://lib.yangcheon.or.kr/" # 👈
    },
}
# web/config.py
# 서울시 통합 전자도서관 설정 파일 (Final Version)

import os

# 1. 기본 경로 설정
BASE_DIR = os.path.dirname(os.path.abspath(__file__)) # web 폴더
ROOT_DIR = os.path.dirname(BASE_DIR)                 # 프로젝트 루트 폴더
DATA_DIR = os.path.join(ROOT_DIR, 'data')
CRAWLER_DIR = os.path.join(ROOT_DIR, "crawler")

# 상태 파일 경로
STATUS_FILE = os.path.join(DATA_DIR, "crawler_status.json")

# 2. API 키 (공공데이터포털 / 서울시)
ODCLOUD_API_KEY = "0R7RBsF2YmoEs3gIwDmbZyv/SYGXCeJwZWyhhlsvX3qcSuGu89uzFL9/sODpXk3tmHa2nt7DP7yZJ/4RJ14FEA=="
SEOUL_API_KEY = "745942496d6b6f6e383774624c4c56"

# 3. 도서관별 상세 설정
#    - platform: 'Kyobo', 'YES24', 'Aladin', 'Mixed', 'Unknown'
#    - service_type: 'Owned' (소장), 'Subscription' (구독), 'Mixed'

LIBRARIES = {
    # ========================================================
    # [Group A] Scrapy 크롤러 (직접 크롤링)
    # ========================================================
    
    # 1. 용산구
    "yongsan": {
        "name": "용산구 (교보)",
        "type": "scrapy",
        "db_file": os.path.join(DATA_DIR, "yongsan_db.csv"),
        "cmd": ["scrapy", "crawl", "yongsan_kyobo", "-O", "../data/yongsan_db.csv"],
        "url_prefix": "https://ebook.yslibrary.or.kr",
        "library_name": "용산구 전자도서관",
        "homepage_url": "https://ebook.yslibrary.or.kr/",
        "platform": "Kyobo",
        "service_type": "Owned"
    },
    # 2. 마포구
    "mapo": {
        "name": "마포구 (교보)",
        "type": "scrapy",
        "db_file": os.path.join(DATA_DIR, "mapo_db.csv"),
        "cmd": ["scrapy", "crawl", "mapo_kyobo", "-O", "../data/mapo_db.csv"],
        "url_prefix": None,
        "library_name": "마포구 전자도서관",
        "homepage_url": "https://ebook.mapo.go.kr/",
        "platform": "Kyobo",
        "service_type": "Owned"
    },
    # 3. 강북구
    "gangbuk": {
        "name": "강북구 (교보)",
        "type": "scrapy",
        "db_file": os.path.join(DATA_DIR, "gangbuk_db.csv"),
        "cmd": ["scrapy", "crawl", "gangbuk_kyobo", "-O", "../data/gangbuk_db.csv"],
        "url_prefix": None,
        "library_name": "강북문화정보도서관",
        "homepage_url": "https://ebook.gblib.or.kr/",
        "platform": "Kyobo",
        "service_type": "Owned"
    },
    # 4. 광진구 (소장형 - 교보 신버전)
    "gwangjin": {
        "name": "광진구 (소장)",
        "type": "scrapy",
        "db_file": os.path.join(DATA_DIR, "gwangjin_db.csv"),
        "cmd": ["scrapy", "crawl", "gwangjin_kyobo", "-O", "../data/gwangjin_db.csv"],
        "url_prefix": None,
        "library_name": "광진구립도서관 (소장)",
        "homepage_url": "https://ebook.gwangjinlib.seoul.kr/",
        "platform": "Kyobo",
        "service_type": "Owned"
    },

    # 4-2. 광진구 (구독형 - 교보 신버전)
    "gwangjin_subs": {
        "name": "광진구 (구독)",
        "type": "scrapy",
        "db_file": os.path.join(DATA_DIR, "gwangjin_subs_db.csv"),
        "cmd": ["scrapy", "crawl", "gwangjin_subscription", "-O", "../data/gwangjin_subs_db.csv"],
        "url_prefix": None,
        "library_name": "광진구립도서관 (구독)",
        "homepage_url": "https://gwangjin.dkyobobook.co.kr/",
        "platform": "Kyobo",
        "service_type": "Subscription"
    },
    # 5. 성동구 (FxLibrary)
    "seongdong": {
        "name": "성동구 (Fx)",
        "type": "scrapy",
        "db_file": os.path.join(DATA_DIR, "seongdong_db.csv"),
        "cmd": ["scrapy", "crawl", "seongdong_fx", "-O", "../data/seongdong_db.csv"],
        "url_prefix": None,
        "library_name": "성동구립도서관",
        "homepage_url": "https://ebook.sdlib.or.kr/",
        "platform": "FxLibrary",
        "service_type": "Mixed"
    },
    # 6. 강동구 (YES24 - 소장)
    "gangdong_yes24": {
        "name": "강동구 (YES24)",
        "type": "scrapy",
        "db_file": os.path.join(DATA_DIR, "gangdong_yes24_db.csv"),
        "cmd": ["scrapy", "crawl", "gangdong_yes24", "-O", "../data/gangdong_yes24_db.csv"],
        "url_prefix": None,
        "library_name": "강동구립도서관 (소장)",
        "homepage_url": "https://ebook.gdlibrary.or.kr/",
        "platform": "YES24",
        "service_type": "Owned"
    },
    # 7. 강동구 (교보 - 구독)
    "gangdong_kyobo": {
        "name": "강동구 (구독)",
        "type": "scrapy",
        "db_file": os.path.join(DATA_DIR, "gangdong_kyobo_db.csv"),
        "cmd": ["scrapy", "crawl", "gangdong_kyobo", "-O", "../data/gangdong_kyobo_db.csv"],
        "url_prefix": None,
        "library_name": "강동구립도서관 (구독)",
        "homepage_url": "https://gdlib.dkyobobook.co.kr/",
        "platform": "Kyobo",
        "service_type": "Subscription"
    },
    # 8. 도봉구
    "dobong": {
        "name": "도봉구 (교보)",
        "type": "scrapy",
        "db_file": os.path.join(DATA_DIR, "dobong_db.csv"),
        "cmd": ["scrapy", "crawl", "dobong_kyobo", "-O", "../data/dobong_db.csv"],
        "url_prefix": None,
        "library_name": "도봉구립도서관",
        "homepage_url": "https://elib.dobong.kr/",
        "platform": "Kyobo",
        "service_type": "Owned"
    },
    # 9. 서대문구 (구독)
    "seodaemun_subs": {
        "name": "서대문구 (구독)",
        "type": "scrapy",
        "db_file": os.path.join(DATA_DIR, "seodaemun_subs_db.csv"),
        "cmd": ["scrapy", "crawl", "seodaemun_subscription", "-O", "../data/seodaemun_subs_db.csv"],
        "url_prefix": None,
        "library_name": "서대문구립도서관 (구독)",
        "homepage_url": "https://sdmlib.dkyobobook.co.kr/",
        "platform": "Kyobo",
        "service_type": "Subscription"
    },
    # 10. 서대문구 (소장)
    "seodaemun_owned": {
        "name": "서대문구 (소장)",
        "type": "scrapy",
        "db_file": os.path.join(DATA_DIR, "seodaemun_owned_db.csv"),
        "cmd": ["scrapy", "crawl", "seodaemun_owned", "-O", "../data/seodaemun_owned_db.csv"],
        "url_prefix": None,
        "library_name": "서대문구립도서관 (소장)",
        "homepage_url": "https://ebook.sdm.or.kr/",
        "platform": "Kyobo",
        "service_type": "Owned"
    },
    # 11. 중구
    "junggu": {
        "name": "중구 (교보)",
        "type": "scrapy",
        "db_file": os.path.join(DATA_DIR, "junggu_db.csv"),
        "cmd": ["scrapy", "crawl", "junggu_kyobo", "-O", "../data/junggu_db.csv"],
        "url_prefix": None,
        "library_name": "중구통합전자도서관",
        "homepage_url": "https://ebook.junggulib.or.kr/",
        "platform": "Kyobo",
        "service_type": "Owned"
    },
    # 12. 중랑구
    "jungnang": {
        "name": "중랑구 (교보)",
        "type": "scrapy",
        "db_file": os.path.join(DATA_DIR, "jungnang_db.csv"),
        "cmd": ["scrapy", "crawl", "jungnang_kyobo", "-O", "../data/jungnang_db.csv"],
        "url_prefix": None,
        "library_name": "중랑구립정보도서관",
        "homepage_url": "https://ebook.jungnanglib.seoul.kr/",
        "platform": "Kyobo",
        "service_type": "Owned"
    },
    # 13. 관악구
    "gwanak": {
        "name": "관악구 (YES24)",
        "type": "scrapy",
        "db_file": os.path.join(DATA_DIR, "gwanak_db.csv"),
        "cmd": ["scrapy", "crawl", "gwanak_yes24", "-O", "../data/gwanak_db.csv"],
        "url_prefix": None,
        "library_name": "관악구통합도서관",
        "homepage_url": "https://e-lib.gwanak.go.kr/",
        "platform": "YES24",
        "service_type": "Owned"
    },
    # 14. 노원구 (New)
    "nowon": {
        "name": "노원구 (교보)",
        "type": "scrapy",
        "db_file": os.path.join(DATA_DIR, "nowon_db.csv"),
        "cmd": ["scrapy", "crawl", "nowon_kyobo", "-O", "../data/nowon_db.csv"],
        "url_prefix": None,
        "library_name": "노원구립도서관",
        "homepage_url": "https://eb.nowonlib.kr/",
        "platform": "Kyobo",
        "service_type": "Owned"
    },
    # 15. 구로구 (New)
    "guro": {
        "name": "구로구 (교보)",
        "type": "scrapy",
        "db_file": os.path.join(DATA_DIR, "guro_db.csv"),
        "cmd": ["scrapy", "crawl", "guro_kyobo", "-O", "../data/guro_db.csv"],
        "url_prefix": None,
        "library_name": "구로구립도서관",
        "homepage_url": "https://ebook.guro.go.kr/",
        "platform": "Kyobo",
        "service_type": "Owned"
    },

    # ========================================================
    # [Group B] Custom Script (서울도서관, 교육청)
    # ========================================================
    "seoul": {
        "name": "서울도서관",
        "type": "custom",
        "db_file": os.path.join(DATA_DIR, "seoul_ebook_db.json"),
        "cmd": ["python", "collect_seoul.py"],
        "url_prefix": None,
        "library_name": "서울도서관 (복합)",
        "homepage_url": "https://elib.seoul.go.kr/",
        "platform": "Mixed",
        "service_type": "Mixed"
    },
    "sen_owned": {
        "name": "서울시교육청 (소장)",
        "type": "custom", 
        "db_file": os.path.join(DATA_DIR, "sen_owned_db.csv"),
        "cmd": ["python", "download_sen_owned_db.py"],
        "url_prefix": None,
        "library_name": "서울시교육청 (소장)",
        "homepage_url": "https://e-lib.sen.go.kr/",
        "platform": "Mixed",
        "service_type": "Owned"
    },
    "sen_subs": {
        "name": "서울시교육청 (구독)",
        "type": "custom",
        "db_file": os.path.join(DATA_DIR, "sen_subs_db.csv"),
        "cmd": ["python", "download_sen_subs_db.py"],
        "url_prefix": None,
        "library_name": "서울시교육청 (구독)",
        "homepage_url": "https://e-lib.sen.go.kr/",
        "platform": "Mixed",
        "service_type": "Subscription"
    },

    # ========================================================
    # [Group C] ODCloud (공공데이터포털 API)
    # ========================================================
    "seongbuk": {
        "name": "성북구 (교보)",
        "type": "odcloud",
        "db_file": os.path.join(DATA_DIR, "seongbuk_db.csv"),
        "cmd": ["python", "odcloud_downloader.py", "seongbuk"],
        "api_url": "https://api.odcloud.kr/api/15112699/v1/uddi:29e375a7-80b6-4f0d-8318-d6d26e71c42c",
        "column_map": {'제목': 'title', '저자': 'author', '출판사': 'publisher', '콘텐츠 유형': 'format'},
        "format_filter_column": "format",
        "library_name": "성북구 도서관",
        "isbn_map": "국제표준도서번호",
        "homepage_url": "https://elib.sblib.seoul.kr/",
        "platform": "Kyobo",
        "service_type": "Owned"
    },
    "gangnam": {
        "name": "강남구 (교보)",
        "type": "odcloud",
        "db_file": os.path.join(DATA_DIR, "gangnam_db.csv"),
        "cmd": ["python", "odcloud_downloader.py", "gangnam"],
        "api_url": "https://api.odcloud.kr/api/15112734/v1/uddi:e7b16135-62b4-4e02-8776-e842f96878fa",
        "column_map": {'도서명': 'title', '저자명': 'author', '출판사': 'publisher', '표지주소': 'image_url', '형식(전자책)': 'format'},
        "format_filter_column": "format",
        "library_name": "강남구 도서관",
        "isbn_map": "국제표준도서번호",
        "homepage_url": "http://ebook.gangnam.go.kr/",
        "platform": "Kyobo",
        "service_type": "Owned"
    },
    "yeongdeungpo": {
        "name": "영등포구 (교보)",
        "type": "odcloud",
        "db_file": os.path.join(DATA_DIR, "yeongdeungpo_db.csv"),
        "cmd": ["python", "odcloud_downloader.py", "yeongdeungpo"],
        "api_url": "https://api.odcloud.kr/api/15112603/v1/uddi:04d1126f-ea1f-4483-ac19-ffca6b489359",
        "column_map": {'제목': 'title', '저자': 'author', '출판사': 'publisher', '상품종류': 'format'},
        "format_filter_column": "format",
        "library_name": "영등포구 도서관",
        "url_prefix": "https://ebook.ydplib.or.kr",
        "isbn_map": "국제표준도서번호",
        "homepage_url": "https://ebook.ydplib.or.kr/",
        "platform": "Kyobo",
        "service_type": "Owned"
    },
    "dongdaemun": {
        "name": "동대문구 (교보)",
        "type": "odcloud",
        "db_file": os.path.join(DATA_DIR, "dongdaemun_db.csv"),
        "cmd": ["python", "odcloud_downloader.py", "dongdaemun"],
        "api_url": "https://api.odcloud.kr/api/15112707/v1/uddi:ade71320-94a4-433b-976f-eaaaa166602a",
        "column_map": {'도서명': 'title', '저자': 'author', '출판사': 'publisher', '자료유형': 'format'},
        "format_filter_column": "format",
        "library_name": "동대문구 도서관",
        "isbn_map": "국제표준도서번호",
        "homepage_url": "https://e-book.l4d.or.kr/",
        "platform": "Kyobo",
        "service_type": "Owned"
    },
    "dongjak": {
        "name": "동작구 (교보)",
        "type": "odcloud",
        "db_file": os.path.join(DATA_DIR, "dongjak_db.csv"),
        "cmd": ["python", "odcloud_downloader.py", "dongjak"],
        "api_url": "https://api.odcloud.kr/api/15112685/v1/uddi:fca8b6b1-1352-4453-8601-ea3aca1ec259",
        "column_map": {'제목': 'title', '저자': 'author', '출판사': 'publisher', '콘텐츠 유형': 'format'},
        "format_filter_column": "format",
        "library_name": "동작구 구립도서관",
        "isbn_map": "국제표준도서번호",
        "homepage_url": "https://ebook.dongjaklib.sookmyung.ac.kr/",
        "platform": "Kyobo",
        "service_type": "Owned"
    },
    "gangseo": {
        "name": "강서구 (교보)",
        "type": "odcloud",
        "db_file": os.path.join(DATA_DIR, "gangseo_db.csv"),
        "cmd": ["python", "odcloud_downloader.py", "gangseo"],
        "api_url": "https://api.odcloud.kr/api/15112683/v1/uddi:c2a03e68-32dd-41aa-9b84-eab6814f4c92",
        "column_map": {'도서명': 'title', '저자명': 'author', '출판사': 'publisher', '표지이미지주소': 'image_url'},
        "format_filter_column": None,
        "library_name": "강서구 전자도서관",
        "isbn_map": "국제표준도서번호",
        "homepage_url": "https://ebook.gangseo.seoul.kr/",
        "platform": "Kyobo",
        "service_type": "Owned"
    },
    "seocho": {
        "name": "서초구 (YES24)",
        "type": "odcloud",
        "db_file": os.path.join(DATA_DIR, "seocho_db.csv"),
        "cmd": ["python", "odcloud_downloader.py", "seocho"],
        "api_url": "https://api.odcloud.kr/api/15112631/v1/uddi:a0e9252b-5ad3-4ec8-b965-d9a4b5c912c7",
        "column_map": {'도서명': 'title', '저자명': 'author', '출판사': 'publisher', '표지 주소(url)': 'image_url', '형식': 'format'},
        "format_filter_column": "format",
        "library_name": "서초구 전자도서관",
        "isbn_map": "국제 표준 도서 번호(isbn)",
        "homepage_url": "https://ebook.seocholib.or.kr/",
        "platform": "YES24",
        "service_type": "Owned"
    },
    "eunpyeong": {
        "name": "은평구 (교보)",
        "type": "odcloud",
        "db_file": os.path.join(DATA_DIR, "eunpyeong_db.csv"),
        "cmd": ["python", "odcloud_downloader.py", "eunpyeong"],
        "api_url": "https://api.odcloud.kr/api/15112554/v1/uddi:b596ed90-3410-450d-8f40-9899203fb2a9",
        "column_map": {'도서명': 'title', '저자명': 'author', '출판사': 'publisher', '표지주소(URL)': 'image_url'},
        "format_filter_column": None,
        "library_name": "은평구립도서관",
        "isbn_map": "국제표준도서번호(ISBN)",
        "homepage_url": "https://ebook.eplib.or.kr/",
        "platform": "Kyobo",
        "service_type": "Owned"
    },
    "jongno": {
        "name": "종로구 (교보)",
        "type": "odcloud",
        "db_file": os.path.join(DATA_DIR, "jongno_db.csv"),
        "cmd": ["python", "odcloud_downloader.py", "jongno"],
        "api_url": "https://api.odcloud.kr/api/15112922/v1/uddi:e3d4db2a-3a4d-46a2-8c3d-c87ad7f09773",
        "column_map": {'도서명': 'title', '서명': 'title', '저자': 'author', '저자명': 'author', '출판사': 'publisher', '발행처': 'publisher'},
        "format_filter_column": None,
        "library_name": "종로구 전자도서관",
        "url_prefix": None,
        "isbn_map": None,
        "homepage_url": "https://lib.jongno.go.kr/",
        "platform": "Kyobo",
        "service_type": "Owned"
    },
    "songpa": {
        "name": "송파구 (교보)",
        "type": "odcloud",
        "db_file": os.path.join(DATA_DIR, "songpa_db.csv"),
        "cmd": ["python", "odcloud_downloader.py", "songpa"],
        "api_url": "https://api.odcloud.kr/api/15112642/v1/uddi:253ba864-742b-4ee3-8a8a-bb8662eacd02",
        "column_map": {'제목': 'title', '출판사': 'publisher', '형식': 'format'},
        "format_filter_column": "format",
        "library_name": "송파구 도서관",
        "url_prefix": None,
        "isbn_map": None,
        "homepage_url": "https://www.splib.or.kr/",
        "platform": "Kyobo",
        "service_type": "Owned"
    },
    "geumcheon": {
        "name": "금천구 (YES24)",
        "type": "odcloud",
        "db_file": os.path.join(DATA_DIR, "geumcheon_db.csv"),
        "cmd": ["python", "odcloud_downloader.py", "geumcheon"],
        "api_url": "https://api.odcloud.kr/api/15112687/v1/uddi:fe4d39aa-7188-4919-a85e-b8befd3040b8",
        "column_map": {'도서명': 'title', '저자명': 'author', '출판사': 'publisher', '형식': 'format'},
        "format_filter_column": "format",
        "library_name": "금천구 도서관",
        "url_prefix": None,
        "isbn_map": None,
        "homepage_url": "https://geumcheonlib.seoul.kr/",
        "platform": "YES24",
        "service_type": "Owned"
    },
    "yangcheon": {
        "name": "양천구 (YES24)",
        "type": "odcloud",
        "db_file": os.path.join(DATA_DIR, "yangcheon_db.csv"),
        "cmd": ["python", "odcloud_downloader.py", "yangcheon"],
        "api_url": "https://api.odcloud.kr/api/15112714/v1/uddi:4b8d4010-e054-42fe-b99c-e7a337bb2dc5",
        "column_map": {'도서명': 'title', '저자명': 'author', '출판사명': 'publisher', '형식': 'format'},
        "format_filter_column": "format",
        "library_name": "양천구 도서관",
        "url_prefix": None,
        "isbn_map": None,
        "homepage_url": "https://lib.yangcheon.or.kr/",
        "platform": "YES24",
        "service_type": "Owned"
    }
}
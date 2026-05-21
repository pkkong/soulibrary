import json
import os
import re
import threading
import time


CUSTOM_SLUGS = {
    "프로젝트 헤일메리": "project-hail-mary",
    "불편한 편의점": "bulpyeonhan-pyeonuijeom",
}

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_AUTO_BOOKS_PATH = os.path.join(ROOT_DIR, "data", "seo_books_auto.json")
STORE_VERSION = 1
_STORE_LOCK = threading.Lock()
DEFAULT_APPROVE_THRESHOLD = 70
DEFAULT_PUBLISH_THRESHOLD = 85


_SEO_BOOK_ROWS = [
    ("프로젝트 헤일메리", "앤디 위어", "알에이치코리아(RHK)"),
    ("나의 월급 독립 프로젝트(리마스터 에디션)", "유목민", "리더스북"),
    ("방구석 노트북 하나로 월급 독립 프로젝트", "노마드 그레이쓰", "리더스북"),
    ("데카메론 프로젝트", "마거릿 애트우드 외 28인", "인플루엔셜"),
    ("불편한 편의점", "김호연", "나무옆의자"),
    ("불편한 편의점 2", "김호연", "나무옆의자"),
    ("불편한 사람과 뻔뻔하게 대화하는 법", "진 마티넷", "필름(Feelm)"),
    ("불편한 한국사", "배기성", "블랙피쉬"),
    ("디 에센셜 한강", "한강", "문학동네"),
    ("디 에센셜: 한강(무선 보급판)", "한강", "문학동네"),
    ("꽁꽁 얼어붙은 한강 위로 고양이가 걸어갑니다", "김주하", "매일경제신문사"),
    ("마음이 따뜻한 강철왕, 카네기", "배미주", "아람북스"),
    ("김호연의 작업실", "김호연", "서랍의날씨"),
    ("우리가 읽은 소설 가이드 김호연의 불편한 편의점", "렛베일북스 편집부", "스마트북"),
    ("김호연재 시 깊이 읽기", "박은선", "국학자료원"),
    ("김호연의 작업실 - 김호연의 사적인 소설 작업 일지", "김호연 지음", "서랍의날씨"),
    ("우리가 읽은 소설 가이드 김초엽의 지구 끝의 온실", "렛베일북스 편집부", "스마트북"),
    ("내가 읽은 김초엽의 우리가 빛의 속도로 갈 수 없다면", "윤지한", "작가와"),
    ("히가시노 게이고의 무한도전", "히가시노 게이고", "소미북스"),
    ("범인 없는 살인의 밤 (개정판) - 히가시노 게이고 문학선", "히가시노 게이고", "알에이치코리아(RHK)"),
    ("수상한 사람들 - 히가시노 게이고 장편소설", "히가시노 게이고", "RHK"),
    ("사랑에 빠지지 말 것 사랑을 할 것", "슈히", "딥앤와이드"),
    ("사랑하기 전에 알았더라면 좋았을 것들", "김달", "빅피시"),
    ("너를 미워할 시간에 나를 사랑하기로 했다", "윤서진", "스몰빅라이프"),
    ("온전한 사랑의 이해", "다니엘", "사운드인사이트(Sound Insight)"),
    ("이세돌, 인생의 수읽기", "이세돌", "웅진지식하우스"),
    ("인생을 바꾸는 이메일 쓰기", "이슬아", "이야기장수"),
    ("인생은 호르몬", "데이비드 JP 필립스", "윌북"),
    ("공부는 인생을 바꾼다 : 존 밀턴의 교육철학", "존 밀턴", "아이보리잉크"),
    ("잘 벌고 잘 쓰고 잘 살고 싶어서 돈 공부를 시작했다", "래빗해빛(김아름)", "토네이도"),
    ("돈으로 읽는 세계사", "강영운", "교보문고"),
    ("나의 돈키호테", "김호연", "나무옆의자"),
    ("돈이 어렵지 않은 어른이 된다는 것", "시골쥐", "웅진지식하우스"),
    ("다시, 역사의 쓸모", "최태성", "(주)프런트페이지"),
    ("한국인의 눈으로 본 근대 일본의 역사", "박훈", "어크로스"),
    ("황현필의 진보를 위한 역사", "황현필", "역바연"),
    ("RNA의 역사", "토머스 R. 체크", "세종서적"),
    ("과자 사면 과학 드립니다", "정윤선", "풀빛"),
    ("과학이 설계한 유토피아 : 뉴 아틀란티스 15문장", "프랜시스 베이컨", "위즈덤커넥트"),
    ("수면의 뇌과학", "크리스 윈터", "현대지성"),
    ("감정의 과학 SHIFT", "이선 크로스", "웅진지식하우스"),
    ("내 마음이 지옥일 때 부처가 말했다", "코이케 류노스케", "웅진지식하우스"),
    ("메리골드 마음 식물원", "윤정은", "북로망스"),
    ("온 마음을 모아", "서혜듬", "안전가옥"),
    ("결국 마음먹은 대로 된다", "나폴레온 힐", "지니의서재"),
    ("당연한 것들을 의심하는 100가지 철학", "오가와 히토시", "이든서재"),
    ("일하는 사람을 위한 철학", "애니 로슨", "프런트페이지"),
    ("행복한 철학자", "우애령", "하늘재"),
    ("100세 철학자의 행복론", "김형석", "열림원"),
    ("미술관 여행자를 위한 도슨트 북", "카미유 주노", "윌북아트"),
    ("서울 한 바퀴, 둘레길 여행", "이준휘", "링크북스"),
    ("인생이 두 배 즐거워지는 자유 여행영어", "배진영", "다락원"),
    ("길 잃은 여행자를 위한 안내서", "묵명 권 진오", "e퍼플"),
    ("벌거벗은 한국사: 근현대편", "tvN STORY 〈벌거벗은 한국사〉 제작팀 저, 최태성 감수", "프런트페이지"),
    ("한국에 남자가 너무 많아서", "민지형", "라우더북스"),
    ("한국이란 무엇인가", "김영민", "어크로스"),
    ("2026 한국이 열광할 세계 트렌드", "KOTRA", "시공사"),
    ("세계 경제 지각 변동", "박종훈", "글로퍼스"),
    ("내가 보고 있는 세계는 진짜일까 : 버클리의 인식 수업", "조지 버클리", "아이보리잉크"),
    ("분쟁 지역을 읽으면 세계가 보인다", "김준형", "날"),
    ("처음 만나는 양자의 세계", "채은미", "북플레저"),
    ("다시, 공부머리 독서법: 영유아, 초등 저학년 편", "최승필", "책구루"),
    ("외우지 않는 공부법", "손의찬(메디소드)", "빅피시"),
    ("해외선물 처음공부", "김직선", "이레미디어"),
    ("나는 AI와 공부한다", "살만 칸", "RHK"),
    ("음악소설집", "김애란", "프란츠"),
    ("아라의 소설", "정세랑", "안온북스"),
    ("소설가라는 이상한 직업", "장강명", "유유히"),
    ("웹소설의 신", "이낙준(한산이가)", "비단숲"),
    ("경제신문이 말하지 않는 경제 이야기", "임주영", "민들레북"),
    ("드디어 만나는 경제학 수업", "앨프리드 밀", "현대지성"),
    ("홍춘욱의 최소한의 경제 토픽", "홍춘욱", "리더스북"),
    ("최소한의 경제공부", "문지웅", "매일경제신문사"),
    ("박곰희 연금 부자 수업", "박곰희", "인플루엔셜"),
    ("1퍼센트 부자의 법칙", "사이토 히토리", "나비스쿨"),
    ("부자들의 서재", "리치파카(강연주)", "카시오페아"),
    ("왜 그들만 부자가 되는가", "필립 바구스", "북모먼트"),
    ("빨모쌤의 라이브 영어회화", "신용하", "웅진지식하우스"),
    ("같은 생각 다른 표현: 영어토론 편", "장승진", "프랙티쿠스"),
    ("영어, 이번에는 끝까지 가봅시다", "정김경숙(로이스 김) 저", "웅진지식하우스"),
    ("주아쌤의 툭 치면 탁 나오는 영어회화", "주아쌤(이정은)", "몽스북"),
    ("부서지는 아이들", "애비게일 슈라이어", "웅진지식하우스"),
    ("아이들의 집", "정보라", "열림원"),
    ("천근아의 느린 아이 부모 수업", "천근아", "웅진지식하우스"),
    ("부모의 태도가 아이의 불안이 되지 않게", "애슐리 그래버 · 마리아 에번스", "부키"),
    ("엄마의 말 그릇", "김윤나", "카시오페아"),
    ("엄마의 자존감", "전미경", "카시오페아"),
    ("오늘도 불안한 엄마들에게", "양소영", "담담사무소"),
    ("엄마의 얼굴", "김재원", "달먹는토끼"),
    ("고전이 답했다 마땅히 살아야 할 삶에 대하여", "고명환", "라곰"),
    ("단 한 번의 삶", "김영하", "복복서가"),
    ("붙잡지 않는 삶", "에크하르트 톨레", "스노우폭스북스"),
    ("삶의 실력, 장자", "최진석", "위즈덤하우스"),
    ("느리게 나이 드는 습관", "정희원", "한빛라이프"),
    ("100일 아침 습관의 기적", "켈리 최", "다산북스"),
    ("경제가 쉬워지는 습관", "토리텔러", "좋은습관연구소"),
    ("디디미니의 맛있어서 평생 습관 되는 다이어트 레시피", "박지우", "빅피시"),
    ("먼저 온 미래", "장강명", "동아시아"),
    ("미래는 생성되지 않는다", "박주용", "동아시아"),
    ("오백 년째 열다섯 4: 구슬의 미래", "김혜정", "위즈덤하우스"),
]


def _slugify(title):
    base = re.sub(r"[^0-9A-Za-z가-힣]+", "-", title).strip("-").lower()
    return base or "book"


def _book(slug, title, author="", publisher=""):
    return {
        "slug": slug,
        "title": title,
        "author": author,
        "publisher": publisher,
        "summary": f"{title} 전자책을 서울 전자도서관에서 검색하고, 보유 도서관과 대출 가능 여부를 실시간으로 확인하세요.",
        "keywords": [f"{title} 전자도서관", f"{title} 전자책", f"{title} 대출"],
    }


def _build_books(rows):
    books = []
    seen_slugs = {}
    for title, author, publisher in rows:
        raw_slug = CUSTOM_SLUGS.get(title) or _slugify(title)
        count = seen_slugs.get(raw_slug, 0) + 1
        seen_slugs[raw_slug] = count
        slug = raw_slug if count == 1 else f"{raw_slug}-{count}"
        books.append(_book(slug, title, author, publisher))
    return books


STATIC_SEO_BOOKS = _build_books(_SEO_BOOK_ROWS)


def _store_path():
    return os.environ.get("SEO_BOOKS_PATH") or DEFAULT_AUTO_BOOKS_PATH


def _env_enabled(name, default="0"):
    value = os.environ.get(name, default)
    return str(value).strip().lower() not in {"", "0", "false", "no", "off"}


def _clean_text(value, limit=240):
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    return value[:limit]


def _book_key(book):
    title = re.sub(r"\s+", "", (book.get("title") or "").lower())
    author = re.sub(r"\s+", "", (book.get("author") or "").lower())
    return f"{title}|{author}"


def _valid_title(title):
    if not title or len(title) < 2 or len(title) > 80:
        return False
    if "?" in title or "\ufffd" in title:
        return False
    return bool(re.search(r"[0-9A-Za-z가-힣]", title))


def _library_count(item):
    counts = item.get("counts") or {}
    try:
        count = int(counts.get("total") or 0)
    except Exception:
        count = 0
    if count <= 0:
        count = len(item.get("libraries") or [])
    return count


def _stable_detail_present(item):
    if item.get("live_detail_key") or item.get("live_detail_url"):
        return True
    for lib in item.get("libraries") or []:
        if not isinstance(lib, dict):
            continue
        if lib.get("detail_url") or lib.get("brcd") or lib.get("content_id") or lib.get("isbn"):
            return True
    return False


def _match_text(value):
    return re.sub(r"[^0-9a-z가-힣]", "", str(value or "").lower())


def _score_match(candidate, item):
    title = _match_text(candidate.get("title"))
    item_title = _match_text(item.get("title"))
    author = _match_text(candidate.get("author"))
    item_author = _match_text(item.get("author"))
    publisher = _match_text(candidate.get("publisher"))
    item_publisher = _match_text(item.get("publisher"))
    score = 0
    reasons = []

    if not _valid_title(candidate.get("title")):
        return -100, ["제목 형식이 안정적이지 않습니다."]

    if title and item_title:
        if title == item_title:
            score += 45
            reasons.append("제목 일치")
        elif title in item_title or item_title in title:
            score += 30
            reasons.append("제목 유사")
        else:
            score -= 80
            reasons.append("제목 불일치")

    if author and item_author:
        if author == item_author:
            score += 25
            reasons.append("저자 일치")
        elif author in item_author or item_author in author:
            score += 15
            reasons.append("저자 유사")
        else:
            score -= 25
            reasons.append("저자 불일치")
    elif author or item_author:
        score += 5
        reasons.append("저자 정보 일부 확인")

    if publisher and item_publisher:
        if publisher == item_publisher:
            score += 15
            reasons.append("출판사 일치")
        elif publisher in item_publisher or item_publisher in publisher:
            score += 8
            reasons.append("출판사 유사")
    elif publisher or item_publisher:
        score += 4
        reasons.append("출판사 정보 일부 확인")

    library_count = _library_count(item)
    if library_count >= 10:
        score += 12
        reasons.append("보유 도서관 10곳 이상")
    elif library_count >= _min_library_count():
        score += 8
        reasons.append("보유 도서관 기준 충족")
    else:
        score -= 20
        reasons.append("보유 도서관 기준 미달")

    if item.get("image_url"):
        score += 5
        reasons.append("표지 확인")
    if _stable_detail_present(item):
        score += 5
        reasons.append("상세 식별자 확인")

    return score, reasons


def _best_validation_match(candidate, items):
    best = None
    best_score = -999
    best_reasons = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        score, reasons = _score_match(candidate, item)
        if score > best_score:
            best = item
            best_score = score
            best_reasons = reasons
    return best, best_score, best_reasons


def _auto_capture_enabled():
    return _env_enabled("SEO_AUTO_CAPTURE", "0")


def _dynamic_books_enabled():
    return _env_enabled("SEO_DYNAMIC_BOOKS", "0")


def _capture_limit():
    try:
        return max(1, min(int(os.environ.get("SEO_CAPTURE_LIMIT", "10")), 20))
    except ValueError:
        return 10


def _min_library_count():
    try:
        return max(1, int(os.environ.get("SEO_MIN_LIBRARY_COUNT", "3")))
    except ValueError:
        return 3


def _empty_store():
    return {"version": STORE_VERSION, "books": []}


def _read_store():
    path = _store_path()
    if not os.path.exists(path):
        return _empty_store()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return _empty_store()
    if isinstance(data, list):
        return {"version": STORE_VERSION, "books": data}
    if not isinstance(data, dict):
        return _empty_store()
    books = data.get("books")
    if not isinstance(books, list):
        data["books"] = []
    data["version"] = STORE_VERSION
    return data


def _write_store(store):
    path = _store_path()
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def _published_dynamic_books():
    if not _dynamic_books_enabled():
        return []
    store = _read_store()
    return [
        _book(
            book.get("slug") or _slugify(book.get("title") or ""),
            _clean_text(book.get("title"), 160),
            _clean_text(book.get("author"), 160),
            _clean_text(book.get("publisher"), 160),
        )
        for book in store.get("books", [])
        if book.get("status") == "published" and _valid_title(_clean_text(book.get("title"), 160))
    ]


def get_seo_books():
    books = []
    seen = set()
    for book in [*STATIC_SEO_BOOKS, *_published_dynamic_books()]:
        key = _book_key(book)
        if not key or key in seen:
            continue
        seen.add(key)
        books.append(book)
    return books


def get_seo_book_by_slug(slug):
    slug = (slug or "").strip()
    for book in get_seo_books():
        if book.get("slug") == slug:
            return book
    return None


def record_search_results(query, payload):
    if not _auto_capture_enabled():
        return 0
    query = _clean_text(query, 120)
    items = (payload or {}).get("items") or []
    if not query or not items:
        return 0

    now = int(time.time())
    min_libraries = _min_library_count()
    limit = _capture_limit()

    with _STORE_LOCK:
        store = _read_store()
        dynamic_books = store.setdefault("books", [])
        static_keys = {_book_key(book) for book in STATIC_SEO_BOOKS}
        by_key = {_book_key(book): book for book in dynamic_books if isinstance(book, dict)}
        slug_to_key = {
            book.get("slug"): _book_key(book)
            for book in [*STATIC_SEO_BOOKS, *dynamic_books]
            if isinstance(book, dict) and book.get("slug")
        }

        changed = 0
        captured = 0
        for item in items:
            if captured >= limit:
                break
            if not isinstance(item, dict):
                continue

            title = _clean_text(item.get("title"), 160)
            author = _clean_text(item.get("author"), 160)
            publisher = _clean_text(item.get("publisher"), 160)
            if not _valid_title(title):
                continue

            library_count = _library_count(item)
            if library_count < min_libraries:
                continue

            key = _book_key({"title": title, "author": author})
            if key in static_keys:
                captured += 1
                continue

            existing = by_key.get(key)
            if existing:
                existing["last_seen"] = now
                existing["search_count"] = int(existing.get("search_count") or 0) + 1
                existing["library_count"] = max(int(existing.get("library_count") or 0), library_count)
                if query and query not in existing.setdefault("source_queries", []):
                    existing["source_queries"] = (existing["source_queries"] + [query])[-10:]
                changed += 1
                captured += 1
                continue

            base_slug = CUSTOM_SLUGS.get(title) or _slugify(title)
            slug = base_slug
            suffix = 2
            while slug in slug_to_key and slug_to_key[slug] != key:
                slug = f"{base_slug}-{suffix}"
                suffix += 1
            slug_to_key[slug] = key

            book = {
                "slug": slug,
                "title": title,
                "author": author,
                "publisher": publisher,
                "status": "candidate",
                "library_count": library_count,
                "search_count": 1,
                "first_seen": now,
                "last_seen": now,
                "source_queries": [query],
                "validation": {"score": 0, "reasons": []},
            }
            dynamic_books.append(book)
            by_key[key] = book
            changed += 1
            captured += 1

        if changed:
            _write_store(store)
        return changed


def review_seo_candidates(
    search_func,
    limit=50,
    auto_publish=False,
    approve_threshold=DEFAULT_APPROVE_THRESHOLD,
    publish_threshold=DEFAULT_PUBLISH_THRESHOLD,
    dry_run=False,
):
    now = int(time.time())
    with _STORE_LOCK:
        store = _read_store()
        candidates = [
            dict(book)
            for book in store.get("books", [])
            if isinstance(book, dict) and book.get("status") in {"candidate", "approved", "stale"}
        ][: max(1, int(limit or 50))]

    summary = {
        "checked": 0,
        "approved": 0,
        "published": 0,
        "rejected": 0,
        "unchanged": 0,
        "errors": 0,
    }
    updates = {}

    for candidate in candidates:
        key = _book_key(candidate)
        if not key:
            continue
        summary["checked"] += 1
        updated = dict(candidate)
        try:
            payload = search_func(
                query=candidate.get("title") or "",
                field="title",
                providers_raw="",
                libraries_raw="",
                limit=20,
                offset=0,
            )
            best, score, reasons = _best_validation_match(candidate, (payload or {}).get("items") or [])
            if not best:
                reasons = ["검증 가능한 검색 결과가 없습니다."]
            updated["validated_at"] = now
            updated["validation"] = {
                "score": score,
                "reasons": reasons,
                "matched_title": (best or {}).get("title") or "",
                "matched_author": (best or {}).get("author") or "",
            }
            if best:
                updated["library_count"] = max(int(updated.get("library_count") or 0), _library_count(best))
                if best.get("image_url"):
                    updated["image_url"] = best.get("image_url")
                if best.get("live_detail_url"):
                    updated["live_detail_url"] = best.get("live_detail_url")
                if best.get("live_detail_key"):
                    updated["live_detail_key"] = best.get("live_detail_key")

            if score >= publish_threshold and auto_publish:
                updated["status"] = "published"
                updated["published_at"] = updated.get("published_at") or now
                summary["published"] += 1
            elif score >= approve_threshold:
                updated["status"] = "approved"
                summary["approved"] += 1
            else:
                updated["status"] = "rejected"
                summary["rejected"] += 1
        except Exception as exc:
            updated["validated_at"] = now
            updated["validation"] = {
                "score": 0,
                "reasons": [f"검증 중 오류: {exc}"],
            }
            summary["errors"] += 1
        updates[key] = updated

    if not dry_run and updates:
        with _STORE_LOCK:
            store = _read_store()
            changed = False
            for idx, book in enumerate(store.get("books", [])):
                key = _book_key(book)
                if key in updates:
                    store["books"][idx] = updates[key]
                    changed = True
            if changed:
                _write_store(store)
    elif dry_run:
        summary["dry_run"] = True

    summary["unchanged"] = max(0, summary["checked"] - summary["approved"] - summary["published"] - summary["rejected"] - summary["errors"])
    return summary


SEO_BOOKS = get_seo_books()
SEO_BOOK_BY_SLUG = {book["slug"]: book for book in SEO_BOOKS}

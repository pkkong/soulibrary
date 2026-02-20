import json
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
CURATION_DATA_PATH = ROOT_DIR / "data" / "curations.json"
CURATION_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates" / "curations"

HOME_STYLE_OPTIONS = [
    {
        "value": "hero",
        "label": "hero (대표 표지)",
        "description": "대표 표지 1권을 크게 보여주는 하이라이트형",
    },
    {
        "value": "ranked",
        "label": "ranked (순위형)",
        "description": "순번 + 표지 + 제목/저자로 랭킹 목록을 보여주는 형식",
    },
    {
        "value": "basic",
        "label": "basic (기본 카드)",
        "description": "표지 중심의 가장 기본적인 카드형",
    },
    {
        "value": "tilt",
        "label": "tilt (3D 표지)",
        "description": "기울어진 표지를 강조해 시각 임팩트를 주는 형식",
    },
    {
        "value": "editorial",
        "label": "editorial (매거진형)",
        "description": "표지와 제목/저자를 균형 있게 보여주는 에디토리얼형",
    },
    {
        "value": "compact",
        "label": "compact (간결형)",
        "description": "작은 표지 + 메타 정보로 여러 권을 빠르게 훑는 형식",
    },
    {
        "value": "news",
        "label": "news (배너+좌우버튼)",
        "description": "뉴스/프로모션 배너처럼 좌우 버튼으로 넘기는 형식",
    },
]

HOME_STYLE_VALUES = {item["value"] for item in HOME_STYLE_OPTIONS}

DEFAULT_CURATIONS = [
    {
        "slug": "cafe",
        "title": "디지털 e북 카페 추천 도서",
        "summary": "네이버 전자책 카페에서 추천받은 도서 목록을 모았습니다.",
        "book_ids": [1163, 1653, 3900, 2361, 62991, 165705, 269836, 239293],
    },
    {
        "slug": "bitcoin",
        "title": "비트코인을 공부하기 위해 필요한 책들",
        "summary": "입문부터 이해에 도움이 되는 핵심 도서를 정리했습니다.",
        "book_ids": [29621, 293944, 231444, 234760, 303558, 182651],
    },
    {
        "slug": "faker-top10",
        "title": "페이커가 읽었다고 알려진 인생 책 10선",
        "summary": "독서로 마인드셋을 다듬는다고 알려진 페이커의 추천 리스트와 이유를 정리했습니다.",
        "content_template": "curations/faker-top10.html",
        "feature_image": "http://www.gameculture.or.kr/data/editor/2510/20251027092538_a918d0a3bac8cb81b87d6774f3d8c394_1u05.png",
        "book_ids": [25667, 10693, 7997, 12235, 13092, 9347, 60960, 10973, 10657, 261593],
    },
    {
        "slug": "chanho",
        "title": "'찬호께이' 작가의 추천 도서",
        "summary": "작가 ‘찬호께이’의 주요 작품을 모았습니다.",
        "book_ids": [261, 7939, 31037, 439973, 275025],
    },
    {
        "slug": "jeongyujeong",
        "title": "'정유정' 작가의 추천 도서",
        "summary": "정유정 작가의 주요 작품을 모았습니다.",
        "book_ids": [311288, 458653, 456403, 459032, 460178],
    },
    {
        "slug": "jeonghaeyeon",
        "title": "'정해연' 작가의 추천 도서",
        "summary": "정해연 작가의 주요 작품을 모았습니다.",
        "book_ids": [1749, 2666, 2792, 4727, 9221],
    },
]

_CURATIONS_CACHE = {"mtime": None, "data": None}


def _normalize_payload(raw):
    if isinstance(raw, dict) and "curations" in raw:
        raw = raw.get("curations")
    if not isinstance(raw, list):
        return None
    return raw


def get_curations():
    if CURATION_DATA_PATH.exists():
        mtime = CURATION_DATA_PATH.stat().st_mtime
        if _CURATIONS_CACHE["data"] is not None and _CURATIONS_CACHE["mtime"] == mtime:
            return _CURATIONS_CACHE["data"]
        try:
            data = json.loads(CURATION_DATA_PATH.read_text(encoding="utf-8"))
            curations = _normalize_payload(data) or DEFAULT_CURATIONS
        except Exception:
            curations = DEFAULT_CURATIONS
        _CURATIONS_CACHE.update({"mtime": mtime, "data": curations})
        return curations
    return DEFAULT_CURATIONS


def get_curation_map():
    return {c.get("slug"): c for c in get_curations() if c.get("slug")}


def save_curations(curations):
    payload = {"curations": curations}
    CURATION_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    CURATION_DATA_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _CURATIONS_CACHE.update({"mtime": CURATION_DATA_PATH.stat().st_mtime, "data": curations})


def curation_template_path(slug):
    filename = f"{slug}.html"
    return CURATION_TEMPLATE_DIR / filename

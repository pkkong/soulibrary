import requests
import urllib3

# SSL 경고 메시지 끄기 (지저분해서)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 🚨 [업데이트] 최신 'elib' 주소 및 HTTPS 적용 목록
TARGETS = {
    "강동구": "https://elib.gdlibrary.or.kr", 
    "강북구": "https://elib.gangbuklib.seoul.kr",
    "광진구": "https://elib.gwangjinlib.seoul.kr",
    "구로구": "https://elib.guro.go.kr",
    "노원구": "https://elib.nowonlib.kr",
    "도봉구": "https://elib.dobonglib.seoul.kr",
    "마포구(완료)": "https://ebook.mapo.go.kr", # (비교용)
    "서대문구": "https://elib.sdm.or.kr",
    "성동구": "https://elib.sdlib.or.kr",
    "중구": "https://elib.junggu.seoul.kr",
    "중랑구": "https://elib.jungnanglib.seoul.kr",
    "관악구": "https://elib.gwanaklib.seoul.kr"
}

def check_platform(name, url):
    try:
        # 1. 접속 시도 (SSL 검증 무시 verify=False, 리다이렉트 허용)
        res = requests.get(url, timeout=15, allow_redirects=True, verify=False)
        final_url = res.url
        html = res.text

        # --- 플랫폼 판별 로직 ---

        # 1. 교보문고 (가장 흔함)
        if "Kyobo_T3" in final_url or "Kyobo_T3" in html:
            return "📚 교보문고 (구버전 T3) -> [마포구 코드 복사 가능!]"
        elif "elibrary-front" in final_url or "/search/searchResult" in final_url:
            return "🆕 교보문고 (신버전) -> [용산구 코드 복사 가능!]"
        
        # 2. YES24
        elif "yes24" in final_url or "ebook_list.asp" in final_url or "/ebook/list.asp" in final_url:
            return "📘 YES24 -> [새 크롤러 필요]"
        
        # 3. OPMS (웅진)
        elif "opms" in final_url or "opms" in html or "/main/main.do" in final_url:
            return "🟧 OPMS (웅진) -> [새 크롤러 필요]"
        
        # 4. 북큐브
        elif "bookcube" in final_url:
            return "🟩 북큐브 -> [새 크롤러 필요]"

        else:
            # 힌트 찾기 (HTML title 태그 등)
            import re
            title_match = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE)
            title = title_match.group(1) if title_match else "제목없음"
            return f"❓ 확인 필요 (Title: {title}) - URL: {final_url}"

    except Exception as e:
        return f"❌ 접속 실패 ({str(e)})"

print("--- [서울시 미구축 도서관 플랫폼 2차 조사] ---")
for name, url in TARGETS.items():
    print(f"검사 중... [{name}]")
    result = check_platform(name, url)
    print(f"👉 결과: {result}\n")
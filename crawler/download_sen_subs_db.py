import requests
import pandas as pd
import time
import os

# 저장 경로
OUTPUT_FILE = "../data/sen_subs_db.csv"  # "구독형" 전용 DB 파일

# API 설정 (구독형 1개만)
URL_SUBS = "https://e-lib.sen.go.kr/api/contents/catesearch"
CONTENT_TYPE_SUBS = "TY02"
LABEL = "구독형"

def download_sen_api(url, content_type, label):
    """
    '구독형' API를 1000개씩 반복 호출하여 다운로드합니다.
    Ctrl+C(KeyboardInterrupt)를 누르면 그때까지 수집한 데이터만 반환합니다.
    """
    all_books = []
    page = 1
    per_page = 1000  # 1000개씩 요청 (원하면 100으로 줄여서 테스트 가능)

    print(f"--- [서울시교육청] '{label}' ({content_type}) API 다운로드 시작 ---")

    try:
        while True:
            # [핵심] 모든 파라미터 전송
            params = {
                "contentType": content_type, "majorCategory": "", "subCategory": "",
                "tinyCategory": "", "ownerCategory": "", "innerSearchYN": "N",
                "innerKeyword": "", "orderOption": "1", "typeOption": "1",
                "currentCount": page,
                "pageCount": per_page,
                "loanable": "N",
                "_": int(time.time() * 1000)
            }

            print(f"Page {page} ({per_page}개씩) 요청 중... ", end="")

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Referer": "https://e-lib.sen.go.kr/"
            }

            response = requests.get(url, params=params, headers=headers, timeout=60)
            response.raise_for_status()

            # ★★★ JSON 파싱 ★★★
            data = response.json()

            # ★★★ 구독형 전용 경로: CategoryDataList.responses 기준 (이전에 XML로 보던 구조) ★★★
            book_list = []
            if 'CategoryDataList' in data:
                book_list = data['CategoryDataList'].get('responses', [])
            elif 'contents' in data:
                # 혹시라도 contents 경로로 내려오는 예외 케이스 대비
                book_list = data['contents'].get('ContentDataList', [])

            # 디버깅용: 첫 페이지에서 구조 확인하고 싶으면 아래 주석 해제
            # if page == 1:
            #     print("DEBUG keys:", data.keys())
            #     print("DEBUG sample:", book_list[0] if book_list else "no sample")

            if not book_list:
                print("데이터 없음. (완료)")
                break

            print(f"성공! ({len(book_list)}권)")

            # JSON에서 데이터 뽑기 (구독형 필드 이름 기준)
            for book_json in book_list:
                # 오디오북 필터링
                file_type = book_json.get('ucm_file_type')
                if file_type == 'AUDIO':
                    continue  # 오디오북은 건너뛰기

                all_books.append({
                    'title': book_json.get('ucm_title'),
                    'author': book_json.get('ucm_writer'),
                    'publisher': book_json.get('ucp_brand'),
                    'image_url': book_json.get('ucm_cover_url')
                })

            # 마지막 페이지 체크
            if len(book_list) < per_page:
                print(f"--- '{label}' 수집 완료 ---")
                break

            page += 1
            time.sleep(1)  # 1000개씩이니 1초 쉬기

    except KeyboardInterrupt:
        # 사용자가 Ctrl+C로 중단했을 때
        print(f"\n🛑 Ctrl+C 감지! 지금까지 수집한 {len(all_books)}권만 사용합니다.")

    except Exception as e:
        # 기타 오류 발생 시
        print(f"\n[오류] Page {page} 요청 실패: {e}")
        print(f"지금까지 수집한 {len(all_books)}권만 사용합니다.")

    # 정상 종료든, Ctrl+C든, 에러든 지금까지 모은 것 반환
    return all_books


def save_to_csv(books):
    if not books:
        print("저장할 데이터가 없습니다.")
        return

    print(f"\n데이터 통합 및 저장 중... (총 {len(books)}권)")
    df = pd.DataFrame(books)

    df['library'] = '서울시교육청 (구독형)'

    # 중복 제거 (제목+저자)
    df = df.drop_duplicates(subset=['title', 'author'])
    print(f"-> 중복 제거 후 최종 {len(df)}권")

    final_df = df[['title', 'author', 'publisher', 'library', 'image_url']]

    final_df.to_csv(OUTPUT_FILE, index=False, encoding='utf-8-sig')
    print(f"✅ 저장 완료: {OUTPUT_FILE}")


# --- 메인 실행 ---
if __name__ == "__main__":
    # 1. 구독형(TY02)만 다운로드
    subs_data = download_sen_api(URL_SUBS, CONTENT_TYPE_SUBS, LABEL)

    # 2. 저장 (Ctrl+C로 중단했어도, 그때까지 수집한 데이터 저장)
    save_to_csv(subs_data)

# 1. 파이썬 3.11 버전을 기반으로 한다
FROM python:3.11-slim

# 2. 서버 내 작업 폴더를 설정한다
WORKDIR /app

# 3. 현재 폴더의 모든 파일을 서버의 /app으로 복사한다
COPY . /app

# 4. 필요한 라이브러리를 설치한다
RUN pip install --no-cache-dir -r requirements.txt

# 5. web 폴더로 이동해서 검색 앱을 실행한다
WORKDIR /app/web
ENV LIBRARY_SEARCH_PORT=5000
CMD ["sh", "-c", "gunicorn --no-control-socket --bind 0.0.0.0:${PORT:-5000} --workers ${WEB_CONCURRENCY:-2} --threads ${GUNICORN_THREADS:-4} --timeout ${GUNICORN_TIMEOUT:-120} app_search:app"]

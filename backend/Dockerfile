FROM python:3.11-slim-bookworm
ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai
WORKDIR /app
# WPS uses Chromium; Chinese fonts keep page layout stable.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl tzdata chromium fonts-noto-cjk \
 && rm -rf /var/lib/apt/lists/*
# SQL Server uses pymssql / FreeTDS from the Python requirements.
COPY requirements.txt ./
RUN pip install --no-cache-dir -i "$PIP_INDEX_URL" -r requirements.txt
COPY alembic.ini docker-entrypoint.sh ./
COPY alembic ./alembic
COPY app ./app
COPY scripts ./scripts
RUN chmod +x docker-entrypoint.sh
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/health || exit 1
ENTRYPOINT ["./docker-entrypoint.sh"]

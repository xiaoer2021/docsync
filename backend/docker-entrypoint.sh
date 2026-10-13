#!/bin/sh
# 容器启动：先把元数据库升到最新结构，再起服务。
# 这样升级镜像时不用人工记得跑迁移。
set -e

echo "[docsync] 检查元数据库结构…"
if [ "${DOCSYNC_AUTO_SETUP:-false}" = "true" ]; then
    python scripts/bootstrap_config.py
    set -a
    . "${DOCSYNC_DATA_DIR:-./data}/runtime.env"
    set +a
    python -m app.cli bootstrap
else
    python -m app.cli initdb
fi

echo "[docsync] 启动 API 服务…"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000

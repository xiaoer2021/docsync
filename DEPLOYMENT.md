# 安装、初始化与维护

首次安装见 README，本说明适用于任意自托管实例。

## 配置

| 配置 | 用途 |
|---|---|
| `DOCSYNC_ENV` | 安装默认 prod，要求主密钥及显式设置的至少 32 字符 JWT 密钥 |
| `DOCSYNC_MASTER_KEY` | Fernet 凭证加密主密钥，安装后保持不变 |
| `DOCSYNC_JWT_SECRET` | 登录签名密钥，安装后保持稳定 |
| `DOCSYNC_META_DB_URL` | 手动默认 SQLite；Compose 从 `MYSQL_PASSWORD` 自动拼接 MySQL 地址 |
| `DOCSYNC_DATA_DIR` | 日志、临时文件、默认浏览器档案及下载缓存根目录 |
| `DOCSYNC_BROWSER` | 可选 Chromium/Chrome/Edge 可执行文件完整路径 |
| `DOCSYNC_BROWSER_PROFILES_DIR` | 可选档案位置，Compose 保留 `/data/browser` 挂载兼容现有实例 |
| `DOCSYNC_WPS_DOWNLOAD_DIR` | 可选下载位置；旧 `WPS_DOWNLOAD_DIR` 仍兼容 |
| `DOCSYNC_CORS_ORIGINS` | 默认空数组；跨域时用 JSON 数组，如 `["https://sync.example.com"]` |
| `MYSQL_PASSWORD` / `MYSQL_ROOT_PASSWORD` | Docker 空库创建口令，更改 env 不会自动改已有数据库用户口令 |
| `WEB_PORT` | 对外端口，默认 8090，API 内部固定 8000 |
| SQL Server 驱动 | 使用 requirements 中的 pymssql，构建无需微软 ODBC 驱动 |
| `PIP_INDEX_URL` | 可选 Docker 构建包源 |

配置生成器创建独立密钥，`python -m app.cli setup` 迁移表结构并交互创建首个管理员。重复初始化保留现有配置、账号和数据。修改已有口令用 `reset-password --username <账号>`，省略 `--password` 即交互输入。
生产只运行一个 API 进程，内嵌调度器在多个 workers/副本中可能重复派发任务。不要将某个实例的 `.env` 作为默认配置分发。

## 检查

```bash
docker compose ps
docker compose exec api python -m app.cli check
docker compose logs --tail 100 api
```

访问 `/health` 检查 `database.ok`、`scheduler.running` 和队列。HTTP 成功不单独证明调度正常，启用自动任务时应检查 `scheduler.running=true`。业务成功需核对执行结果和目标库。

## 备份及升级

升级前暂停自动任务或在空闲窗口停 API，备份 `.env`、元数据库及 `data/`。Docker MySQL 在 `mysql-data` 卷中，停库后可物理快照；运行中的数据库应使用一致性逻辑导出。手动 SQLite 停后端再复制数据库及必要 WAL 文件。
完成备份后执行：

```bash
docker compose stop api web
docker compose up -d --build --wait
docker compose exec api python -m app.cli check
```

保留原 `.env`，不要重新生成密钥。容器启动自动升级元数据库；回退须同时恢复旧代码和迁移前数据库备份。
禁止 `docker compose down -v`，它会删除 MySQL 数据卷。登录档案及 `.broken-*` 副本可能有可恢复登录态，不能当普通缓存清理。
SQLite 转 MySQL 维护脚本为 `backend/scripts/migrate_sqlite_to_mysql.py`。仅对一致性快照执行，目标 MySQL 先迁移且业务表为空；脚本按表核对数量。它不是首次初始化必要步骤。

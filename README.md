# docsync · 文档同步中心

将在线表格同步到数据库，并按需触发下游刷新。通过网页登记文档、预览子表、配置字段映射、写入策略及定时任务，无需为每份文档编写脚本。
完整前后端源码、连接器、迁移及测试均在本仓库，采用 [MIT](LICENSE) 许可，允许修改、商用及自行部署。第三方依赖和品牌说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 当前支持

| 来源/目标 | 支持方式 |
|---|---|
| 钉钉电子表格、AI/多维表格 | 开放平台 API，配置应用凭证及文档权限 |
| 飞书电子表格、多维表格 | 开放平台 API，配置应用凭证及文档权限 |
| WPS 个人版表格 | Chromium 登录/网页授权后下载 xlsx，按工作表名读取，需文档导出权限 |
| WPS 开发者 API、Google 及其他平台入口 | 尚未实现，不能作为可用连接器使用 |
| 目标数据库 | MySQL、SQL Server |
| 元数据库 | Docker 默认 MySQL 8；手动安装默认 SQLite，也可自行配置 MySQL |

WPS 个人版依赖平台网页及下载服务，属于尽力兼容，不是官方 OpenAPI 接入。公开分享不保证允许导出，私有文档需登录。生产同步不再使用剪贴板复制。
支持表头选择、合并单元格、日期交叉表、跳过/替换规则、多值拆分、类型转换、异常原文保留、自动建表/补列、主键更新、追加、分区覆盖及整表重写。支持定时调度、实时日志、执行历史、Webhook、钉钉机器人和下游接口动作。

## Docker 安装（推荐）

需要 Docker Engine/Desktop 和 Compose v2。配置生成器仅需 Python 3.10+ 标准库；推荐 Python 3.11。在项目根目录执行：

```bash
python scripts/init_config.py --mode docker
docker compose up -d --build --wait
docker compose exec api python -m app.cli setup
docker compose exec api python -m app.cli check
```

初始化时输入自己的管理员口令，没有默认口令。访问 `http://localhost:8090`，以 `admin` 登录。远程安装将 localhost 换成服务器地址。`.env` 中的 `WEB_PORT` 可调整访问端口。
没有 Python 时，Linux/macOS 用以下命令替代第一步：

```bash
docker run --rm -v "$PWD:/workspace" -w /workspace python:3.11-slim python scripts/init_config.py --mode docker
```

Windows PowerShell：

```powershell
docker run --rm -v "${PWD}:/workspace" -w /workspace python:3.11-slim python scripts/init_config.py --mode docker
```

生成器自动创建独立主密钥、登录密钥和 MySQL 口令。已有 `.env` 时拒绝覆盖；`setup` 可重复执行，保留已有可用管理员及业务数据。Docker 启动自动迁移数据库，首个管理员由命令主动创建。

## 手动运行前后端

推荐 Python 3.11、Node.js 22。SQLite 元数据库无需安装 MySQL，目标业务库仍需用户提供。
Linux/macOS 后端：

```bash
python3 scripts/init_config.py --mode manual
cd backend
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m app.cli setup
python -m app.cli check
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Windows PowerShell 后端：

```powershell
py -3.11 scripts/init_config.py --mode manual
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m app.cli setup
.\.venv\Scripts\python.exe -m app.cli check
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

另开终端，从项目根目录启动前端：

```bash
cd frontend
npm ci
npm run dev -- --host 127.0.0.1
```

访问 `http://127.0.0.1:5273`，前端将 `/api`、`/health` 代理到后端。后端须从 `backend/` 执行，读取根目录 `.env`；SQLite 及运行数据在 `backend/data/`。手动安装不要使用 Docker 模式数据库连接。
Windows 完成依赖及初始化后，也可双击 `start.bat` 后台启动、`stop.bat` 停止本项目进程，日志位于根目录 `data/`。
WPS 手动运行需 Chromium、Chrome 或 Edge。程序寻找常见路径，也可在 `.env` 设置 `DOCSYNC_BROWSER` 为可执行文件完整路径。Linux 安装 `chromium` 和 `fonts-noto-cjk`；Docker 镜像已包含。档案与缓存随 `DOCSYNC_DATA_DIR` 持久化，不依赖容器专用路径。
生产托管使用 `npm run build`，由 nginx 等静态服务器托管 `frontend/dist`，将 `/api`、`/health` 代理到后端并配置 HTTPS。Vite 仅用于开发。内嵌调度部署只能运行一个 API 进程，不要增加 uvicorn workers 或多个副本。

## 首次使用

1. 添加钉钉、飞书或 WPS 应用，完成权限配置或登录。
2. 添加目标数据库并测试连接。
3. 登记文档链接并确认工作表清单。
4. 创建任务，选择工作表、表头、字段映射及目标表。
5. 先试跑核对行数、类型和计划，再正式执行并检查目标库。
6. 最后配置调度与后置动作。
首次安装不预置业务应用、数据源、文档和定时任务，不会自动同步业务数据。

## 数据处理边界

- 主键、必填和明确指定的关键列转换失败时，写入前停止。
- 普通异常格可在业务列留空并保留原文到 `原始值_未识别`，执行日志记录异常数量。此时仍可能显示成功，需主动核对质量信息。
- 日期交叉表读取中的公式错误格按当前规则取 0，不保证等同 Excel 重算结果；日期顺序不明确时不猜。
- 覆盖写入和删除对账检查限行、读取上限、增量及必填缺失等条件。整表重写在原表至少 100 行时，默认不足原表 50% 则停止，可调整比例。
- 试跑不写目标表，成功也不等于正式写库或后置动作成功。
配置及维护见 [DEPLOYMENT.md](DEPLOYMENT.md)。

## 开发与发行

```bash
cd backend
python -m ruff check app tests scripts ../scripts
python -m pytest -q
cd ../frontend
npm ci
npm run build
npm audit
```

`backend/app` 为后端业务，`backend/alembic` 为迁移，`backend/tests` 为测试，`frontend/src` 为前端，`scripts` 为安装及发布工具。扩展约定见 [CONTRIBUTING.md](CONTRIBUTING.md)，安全边界见 [SECURITY.md](SECURITY.md)。

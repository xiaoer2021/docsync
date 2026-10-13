# Linux 部署与维护

从服务器上没有项目开始，选择下面一种部署方式。示例以 Debian 12、Python 3.11、Node.js 22 和 x86_64 为基准。已有实例先按后文备份，再升级，不要重新初始化密钥。

## 单文件 Docker 部署

先安装 Docker Engine 和 Compose v2，参考 [Docker 官方安装说明](https://docs.docker.com/engine/install/)。然后：

```bash
mkdir -p ~/docsync
cd ~/docsync
curl -fsSL https://raw.githubusercontent.com/xiaoer2021/docsync/main/docker-compose.yml -o docker-compose.yml
docker compose up -d --build --wait --wait-timeout 300
docker compose exec api cat /app/data/initial-admin-password
```

不需要 Git、Python、Node.js、MySQL 或 `.env`。Docker 自行拉取仓库并构建镜像，首次启动自动生成密钥、迁移元数据库、创建 `admin` 账号。查看随机密码后访问 `http://服务器IP:8090`。宿主机只开放前端 8090，API 8000 不对外发布。

初始化仅在首次安装生效；已有账号或数据不会重置。数据、密钥、下载缓存与浏览器档案均在命名卷。改密码后，初始密码文件可移除，它不用于重置口令。

## 拉取源码后使用 Docker

```bash
git clone https://github.com/xiaoer2021/docsync.git
cd docsync
docker compose up -d --build --wait --wait-timeout 300
docker compose exec api cat /app/data/initial-admin-password
```

默认 Compose 从 GitHub 构建。若要用当前目录的代码构建，在项目根目录创建覆盖文件 `compose.local.yml`：

```yaml
services:
  api:
    build:
      context: ./backend
  web:
    build:
      context: ./frontend
```

然后执行：

```bash
docker compose -f docker-compose.yml -f compose.local.yml up -d --build --wait --wait-timeout 300
```

## Linux 手动部署前后端

手动部署使用 Python 运行后端、Node.js 构建前端、Nginx 提供页面，systemd 保持后端运行。前端构建完成后不需要常驻 Node.js 服务。

### 1. 安装环境并从 GitHub 获取项目

以下命令适用于 Debian 12 的全新安装。其他发行版使用相应包管理器，Python 应为 3.10+，推荐 3.11：

```bash
sudo apt-get update
sudo apt-get install -y git curl ca-certificates python3 python3-venv nginx
curl -fsSL https://deb.nodesource.com/setup_22.x -o /tmp/docsync-node-setup.sh
sudo bash /tmp/docsync-node-setup.sh
sudo apt-get install -y nodejs
id docsync >/dev/null 2>&1 || sudo useradd --system --create-home --home-dir /var/lib/docsync --shell /usr/sbin/nologin docsync
sudo git clone https://github.com/xiaoer2021/docsync.git /opt/docsync
sudo chown -R docsync:docsync /opt/docsync
python3 --version
node --version
```

Node.js 安装脚本来自 NodeSource。已有 Node.js 22 时可以跳过这部分。需要 WPS 时另安装浏览器及字体：

```bash
sudo apt-get install -y chromium fonts-noto-cjk
```

Ubuntu 的 Chromium 安装方式可能使用 Snap，需按发行版确认浏览器能被服务账号以无头模式启动；也可设置 `DOCSYNC_BROWSER` 为已有 Chrome/Chromium 完整路径。

### 2. 安装并初始化后端

```bash
sudo -u docsync python3 -m venv /opt/docsync/backend/.venv
sudo -u docsync /opt/docsync/backend/.venv/bin/python -m pip install -r /opt/docsync/backend/requirements.txt
sudo -u docsync /opt/docsync/backend/.venv/bin/python /opt/docsync/scripts/init_config.py --mode manual
cd /opt/docsync/backend
sudo -u docsync .venv/bin/python -m app.cli setup
sudo -u docsync .venv/bin/python -m app.cli check
sudo chmod 600 /opt/docsync/.env
sudo chmod 700 /opt/docsync/backend/data
```

`setup` 交互输入管理员口令。配置生成器拒绝覆盖已有 `.env`。手动模式默认元数据库为 `/opt/docsync/backend/data/docsync.db`，应用凭证、日志和浏览器档案也保存在 `backend/data/`。这与 Docker 的命名卷是不同存储位置。

### 3. 将后端交给 systemd

```bash
sudo cp /opt/docsync/deploy/linux/docsync.service /etc/systemd/system/docsync.service
sudo systemctl daemon-reload
sudo systemctl enable --now docsync
sudo systemctl status docsync --no-pager
curl --fail http://127.0.0.1:8000/health
```

服务以 `docsync` 账号运行，工作目录固定为 `/opt/docsync/backend`，自动读取父目录 `.env`，仅监听本机 8000。只运行一个 worker，避免重复调度。更换项目路径时同步修改服务文件。

### 4. 构建前端并交给 Nginx

```bash
cd /opt/docsync/frontend
sudo -u docsync -H npm ci
sudo -u docsync -H npm run build
sudo install -d -m 755 /var/www/docsync
sudo cp -a /opt/docsync/frontend/dist/. /var/www/docsync/
sudo chown -R root:root /var/www/docsync
sudo chmod -R u=rwX,go=rX /var/www/docsync
sudo cp /opt/docsync/deploy/linux/nginx.conf /etc/nginx/sites-available/docsync
sudo ln -s /etc/nginx/sites-available/docsync /etc/nginx/sites-enabled/docsync
sudo nginx -t
sudo systemctl enable --now nginx
sudo systemctl reload nginx
curl --fail http://127.0.0.1:8090/health
```

打开 `http://服务器IP:8090`。Nginx 托管静态页面，并代理 `/api/` 与 `/health` 到后端，保留实时日志所需的无缓冲设置。开放对应防火墙/安全组端口；正式公网部署通过域名和 TLS 配置 HTTPS。Vite 的 `npm run dev` 仅用于开发，不作为服务器常驻前端。

## MySQL 元数据库方案

需要独立元数据库或使用当前本地源码构建时，可使用另外的 Compose：

```bash
git clone https://github.com/xiaoer2021/docsync.git
cd docsync
docker run --rm -v "$PWD:/workspace" -w /workspace python:3.11-slim python scripts/init_config.py --mode docker
docker compose -f docker-compose.mysql.yml up -d --build --wait --wait-timeout 300
docker compose -f docker-compose.mysql.yml exec api python -m app.cli setup
docker compose -f docker-compose.mysql.yml exec api python -m app.cli check
```

这里的 `.env`、MySQL 卷和 `./data` 与单文件 SQLite 方案不同。不要直接切换 Compose 期望自动迁移数据。SQLite 转 MySQL 的维护脚本为 `backend/scripts/migrate_sqlite_to_mysql.py`，目标须先迁移且业务表为空，并使用一致性源快照。

## 备份与升级

单文件 Docker：备份 `docsync_docsync-data` 卷，必须包含 `runtime.env`、SQLite 数据库、浏览器档案。为获得一致性快照，停止 API 后由宿主机备份卷，或使用 SQLite 在线备份接口。不要在写入中直接拷贝数据库文件。

完成备份后，默认 `main` 方案更新镜像：

```bash
docker compose up -d --build --wait --wait-timeout 300
docker compose exec api python -m app.cli check
```

若使用固定 `DOCSYNC_REF`，更新时显式指定新的提交 SHA。重建不改变已保存密钥或管理员口令；只重启容器不会获取新代码。禁止 `docker compose down -v`，它会删除数据卷。

手动方案：停服务后备份 `/opt/docsync/.env` 和 `backend/data/`，再更新源码、依赖和前端：

```bash
sudo systemctl stop docsync
cd /opt/docsync
sudo -u docsync git pull --ff-only
sudo -u docsync backend/.venv/bin/python -m pip install -r backend/requirements.txt
cd /opt/docsync/backend
sudo -u docsync .venv/bin/python -m app.cli initdb
cd /opt/docsync/frontend
sudo -u docsync -H npm ci
sudo -u docsync -H npm run build
sudo cp -a dist/. /var/www/docsync/
sudo chown -R root:root /var/www/docsync
sudo chmod -R u=rwX,go=rX /var/www/docsync
sudo systemctl start docsync
curl --fail http://127.0.0.1:8090/health
```

不要重新生成主密钥。回退时配套恢复旧代码及升级前元数据库。

## 开发附录

Linux/macOS 开发可在 `backend/` 建虚拟环境、执行 `setup` 后运行 `uvicorn app.main:app --reload`，在 `frontend/` 运行 `npm ci` 和 `npm run dev`。开发前端默认 5273，代理后端 8000。

Windows 开发从拉取项目开始：

```powershell
git clone https://github.com/xiaoer2021/docsync.git
cd docsync
py -3.11 scripts/init_config.py --mode manual
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m app.cli setup
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

另开终端进入 `docsync/frontend`，运行 `npm ci`、`npm run dev`。`start.bat` / `stop.bat` 用于已完成初始化的 Windows 本地开发。

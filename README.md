# 📦 校驿 · Campus Delivery Desk

> 面向小型校园代取与配送团队的轻量、自托管运营系统。

[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-5.2_LTS-092E20?logo=django&logoColor=white)](https://www.djangoproject.com/)
[![SQLite](https://img.shields.io/badge/SQLite-WAL-003B57?logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![HTMX](https://img.shields.io/badge/HTMX-2.x-3366CC?logo=htmx&logoColor=white)](https://htmx.org/)
[![Bootstrap](https://img.shields.io/badge/Bootstrap-5.3-7952B3?logo=bootstrap&logoColor=white)](https://getbootstrap.com/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)
[![Caddy](https://img.shields.io/badge/Caddy-Reverse_Proxy-1F88C0?logo=caddy&logoColor=white)](https://caddyserver.com/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

校驿服务于约 3～5 人的校园配送团队：客户通过微信联系，录单员统一录入，配送员在手机端接单、取件、拍照和完成配送，管理员负责人员、价格、结算、经营分析与备份恢复。客户无需注册或登录。

## ✨ 核心能力

- 覆盖快递、校门口外卖、周四 KFC、果蔬零食、跑腿和行李上楼六类业务。
- 普通客户与代理批次两套收件体系，支持临时收件人、归拢和代理凭证。
- 路线抢单、批量接单、实物交接转单、近景/远景照片和图片标注。
- 基于费用项的可审计计价，支持结算冻结、退款、撤销、收益归属和工资计算。
- 多维 Dashboard、全局搜索和 Excel 导出；10 万级本机代表查询已完成基准验证。
- 单账号单活跃会话、角色权限、幂等提交、Append-only 审计和维护模式。
- 每日自动备份、恢复前保护备份、媒体保留期清理和启动恢复检查。
- 响应式 Web + PWA；Windows 管理端和 Android 配送端共用一套系统。

## 👥 用户角色

| 角色 | 主要工作 |
|---|---|
| 管理员 | 人员、配置、经营分析、工资、备份恢复和维护 |
| 录单员 | 客户/代理管理、录单、异常、费用调整和结算 |
| 配送员 | 接单、取件、配送、转单、归拢和个人统计 |

## 🧱 系统架构

```mermaid
flowchart LR
    U[Windows / Android<br/>Browser · PWA] -->|HTTPS| C[Caddy]
    C --> W[Gunicorn · Django]
    W --> D[(SQLite WAL)]
    W --> M[Local Media]
    S[Independent Scheduler] --> W
    S --> B[Backup · Cleanup · Recovery]
    G[Optional external HTTPS gateway] -. reverse proxy / tunnel .-> C
```

| 层次 | 技术 |
|---|---|
| 后端 | Python 3.12、Django 5.2 LTS、Gunicorn |
| 页面 | Django Templates、HTMX、Alpine.js、Bootstrap 5.3、Chart.js |
| 数据 | SQLite WAL、本地文件、Pillow、openpyxl |
| 运维 | APScheduler 独立进程、Docker Compose、Caddy |

V1 是模块化 Django 单体，不依赖 Redis、Celery、PostgreSQL、微服务或原生客户端。权威业务规格位于 [`docs/spec/`](docs/spec/README.md)。

## 🚀 本地开发（Windows）

### 1. 环境要求

- Windows 10/11
- Python 3.12+
- Git

### 2. 安装

在 PowerShell 中进入项目根目录：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements/dev.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
New-Item -ItemType Directory -Force data/db,data/media,data/backups,data/tmp,data/logs
```

`requirements/dev.lock` 固定测试过的开发依赖；`pyproject.toml` 保存项目允许的版本范围。

### 3. 初始化数据库

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py seed_initial_config
.\.venv\Scripts\python.exe manage.py create_app_admin
```

`create_app_admin` 会交互式创建第一个管理员。系统不会预置默认账号或密码。

### 4. 启动

```powershell
.\run-dev.bat
```

浏览器打开 <http://127.0.0.1:8000/>。以后可用 `run-dev.bat --check` 只检查开发环境。

### 5. 可选 Demo 数据

```powershell
.\.venv\Scripts\python.exe manage.py seed_demo
```

Demo seed 只允许在 DEBUG 开发环境运行，具有幂等保护，且不会进入生产初始化流程。不要在 Demo 环境录入真实客户资料。

## 🐳 Docker Compose 部署

生产部署同时支持 Windows 和 Linux，应用容器及业务行为一致；差异只在 Docker 的安装方式和宿主机命令。

### 1. 环境要求

| 平台 | 必备工具 | 说明 |
|---|---|---|
| Windows 10/11 x64 | Docker Desktop、WSL2、Docker Compose v2 | 启动前确认 Docker Desktop 正在运行 |
| Linux x86_64 / arm64 | Docker Engine、Docker Compose plugin v2 | 当前用户需有执行 `docker` 的权限 |

两种平台都建议安装 Git 以便克隆和更新代码。正式公网部署还需要稳定域名、正确的 DNS 解析，并允许宿主机的 `80/443` 端口入站。宿主机不需要另外安装 Python、Django、SQLite 或 Caddy。

Compose 启动三个职责独立的服务：

- `web`：Gunicorn + Django；
- `scheduler`：备份、媒体清理、租约和临时文件任务；
- `caddy`：静态文件、反向代理和 HTTPS 入口。

### 2. 获取代码并准备配置

Windows PowerShell：

```powershell
git clone https://github.com/tuanliubuxi/campus-delivery-desk.git
Set-Location campus-delivery-desk
Copy-Item .env.example .env
$bytes = New-Object byte[] 48
[Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
[Convert]::ToBase64String($bytes)
```

Linux：

```bash
git clone https://github.com/tuanliubuxi/campus-delivery-desk.git
cd campus-delivery-desk
cp .env.example .env
head -c 48 /dev/urandom | base64
```

将生成结果填入 `.env` 的 `DJANGO_SECRET_KEY`，不要提交 `.env`。随后根据网络入口填写：

| 变量 | Caddy 直连固定域名 | 外部 HTTPS 网关转发到本机 80 |
|---|---|---|
| `DJANGO_ALLOWED_HOSTS` | `delivery.example.com,localhost` | `public.example.com,localhost` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://delivery.example.com` | `https://public.example.com` |
| `APP_BASE_URL` | `https://delivery.example.com` | `https://public.example.com` |
| `APP_DOMAIN` | `delivery.example.com` | `:80` |
| `PUBLIC_SCHEME` | `https` | `https` |

直连固定域名由 Caddy 自动申请和续期证书。若 HTTPS 已由云负载均衡、反向代理或内网穿透服务终止，应让 Caddy 监听本机 `80`，并保持 `PUBLIC_SCHEME=https`。不要把只能由外部网关访问的临时域名交给本机 Caddy 申请证书。

### 3. 首次初始化

以下命令在 Windows PowerShell 和 Linux shell 中相同：

```bash
docker compose config --quiet
docker compose build
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py seed_initial_config
docker compose run --rm web python manage.py create_app_admin
docker compose up -d
docker compose ps
```

Windows 可使用 `run-prod.bat` 完成同一流程；`run-prod.bat --check` 只检查 Docker、`.env` 和 Compose 配置。Linux 日常启动使用：

```bash
docker compose up -d
docker compose ps
```

### 4. 网络入口注意事项

- 正式环境必须通过 HTTPS 访问；不要关闭安全 Cookie 或 CSRF 校验来适配纯 HTTP。
- 若域名发生变化，同步修改 `DJANGO_ALLOWED_HOSTS`、`DJANGO_CSRF_TRUSTED_ORIGINS` 和 `APP_BASE_URL`，然后运行 `docker compose up -d --force-recreate`。
- 域名变化会形成新的 PWA Origin，旧域名中的安装入口和浏览器本地草稿不会自动迁移。
- 外部反向代理或穿透工具只是网络入口，不是项目依赖；可按部署环境自行选择。

## 📦 私有备份与离线部署包

根目录的发布脚本会在 Git 忽略的 `tags/` 中生成同一版本名的三类私有产物。默认版本名来自 `pyproject.toml`，并附加构建日期，例如 `campus-delivery-desk-v0.1.0-20261001`。

| 产物后缀 | 内容 | 用途 |
|---|---|---|
| `-project-private.zip` / `.tar.gz` | 源码、`.git`、`.env`、`data/` 和本地文档 | 完整私有恢复与迁移 |
| `-venv-windows-amd64.zip` / `-venv-linux-amd64.tar.gz` | 当前开发虚拟环境 | 同系统环境的辅助恢复，不用于生产部署 |
| `-docker-linux-amd64.tar` | 应用镜像与 Caddy 镜像 | 目标机离线导入，不再下载 Python 或镜像依赖 |
| `-manifest.txt` | Git commit、平台和 SHA-256 | 核对版本与文件完整性 |

构建前应提交所有受 Git 跟踪的修改、停止 Compose 服务，并确认 `.env` 和数据库状态正确。Windows：

```powershell
.\build-release.bat amd64
```

Linux：

```bash
chmod +x build-release.sh run-offline.sh
./build-release.sh amd64
```

`amd64` 可替换为 `arm64`；Docker 镜像必须与目标主机 CPU 架构一致。`.venv` 可能包含宿主机路径及平台相关二进制，因此必须单独保存，不能替代 Docker 离线包。

在目标机安装好 Docker 后，解压私有项目包并进入项目目录，将 Docker tar 路径传给启动脚本：

```powershell
.\run-offline.bat "..\campus-delivery-desk-v0.1.0-20261001-docker-linux-amd64.tar"
```

```bash
chmod +x run-offline.sh
./run-offline.sh ../campus-delivery-desk-v0.1.0-20261001-docker-linux-amd64.tar
```

脚本会执行 `docker load`、迁移、幂等初始化、必要时创建首个管理员，然后以 `--no-build --pull never` 启动服务。目标机仍须预先安装 Docker；固定域名首次签发公开 HTTPS 证书也需要网络。私有项目包包含密钥和业务数据，当前格式未加密，只能通过可信介质传输并妥善保管，禁止上传到公开仓库或公共网盘。

## 🗂️ 数据与运维

所有运行数据均位于 `data/`，不会写入 Docker 镜像：

```text
data/
├─ db/        # SQLite 数据库
├─ media/     # 配送照片和生成凭证
├─ backups/   # 应用内备份
├─ tmp/       # 原子上传和临时文件
└─ logs/      # 预留日志目录
```

- `/health/live`：进程存活检查。
- `/health/ready`：数据库和数据目录可用检查。
- scheduler 每日 03:00 自动备份，并按配置清理过期媒体和临时文件。
- 管理员可在 Web 中创建、下载、恢复和删除备份；恢复前自动创建 PRE_RESTORE 保护点。
- 更新流程：进入维护模式 → 创建保护备份 → build/pull → migrate → restart → Recovery Check → 核对后退出维护。

数据库、媒体、备份、`.env`、日志和真实客户资料都不会被 Git 跟踪。详细恢复规则见 [`docs/spec/08_OPERATIONS_BACKUP_RECOVERY.md`](docs/spec/08_OPERATIONS_BACKUP_RECOVERY.md)。

## 🧪 质量检查

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
git diff --check
```

当前自动回归共 112 项。10 万级性能基准、依赖锁和恢复演练见 [`docs/V1_HARDENING_REPORT.md`](docs/V1_HARDENING_REPORT.md)；真实 Android/Windows 验收见 [`docs/MANUAL_ACCEPTANCE.md`](docs/MANUAL_ACCEPTANCE.md)。

## 📁 项目结构

```text
apps/           Django 领域模块、services、selectors 与测试
config/         URL、ASGI/WSGI、开发/生产设置
templates/      响应式页面与 HTMX partials
static/         CSS、JavaScript、PWA 与前端依赖
requirements/   生产/开发精确依赖锁
docs/spec/      V1 权威需求规格
data/           本地运行数据（Git 忽略）
```

## 📄 License

本项目采用 [MIT License](LICENSE)。

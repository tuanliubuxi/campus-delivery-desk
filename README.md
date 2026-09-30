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
    T[cpolar optional] -. HTTPS tunnel .-> C
```

| 层次 | 技术 |
|---|---|
| 后端 | Python 3.12、Django 5.2 LTS、Gunicorn |
| 页面 | Django Templates、HTMX、Alpine.js、Bootstrap 5.3、Chart.js |
| 数据 | SQLite WAL、本地文件、Pillow、openpyxl |
| 运维 | APScheduler 独立进程、Docker Compose、Caddy、cpolar（可选） |

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

Compose 启动三个职责独立的服务：

- `web`：Gunicorn + Django；
- `scheduler`：备份、媒体清理、租约和临时文件任务；
- `caddy`：静态文件、反向代理和 HTTPS 入口。

### 1. 准备配置

```powershell
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

将生成结果填入 `.env` 的 `DJANGO_SECRET_KEY`，不要把 `.env` 提交到 Git。随后按部署方式填写：

| 变量 | 直连固定域名示例 | cpolar 临时域名示例 |
|---|---|---|
| `DJANGO_ALLOWED_HOSTS` | `delivery.example.com,localhost` | `xxxx.cpolar.top,localhost` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://delivery.example.com` | `https://xxxx.cpolar.top` |
| `APP_BASE_URL` | `https://delivery.example.com` | `https://xxxx.cpolar.top` |
| `APP_DOMAIN` | `delivery.example.com` | `:80` |
| `PUBLIC_SCHEME` | `https` | `https` |

直连固定域名由 Caddy 自动申请和续期证书。cpolar 模式由 cpolar 提供公网 HTTPS，并将 HTTP 隧道指向本机 `80` 端口；不要把临时 cpolar 域名直接写成 Caddy 的证书域名。

### 2. 首次初始化

确保 Docker Desktop 已启动：

```powershell
docker compose config --quiet
docker compose build
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py seed_initial_config
docker compose run --rm web python manage.py create_app_admin
docker compose up -d
docker compose ps
```

日常启动也可使用 `run-prod.bat`；`run-prod.bat --check` 只检查 Docker、`.env` 和 Compose 配置。

### 3. cpolar

在 cpolar 中创建 HTTP 隧道并转发到本机 `80` 端口，然后使用在线隧道列表给出的 HTTPS 地址访问。临时域名变化后，需要同步更新上表前三项并重新启动 Compose：

```powershell
docker compose up -d --force-recreate
```

域名变化会形成新的 PWA Origin，旧域名中的安装入口和浏览器本地草稿不会自动迁移。长期使用建议购买或保留固定域名。

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

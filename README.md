# 校驿 · Campus Delivery Desk

面向小型校园代取/配送团队的自托管运营系统。Phase 0 工程骨架已建立；业务功能将按 [V1 实施计划](docs/spec/11_IMPLEMENTATION_PLAN.md) 逐阶段实现。V1 权威规格见 [docs/spec/README.md](docs/spec/README.md)。

## 技术栈

Python 3.12+、Django 5.2 LTS、Templates + HTMX + Alpine.js + Bootstrap、SQLite WAL、本地文件存储、独立 APScheduler 进程、Gunicorn + Caddy + Docker Compose。V1 不使用未来专业版方案。

## 本地开发（PowerShell）

    python -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -e '.[dev]'
    New-Item -ItemType Directory -Force data/db,data/media,data/backups,data/tmp,data/logs
    .\.venv\Scripts\python.exe manage.py migrate
    .\.venv\Scripts\python.exe manage.py runserver

打开 http://127.0.0.1:8000/。Phase 0 仅提供占位首页及健康检查；正式登录和业务页面尚未开发。开发环境可使用内置的非生产密钥；部署必须设置独立的 DJANGO_SECRET_KEY。

    .\.venv\Scripts\python.exe -m pytest -q
    .\.venv\Scripts\ruff.exe check .
    .\.venv\Scripts\python.exe manage.py check

健康接口 /health/live 只检查进程响应；/health/ready 检查 SQLite 文件可取得写锁且数据目录可写。SQLite 数据库默认在 data/db/app.sqlite3，迁移后自动启用 WAL。data/、本地环境文件和历史规格归档不会进入 Git。

## Docker Compose

安装 Docker Engine/Desktop 与 Compose 插件后：

1. 将 .env.example 复制为 .env，替换密钥、域名、HTTPS 地址。不要提交 .env。
2. 配置 APP_DOMAIN 与 DJANGO_ALLOWED_HOSTS；若通过 cpolar 使用固定 HTTPS 域名，二者使用对应域名。
3. 构建并迁移，然后启动：

    docker compose build
    docker compose run --rm web sh -c "mkdir -p /data/db && python manage.py migrate"
    docker compose up -d

Compose 包含 web、独立 scheduler 和 caddy。共享的 ./data 保存数据库与媒体；收集后的静态资源存放在 Web/Caddy 共享 volume。Caddy 只公开静态资源，不匿名公开 media。当前 scheduler 仅启动进程骨架，定时业务任务属于 Phase 10。Phase 1 才会提供应用管理员创建与初始化配置命令，Phase 0 不会提前实现。

## 环境与安全

部署变量样例见 [.env.example](.env.example) 和 [部署规格](docs/spec/17_DEPLOYMENT_ENVIRONMENT.md)。生产 settings 强制要求 DJANGO_SECRET_KEY，启用安全 Cookie 与 HTTPS 重定向。切勿把真实客户资料、图片、数据库、日志或备份提交到仓库。

## 进度

当前状态见 [实施进度](docs/IMPLEMENTATION_PROGRESS.md)。本项目遵循各阶段先测试、审查 diff、更新文档，再提交并推送的流程。

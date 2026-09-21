# 校驿 · Campus Delivery Desk

面向小型校园代取/配送团队的自托管运营系统。工程骨架以及账号、客户、基础配置功能已经建立；后续业务功能按 [V1 实施计划](docs/spec/11_IMPLEMENTATION_PLAN.md) 逐阶段实现。V1 权威规格见 [docs/spec/README.md](docs/spec/README.md)。

## 技术栈

Python 3.12+、Django 5.2 LTS、Templates + HTMX + Alpine.js + Bootstrap、SQLite WAL、本地文件存储、独立 APScheduler 进程、Gunicorn + Caddy + Docker Compose。V1 不使用未来专业版方案。

## 本地开发（PowerShell）

    python -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -e '.[dev]'
    New-Item -ItemType Directory -Force data/db,data/media,data/backups,data/tmp,data/logs
    .\.venv\Scripts\python.exe manage.py migrate
    .\.venv\Scripts\python.exe manage.py runserver

首次迁移后创建管理员账号：

    .\.venv\Scripts\python.exe manage.py createsuperuser

打开 http://127.0.0.1:8000/，从登录页角落进入管理员入口。`createsuperuser` 创建的账号自动使用 ADMIN 角色；其余管理员、录单员和配送员账号在“人员与会话”页面创建。开发环境可使用内置的非生产密钥；部署必须设置独立的 DJANGO_SECRET_KEY。

    .\.venv\Scripts\python.exe -m pytest -q
    .\.venv\Scripts\ruff.exe check .
    .\.venv\Scripts\python.exe manage.py check

健康接口 /health/live 只检查进程响应；/health/ready 检查 SQLite 文件可取得写锁且数据目录可写。SQLite 数据库默认在 data/db/app.sqlite3，迁移后自动启用 WAL。data/、本地环境文件和历史规格归档不会进入 Git。

## Windows 快捷脚本

- `run-dev.bat`：检查虚拟环境、创建本地数据目录、执行迁移并启动 Django 开发服务器；运行地址为 `http://127.0.0.1:8000/`。
- `run-prod.bat`：校验 Docker 与 `.env`，构建镜像、执行容器内迁移，然后启动 Web、scheduler 和 Caddy。生产模式使用 `docker-compose.yml` 中的 80/443 端口。
- 两个脚本都支持 `--check`，只检查环境而不启动长期服务：`run-dev.bat --check`、`run-prod.bat --check`。

脚本遇到缺少虚拟环境、Docker 未启动、Compose 配置错误或示例生产密钥时会立即停止，不会绕过安全校验。

## Docker Compose

安装 Docker Engine/Desktop 与 Compose 插件后：

1. 将 .env.example 复制为 .env，替换密钥、域名、HTTPS 地址。不要提交 .env。
2. 配置 APP_DOMAIN 与 DJANGO_ALLOWED_HOSTS；若通过 cpolar 使用固定 HTTPS 域名，二者使用对应域名。
3. 构建并迁移，然后启动：

    docker compose build
    docker compose run --rm web sh -c "mkdir -p /data/db && python manage.py migrate"
    docker compose up -d

Compose 包含 web、独立 scheduler 和 caddy。共享的 ./data 保存数据库与媒体；收集后的静态资源存放在 Web/Caddy 共享 volume。Caddy 只公开静态资源，不匿名公开 media。当前 scheduler 仅启动进程骨架，定时业务任务属于 Phase 10。迁移会初始化固定六种业务、1～18 号楼、默认价格/KFC 开放日等 V1 配置；管理员账号仍通过 `createsuperuser` 显式创建，不内置默认口令。

### Docker Desktop 国内镜像

国内网络可在 `%USERPROFILE%\.docker\daemon.json` 保留原配置并加入：

```json
"registry-mirrors": [
  "https://docker.m.daocloud.io"
]
```

保存后重启 Docker Desktop，通过 `docker info` 确认 Registry Mirrors，再用普通的 `docker pull` 命令验证。镜像加速服务属于第三方下载链路；如服务策略或可用性变化，应移除该项并回退 Docker Hub 或改用团队自建镜像仓库。

## 环境与安全

部署变量样例见 [.env.example](.env.example) 和 [部署规格](docs/spec/17_DEPLOYMENT_ENVIRONMENT.md)。生产 settings 强制要求 DJANGO_SECRET_KEY，启用安全 Cookie 与 HTTPS 重定向。切勿把真实客户资料、图片、数据库、日志或备份提交到仓库。

## 进度

当前状态见 [实施进度](docs/IMPLEMENTATION_PROGRESS.md)。本项目遵循各阶段先测试、审查 diff、更新文档，再提交并推送的流程。

# 校驿 · Campus Delivery Desk

校驿是面向 3～5 人校园代取/配送团队的自托管运营系统，覆盖录单、接单、取件、配送证据、归拢、代理批次、结算、收益工资、经营分析与本地备份恢复。客户不登录系统，团队通过响应式 Web/PWA 在 Windows 与 Android 浏览器中协作。

V1 权威需求位于 [`docs/spec/`](docs/spec/README.md)，采用 Django 单体、Templates、HTMX、Alpine.js、SQLite WAL、本地文件、独立 APScheduler、Gunicorn、Caddy 与 Docker Compose。V1 不使用 Redis、Celery、PostgreSQL、微服务或原生客户端。

## 本地开发

要求 Python 3.12+。PowerShell 命令：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
New-Item -ItemType Directory -Force data/db,data/media,data/backups,data/tmp,data/logs
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py seed_initial_config
.\.venv\Scripts\python.exe manage.py create_app_admin
.\.venv\Scripts\python.exe manage.py runserver
```

打开 <http://127.0.0.1:8000/>。管理员从登录页角落进入独立入口；其余管理员、录单员和配送员账号可在“人员”页面创建。

也可以运行 `run-dev.bat`；`run-dev.bat --check` 只检查环境，不启动长期服务。

### Demo 数据

Demo seed 只允许在 `DEBUG=true` 的开发环境运行，不参与迁移、生产初始化或容器启动：

```powershell
.\.venv\Scripts\python.exe manage.py seed_demo
```

命令只创建名称带“演示”的合成账号、客户和订单，首次运行会输出随机 Demo 口令，重复执行不会重置口令或重复创建订单。不要在 Demo 环境输入真实客户资料。

## Docker Compose 部署

1. 将 `.env.example` 复制为 `.env`。
2. 替换 `DJANGO_SECRET_KEY`、域名、允许主机和 HTTPS Origin；不要提交 `.env`。
3. 初始化并启动：

```powershell
docker compose build
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py seed_initial_config
docker compose run --rm web python manage.py create_app_admin
docker compose up -d
```

Compose 包含 `web`、独立 `scheduler` 与 `caddy`。`./data` 保存 SQLite、媒体、备份、临时文件和日志，升级镜像不会覆盖该目录。Caddy 只公开静态资源；业务媒体必须通过带权限的下载端点访问。

生产更新流程：进入维护模式 → 创建保护备份 → build/pull → migrate → restart → Recovery Check → 人工核对后退出维护模式。

## PWA 与弱网边界

- 在 HTTPS 或本地开发 Origin 打开系统，可使用浏览器“安装应用”添加到 Android/Windows 桌面。
- 系统不会离线执行录单、配送或结算；断网时会明确阻止用户期待离线提交。
- 关键文本表单保存在当前浏览器的 `localStorage`，可手工清除。
- 图片表单通过页面内提交保留 `File` 引用；网络或校验失败后可在同一页面重试。
- 核心录单、接单、完成、转单、结算、异常和备份操作使用稳定幂等键或状态机重复检测。

更换域名会改变 PWA Origin，也会隔离原 Origin 的本地草稿；正式部署应使用稳定 HTTPS 域名。

## 运维

- `/health/live`：进程存活。
- `/health/ready`：SQLite 与数据目录可写。
- scheduler 每日 03:00 备份，每月清理超过保留期的媒体，并定时清理 stale lease/临时文件。
- 管理员可在 Web 中管理备份、恢复、媒体和维护模式；Web 不具备宿主机关机或 Docker 控制权限。

数据目录、`.env`、真实客户资料、媒体、数据库、日志与备份均不应进入 Git。恢复流程和保留策略详见 [`docs/spec/08_OPERATIONS_BACKUP_RECOVERY.md`](docs/spec/08_OPERATIONS_BACKUP_RECOVERY.md)。

## 质量检查

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
git diff --check
```

阶段进度见 [`docs/IMPLEMENTATION_PROGRESS.md`](docs/IMPLEMENTATION_PROGRESS.md)，尚待需求确认的事项见 [`docs/IMPLEMENTATION_QUESTIONS.md`](docs/IMPLEMENTATION_QUESTIONS.md)。

## License

[MIT](LICENSE)

# 17. 部署与环境变量规范

## 1. Docker Compose

V1 建议：

```text
web
scheduler
caddy
```

无 Redis、Postgres、Celery。

web 示例：

```bash
gunicorn config.wsgi:application --workers 2 --threads 4 --timeout 60 --bind 0.0.0.0:8000
```

scheduler：

```bash
python manage.py run_scheduler
```

## 2. Volume

```text
/data/db
/data/media
/data/backups
/data/tmp
/data/logs
```

容器升级不得覆盖 `/data`。

## 3. 环境变量

```text
DJANGO_SECRET_KEY=change-me
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=delivery.example.com,localhost
DJANGO_CSRF_TRUSTED_ORIGINS=https://delivery.example.com
SYSTEM_TIMEZONE=Asia/Shanghai
APP_BASE_URL=https://delivery.example.com

DATA_ROOT=/data
DB_PATH=/data/db/app.sqlite3
MEDIA_ROOT=/data/media
BACKUP_ROOT=/data/backups
TMP_ROOT=/data/tmp
LOG_ROOT=/data/logs

SESSION_COOKIE_SECURE=true
```

价格、加急、天气、费率、主题等属于数据库配置中心，不同时维护环境变量副本。

## 4. 初始化

```bash
docker compose build
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py create_app_admin
docker compose run --rm web python manage.py seed_initial_config
docker compose up -d
```

`seed_initial_config` 必须幂等，不覆盖管理员后续配置。

## 5. Demo

仅开发/演示：`python manage.py seed_demo`。生产不自动 seed。

## 6. 静态/PWA

同 HTTPS origin 提供 static、manifest、service worker。管理员/录单员宽窄屏自适应；配送员模板固定移动卡片体验。

## 7. Media 安全

不要匿名暴露整个 media 根目录。使用受控 endpoint/FileResponse；内部 storage_key 随机不可猜。

## 8. Scheduler 推荐任务

- 每天 03:00：backup；
- 每月固定日期/凌晨：media_cleanup（删除 >30d）；
- 每 1～5 分钟：stale login lease / tmp cleanup（也可在访问时惰性清理）。

不存在 22:00 快递收工任务。

## 9. 健康检查

```text
GET /health/live
GET /health/ready
```

ready 检查 DB 可读写和 data 目录。

## 10. 更新

1. 进入维护模式；
2. 自动/手工保护备份；
3. build/pull；
4. migrate；
5. restart；
6. Recovery Check；
7. 管理员确认后退出维护。

## 11. cpolar

Django 只假设稳定 HTTPS Base URL，不把 cpolar 账号/隧道逻辑写进业务模型。建议固定域名/固定隧道，避免 PWA 地址变化。

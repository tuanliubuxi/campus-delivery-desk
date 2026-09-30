# V1 发布加固记录

本记录补充 V1 自动化收尾结果，不替代 `docs/spec/` 权威需求，也不替代真实设备和目标主机验收。

## 1. cpolar 与 HTTPS 边界

V1 当前使用 cpolar 临时域名。应用只接收一个 HTTPS Base URL，不保存 cpolar 账号、Token 或隧道控制逻辑。

- 每次临时域名变化时，同步更新 `.env` 中的 `DJANGO_ALLOWED_HOSTS`、`DJANGO_CSRF_TRUSTED_ORIGINS`、`APP_BASE_URL` 和 `APP_DOMAIN`。
- 保持安全 Cookie、CSRF、代理 HTTPS 识别和当前域名 HSTS。
- 不启用 `SECURE_HSTS_INCLUDE_SUBDOMAINS` 或 `SECURE_HSTS_PRELOAD`；Django 对这两项的部署检查提示在临时域名阶段属于已接受提示。
- 域名变化会形成新的 PWA Origin，旧 Origin 的安装入口和 localStorage 草稿不会自动迁移。

## 2. 密钥与依赖

- 2026-10-01 已轮换本地忽略文件 `.env` 的 `DJANGO_SECRET_KEY`，使用 48 字节密码学随机源生成 64 字符 URL-safe 值；值未写入日志、文档或 Git。
- `requirements/prod.lock` 固定生产直接及传递依赖；`requirements/dev.lock` 在其上固定测试和静态检查工具。
- `pyproject.toml` 继续作为允许升级范围；lock 作为已回归的精确安装集合。
- Docker 先安装 `requirements/prod.lock`，再以 `--no-deps` 安装本项目，避免镜像构建时重新漂移依赖。

## 3. 10 万级本机容量基准

### 数据与环境

- 日期：2026-10-01
- Python 3.12.5、Django 5.2.17、SQLite 3.45.3
- Windows 11 本地开发机，独立 SQLite 临时数据库
- Customer 20,000、Agent 1,000、Order 79,000，三类合计 100,000
- 另有 ExpressRound 20,000、ExpressOrderDetail 79,000
- 数据库约 70.4 MB；每项读取预热后执行 3 次并记录中位数

### 最终结果

| 代表路径 | 中位数 |
|---|---:|
| 客户列表 50 条 | 22.07 ms |
| 客户文本搜索 | 10.01 ms |
| 代理列表 50 条 | 0.92 ms |
| 代理文本搜索 | 1.43 ms |
| 订单列表 50 条 | 230.41 ms |
| 固定订单号精确搜索 | 2.85 ms |
| 取件标识搜索 | 132.42 ms |
| Dashboard 明细 50 条 | 237.53 ms |
| Dashboard cards | 55.43 ms |

首次测量发现 Dashboard 明细约 580 ms、cards 约 444 ms。原因是默认无筛选查询仍对全部订单附加三个相关 `EXISTS` 子查询，并无条件执行 `DISTINCT`。修正为仅在异常/天气/退款筛选启用时附加相应子查询、仅在多值关联可能产生重复时去重后，结果降至上表范围。

该结果证明当前开发机的代表性 selector 路径符合 `<500ms` 目标，但不等于 HTTP 端到端、3～10 并发用户或目标小主机验收。正式部署主机仍应重复运行。

### 可重复命令

`benchmark_v1_scale` 仅允许 DEBUG 设置，要求 `--confirm-disposable`，拒绝默认 `app.sqlite3`，并拒绝包含 Customer、Agent 或 Order 的数据库。应在新的 PowerShell 会话中让 `DATA_ROOT`/`DB_PATH` 指向独立临时目录后运行：

```powershell
$benchmarkRoot = Join-Path (Resolve-Path .) 'data\tmp\v1-scale'
New-Item -ItemType Directory -Force $benchmarkRoot | Out-Null
$env:DATA_ROOT = $benchmarkRoot
$env:DB_PATH = Join-Path $benchmarkRoot 'benchmark.sqlite3'
.\.venv\Scripts\python.exe manage.py migrate --noinput
.\.venv\Scripts\python.exe manage.py seed_initial_config
.\.venv\Scripts\python.exe manage.py benchmark_v1_scale --confirm-disposable
```

默认规模即 20,000 Customer + 1,000 Agent + 79,000 Order。不得对开发主库或生产库运行。

## 4. 备份恢复演练

2026-10-01 在另一套独立临时数据库完成以下真实服务链路：

1. 创建管理员与标记数据；
2. 创建 MANUAL 备份；
3. 修改备份后的标记值；
4. 进入维护模式；
5. 执行恢复；
6. 自动创建 PRE_RESTORE 保护备份；
7. 校验恢复值回到备份时状态；
8. 校验 Restore JobRun 为 `SUCCEEDED`；
9. 校验恢复后继续处于维护模式。

结果：恢复值正确，PRE_RESTORE 数量 1，可用备份数量 2，恢复任务成功，维护模式保持开启。演练目录随后清理；主开发数据库未参与。

目标服务器上线前仍应在维护窗口使用非生产演练数据重复一次，并记录文件系统容量、备份耗时和恢复耗时。

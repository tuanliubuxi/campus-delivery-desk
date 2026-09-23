# 实施进度

权威 TODO 与验收范围见 [V1 实施计划](spec/11_IMPLEMENTATION_PLAN.md)。本文件记录各阶段进展，不替代需求规格。

## Phase 0：工程骨架（已完成）

- [x] Django 工程、dev/prod settings
- [x] Dockerfile / Compose / Caddy
- [x] SQLite WAL
- [x] pytest / pytest-django / Ruff
- [x] health endpoints
- [x] HTMX / Alpine / Bootstrap
- [x] PWA manifest/service worker 基础
- [x] 四套主题 CSS Variables
- [x] README 安装说明
- [x] 当前阶段测试、diff 审查、提交与推送

本地验证：Python 3.12.5；Django 5.2.17；初始自定义 User 迁移成功；SQLite journal_mode=wal；Django dev/prod check、collectstatic、健康接口及 5 项 pytest 测试通过。Docker Compose 已完成镜像构建、迁移和三服务启动验证；经 Caddy 访问 `/health/live`、`/health/ready` 均返回 200，HTTP 自动跳转 HTTPS，scheduler 正常常驻。因本机 Windows 保留 80 端口，容器验收临时使用宿主机 8080/8443 映射，正式 Compose 配置仍保持 80/443。

## Phase 1：账号、会话、客户、配置（已完成）

- [x] Custom User + ADMIN / RECORDER / COURIER 三角色
- [x] 角色与人员下拉登录、独立管理员入口
- [x] ActiveLoginLease、30 秒心跳、150 秒 stale 判定
- [x] fresh lease 拒绝、stale lease 替换、旧 Session 失效
- [x] 管理员强制下线、停用账号/重置口令同步失效会话
- [x] 配送员接单开关、当前业务类型、后端角色校验
- [x] Customer CRUD、历史值快照 DTO、疑似重复提醒
- [x] 客户多名称/手机尾号 `/` token 搜索
- [x] Building / Zone / 路线顺序及 1～18 号楼默认数据
- [x] 固定六业务、价格、加急、快递附加费、上楼费率、天气、多件优惠配置
- [x] 配送员按业务/收益来源分成配置、四主题默认值与用户覆盖
- [x] KFC 默认开放日（ISO 星期四）与租约/媒体保留配置
- [x] 关键写操作显式 service、后端权限校验与 AuditEvent
- [x] 页面、迁移、测试、Docker Compose 回归、diff 审查、提交与推送

本地验证：24 项 pytest 测试通过；Ruff、Django check、migration drift check 通过。Docker Compose 完成新镜像构建和容器内迁移；Web healthy，HTTPS `/health/ready` 与 `/login/` 均返回 200，初始化数据核对为 6 种业务、18 栋楼、KFC 开放日为星期四。默认配送员分成比例未在规格中给出，未自行猜测，配置行以“未配置”初始化并记录在 `docs/IMPLEMENTATION_QUESTIONS.md`。

## Phase 2 前工程准备（已完成）

- [x] 本机 Docker Desktop 配置 DaoCloud 国内 registry mirror，保留原配置备份并完成实际拉取验证
- [x] 全部代码与可注释配置文件补充文件职责说明，并在账号租约、配置快照、SQLite WAL、容器边界等关键位置补充维护性注释（严格 JSON 配置保持标准格式）
- [x] 根目录新增 `run-dev.bat` 与 `run-prod.bat`，两者的 `--check` 模式均通过

## Phase 2：代理人体系（已完成）

- [x] Agent 长期档案、搜索、修改与停用（历史记录不删除）
- [x] ProxyBatch 基础模型、OPEN/READY_TO_SETTLE/SETTLED/CANCELED 状态字段与 OPEN 追加边界
- [x] ProxyRecipient 批次内临时资料，与 Customer 完全隔离
- [x] 代理来源业务类型守卫：仅 EXPRESS 可用
- [x] `{楼栋}号楼#{本批次序号}` 自动临时命名及批次内唯一约束
- [x] 代理批次工作台、新建批次、连续维护临时收件人响应式 UI
- [x] `show_price_on_receipt` 默认开启且可在 OPEN 批次内修改
- [x] 代理人/联系方式/批次/临时收件人搜索，创建与修改写入 AuditEvent
- [x] migration、专项/全量测试、Docker Compose 构建及运行态回归

本阶段新增 `agents.0001_initial`，建立 Agent、ProxyBatch、ProxyRecipient 及批次编号、临时名称数据库约束。全量 36 项 pytest 测试通过；Ruff、Django check、migration drift check 通过；生产镜像构建成功，容器内迁移无遗漏，Web healthy 且 `/health/ready` 返回 200，scheduler 正常常驻。按阶段依赖，涉及 Order/Assignment/ExpressRound 的 `cancel_proxy_batch()` 保留到 Phase 5，READY 自动判定、显式 reopen 与凭证失效保留到 Phase 6。

## Phase 3：订单、费用与结算基础模型（已完成）

- [x] Order 公共模型、独立 `requires_upstairs` 与六类强类型 Detail
- [x] 固定/动态订单编号、两种格式统一解析与订单历史搜索
- [x] 快递统一 pickup identifier 原值/规范化值、重复强提醒与明确确认继续
- [x] EXPRESS service_date 默认/必填、显式 ExpressRound 与同收件归属归轮
- [x] UNKNOWN 大小及创建时四档价格快照；已知大小立即生成基础费用
- [x] 校外取件、校内送校外、加急与上楼等初始费用拆项
- [x] 六类明确 creator/form、普通录单、客户连续录入和代理临时收件人连续录入
- [x] 楼栋/校外地址、条件地点、上楼地址、行李数量/禁加急等前后端校验
- [x] ChargeItem ACTIVE/VOIDED、禁止物理删除、定价/逻辑作废 service
- [x] Settlement、SettlementOrder、仅供 freeze 创建的不可变 SettlementLine 基础模型
- [x] append-only FinancialAdjustment 基础模型
- [x] CourierEarning 按来源拆行字段、确定性 earning_key、可空 settlement 与幂等基础 service
- [x] NEW 修改、NEW/ASSIGNED 未取取消、费用历史保留及 AuditEvent
- [x] 响应式录单选择/表单/历史/详情/取消页面与角色后端权限
- [x] migration、专项/全量测试、静态检查与 migration drift 检查

本阶段新增 `orders.0001_initial`，建立 Order、ExpressRound 和六类 Detail 及收件归属、轮次、编号、目的地等数据库约束；新增 `settlements.0001_initial`，建立 ChargeItem、Settlement、SettlementOrder、SettlementLine、FinancialAdjustment、CourierEarning 及费用作用域、作废元数据、受益归属和冻结行唯一约束。全量 49 项 pytest 测试通过；Ruff、Django check、migration drift check 与 `git diff --check` 通过。快递重复提醒的“时间窗口”长度未由规格给出，当前按同一 `service_date` 处理并记录于 `docs/IMPLEMENTATION_QUESTIONS.md`。按阶段边界，配送状态推进、UNKNOWN 大小确认、ExpressRound 关闭、代理批次整批取消、结算 build/freeze/confirm 均未提前实现。

## Phase 4：简单配送业务（已完成）

- [x] 五类简单业务（外卖、KFC、商超、跑腿、行李上楼）的独立 DeliveryTask 与业务类型守卫
- [x] 配送员任务池、接单、取到、开始配送、未取件退回及后端角色/归属校验
- [x] 每单至多一个有效 Assignment、原子抢单和重复 operation_id 幂等检测
- [x] DeliveryDrop、同客户/同业务/同目的地合并放置校验及每单唯一完成约束
- [x] `requires_upstairs` 地址完整性与实际放置类型校验
- [x] 近景/远景证据、远景标注派生图、原图关联与受控媒体下载
- [x] Pillow 方向修正、最长边 1600 像素、JPEG 压缩、元数据剥离和原子文件发布
- [x] 普通配送至少一张照片、行李上楼允许零照片
- [x] 配送完成幂等创建 PENDING_PAYMENT CourierEarning，settlement 保持为空
- [x] 转单申请/接受/拒绝，已取件或配送中强制记录实物交接地点
- [x] 基础 ExceptionCase、附件/证据关联、显式结算/归拢阻断字段及处理审计
- [x] 配送员移动端任务、完成、转单和异常页面及浏览器标注交互
- [x] migration、专项/全量测试、静态检查、Docker 生产镜像和一次性容器回归

本阶段新增 `dispatch.0001_initial`，建立 DeliveryTask、Assignment、TransferRequest/Item、DeliveryDrop/Item 及有效责任、完成唯一性和收件归属约束；新增 `mediafiles.0001_initial`，建立 MediaFile 与 DeliveryEvidence；新增 `exceptions.0001_initial`、`exceptions.0002_initial`，建立异常、附件和证据关联，其中拆分迁移用于安全解决跨 App 外键依赖。同步修复 ASSIGNED 订单取消时释放未取件责任、活动任务期间禁止切换业务类型。Phase 4 专项 12 项、全量 61 项 pytest 测试通过；Ruff、Django check、migration drift check、`git diff --check` 均通过。Docker 生产镜像构建成功，一次性容器内 Django check 与 migrate check 通过，未遗留运行容器。未实现快递 RouteBatch、ExpressRound 关闭、代理批次原子取消或归拢逻辑，下一 Phase 尚未开始。

## Phase 5：快递复杂配送（已完成）

- [x] 南区、北区、校外路线池及取件区域/目的区域筛选
- [x] 校外路线逐件展示具体取件地点，校内送校外突出详细地址
- [x] SQLite 条件更新、唯一约束、短重试与冲突回查实现动态批量接单和部分成功
- [x] 同一 Customer/ProxyRecipient 客户直送组批及加急优先展示
- [x] 快递逐件取件、任务级仅启动已取物件、楼栋/收件归属配送排序
- [x] UNKNOWN 大小在取到实物后确认，并按订单创建时四档价格快照生成基础费/上楼费
- [x] 已取实物转单强制交接地点，接收人确认后才切换 Assignment
- [x] 普通/代理快递 DeliveryDrop、最终配送员待付款收益归属及原图/标注证据复用
- [x] ExpressRound 全取消/有效送达 0 件和单件送达关闭；多件分支保持 OPEN 等待 Phase 6
- [x] 空 OPEN ProxyBatch 显式取消、非空批次 NEW/ASSIGNED 原子取消、责任释放与轮次联动
- [x] 已有 PICKED/DELIVERING/DELIVERED 时整批取消整体拒绝；逐单全取消自动 CANCELED
- [x] 配送员路线/直送/任务/大小确认移动页面与录单员代理批次取消交互
- [x] migration、专项/联合/全量测试、静态检查及 Docker 生产容器回归

本阶段新增 `dispatch.0002_routebatch`，为快递路线任务建立 RouteBatch 的取件区域与目的区域元数据；其余状态变化复用 Phase 3/4 已建立的 Order、ExpressRound、DeliveryTask、Assignment、DeliveryDrop、ChargeItem 与 CourierEarning，不重复造表。Phase 5 专项 11 项、配送/订单/代理联合 45 项、全量 72 项 pytest 测试通过；Ruff、Django check、migration drift check 与 `git diff --check` 均通过。Docker 生产镜像构建成功，一次性容器内 Django check 与 migrate check 通过，未遗留运行容器。首次镜像构建曾因 Docker Hub 鉴权网络超时失败，使用本机已配置的 DaoCloud 镜像及缓存重试后成功。多件 ConsolidationRound 创建、等待与最终关闭判定未提前实现，保留到 Phase 6。

## 后续阶段

- [x] Phase 3：订单、费用与结算基础模型
- [x] Phase 4：简单配送业务
- [x] Phase 5：快递复杂配送、基础 ExpressRound 关闭、原子整批取消
- [ ] Phase 6：归拢、多件轮次关闭、结算构建与凭证
- [ ] Phase 7：结算确认、收益与工资
- [ ] Phase 8：异常、人工处理、快速补录
- [ ] Phase 9：经营分析、搜索、Excel
- [ ] Phase 10：运维
- [ ] Phase 11：PWA/弱网/收尾

## 模块边界确认

| App | 主要职责及未来核心实体 |
|---|---|
| accounts | User、ActiveLoginLease、身份与会话 |
| customers | Customer、长期资料与历史快照 |
| agents | Agent、ProxyBatch、ProxyRecipient |
| config_center | 楼栋、区域、业务与价格配置 |
| orders | Order、六类 Detail、ExpressRound、录单与取消 |
| dispatch | DeliveryTask、Assignment、Transfer、DeliveryDrop |
| consolidation | ConsolidationRound/Item、归拢工作流 |
| settlements | ChargeItem、Settlement/Order/Line、FinancialAdjustment、CourierEarning |
| exceptions | ExceptionCase、人工处理 |
| mediafiles | MediaFile、配送证据、受控存储 |
| audit | 仅追加 AuditEvent |
| operations | BackupRecord、JobRun、MaintenanceState |
| dashboard | 只读筛选、聚合与导出 |

写入由各 App 的 `services/` 主持事务与状态迁移；复杂读取由 `selectors/` 提供。关键约束包括订单编号唯一、每单至多一个有效 Assignment、ExpressRound 收件归属二选一、代理来源仅限快递、费用项逻辑作废、SettlementLine 冻结后不可变。Phase 0 仅建立目录及运行基础，不提前创建业务模型或迁移。

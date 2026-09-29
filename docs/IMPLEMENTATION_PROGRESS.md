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
- [x] Phase 6：归拢、多件轮次关闭、结算构建与凭证
- [x] Phase 7：结算确认、收益与工资
- [ ] Phase 8：异常、人工处理、快速补录（除规格未定义的 ManualHandling 外已实现）
- [x] Phase 9：经营分析、搜索、Excel
- [x] Phase 10：运维
- [ ] Phase 11：PWA/弱网/收尾（自动化开发完成，等待真实设备验收）

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

## Phase 6：归拢、结算构建与凭证（已完成）

- [x] ExpressRound eligibility selector，统一排除上楼/当面交付、已归拢与阻塞归拢异常
- [x] Customer/ProxyRecipient 自动归拢及录单员/管理员人工合格子集归拢
- [x] 成员创建即冻结，默认负责人取成员中最后完成配送的配送员
- [x] 独立 `reassign_consolidation_round()`、找件状态、最终位置/近景/远景标注与审计
- [x] ExpressRound 等待已有 PENDING/IN_PROGRESS 归拢；完成后重算剩余候选并按少于 2 件关闭
- [x] ProxyBatch 空批次保持 OPEN、全部逐单取消 CANCELED、完整条件 READY_TO_SETTLE 与显式 reopen
- [x] `build_settlement()` 仅创建 DRAFT + 固定 SettlementOrder，UNKNOWN 可进入 DRAFT
- [x] DRAFT WEATHER/CUSTOMER_EXTRA/MANUAL/MULTI_ITEM 费用新增和逻辑作废
- [x] 结算级费用绑定当前 settlement；快递天气/多件优惠绑定 ExpressRound；客户加价明确 beneficiary
- [x] freeze 同事务重验订单占用、UNKNOWN、阻塞异常与非负总额，复制不可变 SettlementLine
- [x] freeze 后 Settlement/Order 同步 WAITING_PAYMENT；DRAFT/WAITING_PAYMENT 支持保留历史的 VOIDED
- [x] 普通客户结算图、ProxyRecipient 有价/无价客户凭证、Agent 无照片汇总图及版本化受控下载
- [x] 录单员宽窄屏结算/归拢管理页、配送员移动归拢清单/找件/拍照页
- [x] migration、专项/全量测试、静态检查及 Docker 生产容器回归

本阶段新增 `consolidation.0001_initial`（归拢轮次、冻结成员、负责人和最终证据）、`settlements.0002_*`（构建幂等键、结算图片版本、临时收件人凭证版本）、`settlements.0003_*`（每类正式图片/每位临时收件人仅一个有效版本）和 `exceptions.0003_*`（异常关联归拢轮次）。Phase 6 专项 7 项、全量 79 项 pytest 测试通过；Ruff、Django check、migration drift check 与 `git diff --check` 通过。代理批次在存在 DRAFT/WAITING_PAYMENT 账单时必须先废弃账单再 reopen，避免固定订单集合与新增成员并存。付款确认、收益结转、工资计算和结算撤销未提前实现，保留到 Phase 7。

## Phase 7：结算确认、收益与工资（已完成）

- [x] WAITING_PAYMENT 确认收款及 Settlement/Order/ProxyBatch 状态联动
- [x] 配送完成时的 PENDING_PAYMENT 基础收益绑定 Settlement，并冻结最终金额与分成比例
- [x] BASE_DELIVERY、UPSTAIRS、CUSTOMER_EXTRA、MANUAL_EXTRA 按来源独立记录
- [x] 确定性 earning_key 与重复确认幂等；未配置分成比例时拒绝确认
- [x] CUSTOMER_EXTRA 100% 锁定指定配送员，不乘普通分成
- [x] 管理员误结算撤销、原收益转 REVERSED、原凭证转历史且旧财务事实保留
- [x] 撤销后新建 Settlement 再结算，并创建全新的 CourierEarning
- [x] 真实退款以幂等、append-only FinancialAdjustment 追加，不修改 SettlementLine
- [x] 已结算净服务收入池、locked earning 与配送员收益聚合 selectors
- [x] 管理员比例/手工工资计算器、剩余池硬约束及个人超额软提醒
- [x] 结算确认、退款、撤销、收益明细与工资计算响应式页面
- [x] migration、专项/全量测试、静态检查及迁移漂移检查

本阶段新增 `settlements.0004_*`，为 append-only FinancialAdjustment 增加关键请求幂等键；工资计算保持只读 DTO，不表示工资已经发放，也不额外保存“已发工资”状态。真实退款默认不影响工资；按实施计划，“退款影响工资”的人工处置入口保留到 Phase 8。Phase 7 专项 4 项、全量 83 项 pytest 测试通过；Ruff、Django check、migration drift check与 `git diff --check` 通过。规格没有给出默认分成比例，系统继续保留未配置状态，并在确认结算需要对应收益来源时明确拒绝，未自行猜测默认值。Phase 8 尚未开始。

## Phase 8：异常、人工处理、快速补录（部分完成，等待规格）

- [x] ExceptionCase 管理员/录单员宽窄屏 UI 与配送员移动 UI
- [x] 显式 blocks_consolidation / blocks_settlement 修改、权限与 AuditEvent
- [x] ExceptionCaseAttachment 多图片上传与受控下载
- [x] ExceptionEvidenceLink 引用配送证据和归拢最终图片
- [x] OPEN 异常直接/间接媒体保护 selector
- [x] 异常解决后 `max(created_at + retention, resolved_at + retention)` 保留边界
- [ ] ManualHandling（权威规格缺少字段、动作类型、状态机及验收口径）
- [x] 真实退款显式选择是否影响计薪，并可记录个人工资扣减
- [x] DIRECT_COMPLETE：实际配送员、完成时间、位置、普通业务照片与正常待结算收益
- [x] HISTORICAL_BACKFILL：允许无照片、强制补录说明并保留实际完成时间
- [x] migration、专项/全量测试、静态检查及迁移漂移检查

本阶段新增 `exceptions.0004_*`，为异常创建增加幂等键并收紧附件/证据关系约束；新增 `orders.0002_order_entry_note`，将快速完成/历史补录说明与普通订单备注分开保存。已明确的 Phase 8 工作流专项 3 项、全量 86 项 pytest 测试通过；Ruff、Django check、migration drift check 与 `git diff --check` 通过。生产镜像构建成功，并在临时空数据卷上完成全量迁移和容器内 Django check；临时卷及后台 Docker 均已清理。`ManualHandling` 只在实施计划和模块职责中出现，当前规格没有可执行的数据模型或状态规则，已记录到 `docs/IMPLEMENTATION_QUESTIONS.md`，因此 Phase 8 尚不能标记为全部完成。

## Phase 9：经营分析、搜索、Excel（已完成）

- [x] 不可变 `DashboardFilters` DTO 与唯一表单解析入口
- [x] 时间、业务、配送员、普通/代理、Agent、取件/目的区域、路线、大小、加急、上楼、天气、异常、退款、费用项和结算状态筛选
- [x] 订单/物件、已结算收入、待收款、退款/减免、附加费用、平均客单价、异常和配送员收益 cards
- [x] 收入/订单趋势、业务收入、成员贡献、大小、路线、楼栋、费用项及普通/代理 Chart.js 数据
- [x] 固定/动态订单号全局搜索、`/` 分隔客户 token 与规范化取件标识搜索
- [x] Excel 继承相同筛选，并导出订单、费用项、SettlementLine、结算、退款/调整、收益和代理维度
- [x] 配送员移动优先个人统计，后端强制本人范围且不暴露团队经营总额
- [x] 管理员宽窄屏经营分析、响应式明细表、全局搜索和导航入口
- [x] 专项/全量测试、静态检查、迁移漂移检查及 Docker 生产容器回归

本阶段没有新增数据模型或 migration，所有经营指标继续实时聚合 Order、ChargeItem、SettlementLine、FinancialAdjustment 与 CourierEarning 等事实表，不建立每日统计真值表。Phase 9 专项 5 项、全量 91 项 pytest 测试通过；Ruff、Django check、migration drift check 与 `git diff --check` 通过。生产镜像构建成功，并在临时空数据卷中完成全量迁移和容器检查，临时卷及 Docker Desktop 已清理/关闭。跨本地午夜运行全量测试时同时修正了两处既有工资测试使用 UTC `.date()` 的脆弱断言，生产工资查询仍按 Asia/Shanghai 本地业务日期。`ManualHandling` 规格缺口继续保留，Phase 10 尚未开始。

## Phase 10：运维（已完成）

- [x] 独立 scheduler 每日 03:00 自动备份及管理员手动备份
- [x] SQLite 在线备份、配置快照、manifest 校验和与照片归档
- [x] 普通图片、生成结算图、ProxyRecipient 凭证和 Agent 汇总图统一保留期清理
- [x] OPEN 异常直接/间接图片保护及解决后完整 retention 周期
- [x] 备份照片归档独立清理，数据库与配置备份继续保留
- [x] 结算凭证完整重建与明确标识的无照片历史模式
- [x] restore 前 PRE_RESTORE 保护备份、校验及恢复后持续维护模式
- [x] Maintenance mode 应用写入门禁，不包含宿主机关机或 Docker 控制
- [x] startup recovery 文件系统/SQLite/中断任务/临时文件/租约检查，不回滚配送状态
- [x] JobRun 自动任务幂等记录及 stale login lease 清理
- [x] 管理员备份、恢复、维护、媒体浏览下载、单项/批量清理和空间统计页面
- [x] migration、专项/全量测试、静态检查及迁移漂移检查

本阶段新增 `operations.0001_initial`，建立 manifest 对应的 BackupRecord、自动任务幂等 JobRun 和应用级 MaintenanceState。备份目录按数据库、非敏感配置快照、manifest 与可独立删除的 `photos.tar` 分层保存；恢复不会因历史照片已经清理而失败，并始终先生成 PRE_RESTORE 保护点。Phase 10 专项 6 项、全量 97 项 pytest 测试通过；Ruff、Django check、migration drift check 与 `git diff --check` 通过。scheduler 继续作为 Compose 独立进程运行，Web 启动前执行只做检查和安全清理的 recovery command。`ManualHandling` 权威规格缺口仍未消除；Phase 11 尚未开始。

## Phase 11：PWA、弱网与发布收尾（自动化部分完成）

- [ ] PWA 安装验证（manifest、service worker、静态资源和 Edge 渲染通过；Android/Windows 实际点击安装待人工）
- [x] 关键文本表单 localStorage 草稿保留及手工清除
- [x] 图片表单页面内提交，失败后保留 File 引用并支持重试
- [x] 网络状态提示和明确的“无离线业务”边界
- [x] Order 创建 `operation_id` 持久化、唯一约束与重复请求回查
- [ ] Android 真机测试（必须在真实设备和正式 HTTPS Origin 执行）
- [ ] Windows 管理员/录单员完整交互测试（宽/窄屏无头渲染通过，UI 自动化运行资产缺失）
- [x] 配送员桌面保持 480px 移动卡片布局的模板/CSS 回归
- [x] DEBUG-only、幂等且不会进入生产初始化的 Demo seed
- [x] 可重复运行且不覆盖现有数据的初始化配置/管理员命令
- [x] 开源 README 与 MIT License
- [x] V1 验收矩阵、问题记录、空库迁移、Docker 初始化和最终自动回归

本阶段新增 `orders.0003_order_creation_operation_id`，通过安全的“可空字段 → 逐行 UUID 回填 → 非空唯一字段”迁移为历史及新订单建立创建幂等键；`orders.0004_order_creation_fingerprint` 保存请求指纹，拒绝同键不同内容。新增弱网 resilience 脚本、network-first 只读离线提示 service worker、`seed_demo`、`seed_initial_config` 与 `create_app_admin` 命令。Phase 11 专项 6 项、全量 103 项 pytest 测试通过；Ruff、Django check、migration drift、JavaScript 语法和 `git diff --check` 通过。生产镜像在临时空数据卷完成全量迁移、初始化配置、管理员幂等创建、PWA 静态文件收集、Recovery Check，并验证生产环境拒绝 `seed_demo`；临时卷和 Docker Desktop 已清理。真实 Android/Windows PWA 安装和 Android 相机/触控测试尚未执行，因此 Phase 11 不标记为全部完成。Phase 8 `ManualHandling` 规格缺口亦继续保留。

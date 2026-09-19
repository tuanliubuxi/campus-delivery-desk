# 00. 编码 AI 执行约束

本文件为最高优先级工程约束。目标：让 0 上下文编码 AI 在不擅自改需求的前提下，写出可维护的模块化 Django 单体，而不是“大视图 + 大模型 + 大模板”的屎山。

## 1. 开始编码前必须执行

1. 阅读本目录全部文档。
2. 建立 `docs/IMPLEMENTATION_PROGRESS.md`，按 `11_IMPLEMENTATION_PLAN.md` 建立 TODO。
3. 输出一次“模块边界确认”：列出 Django Apps、核心实体、service、selector、状态机、关键数据库约束。
4. 再开始写代码。

不得完成一个 TODO 就停止。每个 Phase 应完成该阶段所有可完成任务、迁移、测试和文档更新后再进入下一阶段。

## 2. V1 技术栈固定

V1 固定使用：

```text
Django 单体 + Templates + HTMX + Alpine.js
SQLite(WAL)
本地文件存储
独立 scheduler
Docker Compose + Caddy
Responsive Web + PWA
```

未经需求变更，禁止自行换成：React/Vue SPA、DRF、FastAPI、Flask、PostgreSQL、Redis、Celery、微服务、Kafka、Kubernetes、MinIO、WebSocket、GraphQL。

专业版技术栈只记录在 `13_FUTURE_PRO_STACK.md`，不是 V1 TODO。

## 3. Django View 必须薄

View 只负责：

- 身份/角色检查；
- Form/请求参数读取；
- 调用 service；
- 选择完整模板或 HTMX partial；
- 将业务错误转换成可读响应。

禁止在 View 里写：价格公式、状态机、归拢判定、抢单、转单、退款、工资、代理结算、备份核心逻辑。

## 4. 所有写业务集中到 service

示例：

```text
apps/orders/services/create_express.py
apps/dispatch/services/claim_route.py
apps/dispatch/services/complete_drop.py
apps/consolidation/services/create_round.py
apps/settlements/services/build_settlement.py
apps/agents/services/create_proxy_batch.py
apps/operations/services/create_backup.py
```

View、Template、scheduler 不得直接修改核心状态字段。scheduler 必须调用和人工操作相同的 service。

## 5. 查询逻辑进入 selector

复杂列表、搜索、报表、Dashboard 聚合统一放 `selectors/`，禁止模板中 N+1 查询。

V1 仪表盘不建立“每日统计真值表”，优先从订单、配送、费用项、结算、收益等事实表实时聚合。

## 6. 禁止用 Django signal 驱动关键业务

不得用 signal 自动：

- 修改订单状态；
- 创建归拢；
- 创建结算；
- 生成费用项/收益；
- 处理代理批次；
- 退款或工资调整。

关键流程必须在显式 service workflow 中发生。

## 7. 禁止万能 JSON 承载核心字段

核心业务字段必须类型化。包括但不限于：

- 业务类型、状态；
- 取件区域、取件标识、快递大小；
- 外卖识别信息；
- KFC 取餐码；
- 跑腿起终点；
- 行李楼层/件数；
- 代理人、临时收件人；
- 费用项、结算、收益；
- 会话租约。

JSON 仅用于非核心扩展元数据或审计附加信息。

## 8. 费用与结算快照

禁止通过 `order.total = x` 直接覆盖最终金额。ChargeItem 是业务费用来源，必须采用 `ACTIVE / VOIDED` 状态；费用录错时逻辑作废，不物理删除。

Settlement 在 DRAFT 阶段只固定 SettlementOrder，允许继续编辑当前 Settlement 的结算级 ChargeItem。DRAFT 页面展示的金额只是“SettlementOrder 对应订单的 ACTIVE 订单级费用项 + `settlement_id=当前 Settlement` 的 ACTIVE 结算级费用项”的实时预览，不是冻结后的历史金额。不得按 Customer/ProxyRecipient 全量扫描历史费用项。

只有在“生成有效结算凭证 / 进入待付款”时，才把上述当前有效 ChargeItem 复制为不可变 SettlementLine，并在同一事务中重新校验 UNKNOWN 快递、阻塞异常和最终金额。冻结后的 `amount_due_snapshot` 必须 `>= 0`；允许 0 元结算，但负数必须拒绝并要求修正费用项。随后把 Settlement 和对应 Order 切到 WAITING_PAYMENT。冻结后历史金额只能按 SettlementLine 计算，不得再通过修改 ChargeItem 改写。

所有金额变化必须形成费用项，例如：

```text
BASE_SERVICE
OFF_CAMPUS_PICKUP
CAMPUS_TO_OFF_CAMPUS
URGENT
WEATHER
UPSTAIRS
CUSTOMER_EXTRA
MANUAL_SURCHARGE
MANUAL_DISCOUNT
MULTI_ITEM_DISCOUNT
```

每项至少保存 label、quantity、unit_price、amount、来源、配置快照、创建人和时间。`CUSTOMER_EXTRA` 必须有明确收益人；涉及多个配送员时拆成多条费用项，不做自动平均。

## 9. V1 不包含的机制

V1 不包含以下体系，编码 AI 不得自行加入：

- 快递 BusinessDay OPEN/CLOSED；
- 22:00 自动收工；
- 人工快递收工；
- 日终优惠返还任务；
- “当天关闭后不可录单”规则。

需要提前录明天业务，只使用普通 `service_date`。所有 EXPRESS 订单的 `service_date` 都必须有值；录单 UI 和后端默认使用当前本地日期，只有提前录未来快递时才修改。其他业务可按需求为空。

## 10. 明确禁止的功能

- 公开注册；
- 账号共用；
- 同账号两个有效活跃会话；
- 客户合并；
- 复杂行李搬运；
- 跨业务类型合并结算；
- 部分付款账务模型；
- 配送员同时处理不同业务类型活跃任务；
- 已取件物件无交接直接转人；
- 已完成记录无痕修改；
- 删除关键审计/结算/退款历史；
- 图片 BLOB 入库；
- 站内通知/Push/微信自动通知；
- 原生 Android/Windows 客户端；
- 真正离线下单/离线配送同步；
- 地图路径规划、GPS 实时追踪、OCR/AI 识别。

## 11. 代理单核心不变量

- V1 代理体系仅支持 EXPRESS；其他业务禁止 source_type=AGENT。
- Agent 是长期代理人档案。
- ProxyBatch 是一次代理推单/结算范围。
- ProxyRecipient 是该批次临时收件人，不进入 Customer。
- 每件代理快递必须绑定一个 ProxyRecipient。
- 配送/归拢按 ProxyRecipient 分组。
- 代理批次统一由 Agent 与平台结算。
- 每个 ProxyRecipient 单独生成可转发的客户凭证；是否显示我方价格默认开启。
- Agent 另外得到无照片的整批结算汇总图。
- ProxyBatch READY_TO_SETTLE 后默认冻结成员；SETTLED 后禁止追加；重新打开必须显式 service + AuditEvent。


## 12. 结算与收益不可变规则

- 配送完成可以创建 `PENDING_PAYMENT` CourierEarning，`settlement_id` 允许为空；禁止为了满足外键创建虚假的 DRAFT Settlement。
- 快递必须通过显式 `ExpressRound` 表达“某收件归属的本轮快递”；归拢、多件优惠和快递结算不得各自猜测“本轮”。
- ExpressRound 内所有订单都取消、有效已送达数量为 0 时必须自动 CLOSED，不得遗留空的 OPEN 轮次。
- `cancel_proxy_batch()` 是整批原子取消：只允许 OPEN 批次且批次内不存在 PICKED/DELIVERING/DELIVERED 的有效快递；事务内自动取消仍可取消的 NEW/ASSIGNED 订单、释放未取件 Assignment，并重新评估/关闭相关 ExpressRound，最后将 ProxyBatch 置为 CANCELED。不得要求录单员先逐单取消。
- `build_settlement()` 只创建 DRAFT Settlement 并固定 SettlementOrder；DRAFT 阶段不生成 SettlementLine。
- 生成有效结算凭证时才把 ACTIVE ChargeItem 冻结为 SettlementLine，并同时将 Settlement/Order 切到 WAITING_PAYMENT。
- DRAFT 或尚未付款的 WAITING_PAYMENT 结算如放弃/有误，标记 VOIDED；不得修改已冻结 SettlementLine。已确认付款的误结算使用 REVERSED。
- 同一 Order 同时最多属于一个 DRAFT/WAITING_PAYMENT/SETTLED 的有效 Settlement；VOIDED/REVERSED 不占用。
- Settlement 撤销后原 Settlement/CourierEarning/图片只保留为历史，不覆盖；再次结算创建新记录。
- ChargeItem 不物理删除，错误项改为 VOIDED；构建冻结时只读取 ACTIVE 项。
- CourierEarning 按收益来源拆行，并用确定性的 `earning_key` 保证幂等。
- CUSTOMER_EXTRA 100% 归明确指定的 beneficiary courier；只有一个最终配送员时可自动选，多人时录单员必须选择，需多人分配则创建多条 CUSTOMER_EXTRA。
- 快递 UNKNOWN 的 BASE_SERVICE 使用订单创建时四档价格快照。
- 是否上楼必须持久化为 `Order.requires_upstairs`，不得根据 floor/room 或最终投放类型推断。
- 归拢负责人调整使用独立 `reassign_consolidation_round()`，不得修改已经 DELIVERED 订单的 Assignment。

## 13. 单会话与心跳

- 一个账号同一时刻仅一个 active login lease。
- 心跳建议 30 秒一次；超时建议 150 秒后视为 stale。
- 新登录发现新鲜租约时拒绝。
- stale 租约允许新登录覆盖，并使旧 Session 失效。
- `sendBeacon` 关闭标签注销只能作为辅助，不能作为唯一机制。
- 管理员支持强制下线。

## 14. SQLite 约束

V1 使用 SQLite WAL，禁止假设 PostgreSQL 行级锁语义。

- 不依赖 `select_for_update()` 解决抢单。
- 使用唯一约束 + 条件写入 + `transaction.atomic()` + 冲突回查。
- 同一订单同时最多一个 active assignment。
- 批量接单允许部分成功。
- `database is locked` 只允许有限短重试并给用户明确提示。

## 15. 代码质量

- 金额用 `Decimal`/`DecimalField`，禁止 float。
- 枚举用 `TextChoices`/Enum，禁止魔法字符串。
- 时间必须 timezone-aware。
- 关键 service 写明事务边界。
- 关键写操作幂等或有重复提交保护。
- 禁止 `except Exception: pass` 和静默吞异常。
- 自动任务必须有 JobRun 记录。
- 数据库 migration 不得通过删除生产历史数据“简化”。

## 16. 完成标准

每个 Phase 必须同时交付：

- 代码；
- migration；
- 自动测试；
- 页面/静态资源；
- 文档更新；
- Docker Compose 可运行状态；
- TODO 状态更新。

“只写了模型”“只有接口没有页面”“页面能点但没有测试”均不算完成。

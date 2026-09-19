# 05. 后端实现规范

## 1. 录单 Service

不要实现“万能动态业务表单引擎”。按业务类型提供清晰 creator：

```python
create_express_order(...)
create_takeout_order(...)
create_kfc_order(...)
create_grocery_order(...)
create_errand_order(...)
create_luggage_upstairs_order(...)
```

公共步骤：权限 → 收件归属解析 → 条件必填校验 → 重复检查 → 编号 → 快照 → detail → 初始费用项/价格规则快照 → AuditEvent。

`source_type=AGENT` 仅允许 `EXPRESS`；其他五种业务必须使用普通 Customer 来源。

## 2. 普通客户与代理录单

普通单使用 Customer；代理快递使用 ProxyBatch + ProxyRecipient。

代理录单页面先选择 Agent/创建 ProxyBatch，再创建临时收件人。每件代理快递必须绑定一个 ProxyRecipient。

系统支持自动临时名：`{楼栋}号楼#{本批次序号}`。

ProxyBatch 处于 READY_TO_SETTLE 或 SETTLED 时不能直接新增成员。READY_TO_SETTLE 需要补单时必须显式 `reopen_proxy_batch()` 回到 OPEN 并写审计。

## 3. 单会话登录

`login_user_with_lease()`：

1. 校验账号和密码；
2. 查询 ActiveLoginLease；
3. fresh lease 存在则拒绝登录；
4. stale lease 则 revoke；
5. 创建 Django Session + 新 lease；
6. AuditEvent LOGIN。

`heartbeat()` 只刷新当前 lease 的 `last_seen_at`。管理员 force logout 立即 revoke lease 并删除/失效 Session。

## 4. 订单编号

编号 service 同时提供：

```text
fixed_id   = {business_code}-{YYMMDD}-{seq3}
display_id = {business_code}-{status_code}-{YYMMDD}-{seq3}
```

搜索 parser 必须能把两种格式解析到同一个 `(business_type, sequence_date, daily_sequence)`。

## 5. 重复订单检查

快递强提醒条件：同一收件归属 + pickup_area + normalized pickup_identifier + 时间窗口。

命中后 UI 弹警告但允许“仍然创建”，不要求填写原因。

外卖/KFC/果蔬/跑腿做较弱提醒。

## 6. 快递取件信息与 UNKNOWN 大小

取件统一使用：

```text
pickup_area
outside_pickup_location
pickup_identifier_type
pickup_identifier
size_class
```

创建快递订单时，无论大小是否 UNKNOWN，都要把当时配置中心的 SMALL/MEDIUM/LARGE/OVERSIZE 四档价格写入 ExpressOrderDetail 的价格快照字段。

- 已知大小：按订单创建时快照立即生成 BASE_SERVICE ChargeItem；
- UNKNOWN：暂不生成 BASE_SERVICE；最终配送员调用 `confirm_express_size()` 后，按订单创建时对应档位快照生成 BASE_SERVICE。

配置中心之后修改价格不得影响已创建订单。

UNKNOWN 快递允许先进入 DRAFT Settlement，便于录单员检查订单集合和费用预览；`build_settlement()` 不以 UNKNOWN 作为通用硬拒绝条件。真正进入待付款前，`freeze_settlement_for_payment()` 必须重新查询并硬校验所有 EXPRESS 已非 UNKNOWN 且已有有效 BASE_SERVICE；任一不满足都拒绝冻结和生成有效结算凭证。

## 7. 是否上楼

使用 `Order.requires_upstairs` 作为业务真值：

- 普通订单默认 false；
- 用户明确要求送上楼时 true；
- 行李搬上楼固定 true。

楼层/房间只用于地址信息和计价输入，不得以 `floor != null` 推断是否上楼；最终 DeliveryDrop.location_type 也不得反向改写该字段。

## 8. 费用项生成原则

价格规则集中在 `settlements/services/pricing.py` 或等价模块。

系统自动费用项：

- 基础服务费；
- 校外取件 +1/件；
- 校内送校外 +2/件；
- 加急；
- 行李/快递上楼。

DRAFT 结算阶段可选/人工费用项：

- 特殊天气；
- 客户自愿加价；
- 其他增费；
- 减免；
- 本轮多件优惠。

禁止直接修改 final total。

ChargeItem 使用 `ACTIVE / VOIDED`。费用录错、取消、替换时调用 `void_charge_item(item, reason, actor)`，保存 voided_at/voided_by/void_reason；禁止物理删除。DRAFT 预览和冻结流程都只读取 ACTIVE ChargeItem。

ChargeItem 是业务费用来源，SettlementLine 是进入 WAITING_PAYMENT 时的冻结快照。两者职责不得混用。

## 9. 路线池 Selector

输入：

```text
pickup_area: SOUTH/NORTH/OUTSIDE
destination_zone/scope
courier
```

OUTSIDE 路线中的订单可来自不同具体校外站点，任务卡必须显示每件具体取件地点。

只返回未接单、未取消、无 active assignment、符合路线模式的快递。

排序：urgent desc → 等待时间 → building.route_order → created_at。

## 10. 路线并发接单

SQLite 不依赖 row lock。

建议：事务中创建 task，对选中订单逐项/批量创建 Assignment，利用数据库唯一约束处理冲突，回查成功项，允许部分成功。

无成功项时删除空 task。

## 11. 取件/开始配送

`mark_picked_up()` 只允许本人 active assignment 且 ASSIGNED → PICKED。

任务级 `start_delivery()` 仅将已 PICKED 的项改 DELIVERING，异常件不阻塞。

## 12. complete_delivery_drop

输入至少：

```text
order_ids
courier
final_location_text
location_type
near_photo(optional for luggage)
far_photo(optional)
far_annotation(optional)
```

普通配送至少 1 张 evidence；行李上楼允许无照片。

远景标注由前端生成派生图片，服务端保存 parent_media 关系，不覆盖原远景图。

若一次完成多个 order_ids，所有订单必须同时满足：

1. 当前配送员拥有有效 Assignment/配送责任；
2. 均处于允许完成配送的状态；
3. 属于同一个 Customer 或同一个 ProxyRecipient；
4. business_type 相同；
5. 目的楼栋/目的地与实际放置动作兼容；
6. 同一个 final_location_text 能真实描述全部物品；
7. 同一组照片确实能作为全部物品的共同凭证。

不同客户、不同实际放置位置或不兼容的业务不得为了少拍照片而合并到一个 DeliveryDrop。

事务内：

1. 完成上述兼容性和状态校验；
2. `requires_upstairs=true` 时校验楼层/房间与业务例外；
3. 创建 DeliveryDrop；
4. 绑定 items/media；
5. 订单置 DELIVERED；
6. 结束 assignment；
7. 生成/补齐系统费用项；
8. 创建确定性的 BASE_DELIVERY `PENDING_PAYMENT` CourierEarning 归属记录，`settlement_id=NULL`，用 earning_key 防重复；
9. EXPRESS 订单更新/评估所属 ExpressRound 与归拢条件；
10. AuditEvent。

此时不为了 CourierEarning 人为创建 DRAFT Settlement。

## 13. 上楼计价

规则按件：

- 小/中件：楼层 × 0.5 × 件数；
- 大/超大件：楼层 × 1.0 × 件数。

快递送上楼与行李搬上楼共用该费率配置。

## 14. ExpressRound 与归拢

### ExpressRound

`get_or_create_express_round(recipient, service_date)`：EXPRESS 创建前必须得到非空 service_date；表单未显式填写时由后端填当前本地日期，不允许使用 sequence_date 作为隐式兜底。随后查找同一收件归属、相同 service_date、`status=OPEN` 的 ExpressRound；存在则加入，否则创建新的 round_no。

`evaluate_express_round(round)`：

- 只要存在有效 NEW/ASSIGNED/PICKED/DELIVERING 订单，保持 OPEN；
- 否则统计 `delivered_count = 未取消且 delivery_status=DELIVERED` 的订单数；
- `delivered_count == 0`：表示本轮全部订单已取消，立即自动 CLOSED，不创建 ConsolidationRound；
- `delivered_count == 1`：无需归拢，直接 CLOSED；
- `delivered_count >= 2`：按 eligibility 计算需要归拢的候选；候选为空时直接 CLOSED；存在候选时创建/等待必要 ConsolidationRound，全部必要归拢 COMPLETED 后 CLOSED。

不同 service_date 永不互相阻塞；一个 round CLOSED 后同一天新增快递也创建下一 round_no。

### ConsolidationRound

自动/手动归拢都按“收件归属 + ExpressRound”处理。候选只选择：EXPRESS、DELIVERED、属于同一 ExpressRound、未入其他 ConsolidationRound、非客户已取、非上楼/当面交付、无 `OPEN && blocks_consolidation=true` 异常的物件。

录单员/管理员可以对已送达的合格子集手动提前创建 ConsolidationRound。创建后成员立即冻结；同一 ExpressRound 后续剩余物件可按规则形成其他 ConsolidationRound。

默认 `assigned_courier_id` 为该归拢成员中最后完成配送的配送员。

负责人调整必须使用：

```python
reassign_consolidation_round(round, new_courier, reason, operator)
```

该 service 只修改 ConsolidationRound 负责人并记录原负责人、新负责人、原因和 AuditEvent；不得创建 Order Transfer，也不得改变已 DELIVERED 订单的 Assignment。

完成前要求所有 item 为 FOUND 或已有明确人工处置；最终近景合照和位置必填，远景标注推荐但非必填。

## 15. 简单业务复用

外卖/KFC/果蔬/跑腿/行李复用：

```python
claim_simple_task()
mark_simple_picked()
start_simple_delivery()
complete_delivery_drop()
```

业务 detail 只负责字段差异与价格规则，不复制状态机。

## 16. 转单

未取件：退池或指定转单。

已取件：必须 handoff；接收人确认实物后切 Assignment。

已完成：不能转，走异常/人工处理。

## 17. ProxyBatch 状态服务

`evaluate_proxy_batch_ready(batch)` 先统计非取消订单。若非取消订单数量为 0（例如录单员逐单取消了整批所有订单），不得利用“全部非取消订单已完成”的空集合条件推进 READY_TO_SETTLE，而应将仍为 OPEN 的 ProxyBatch 自动置为 CANCELED、确认相关 ExpressRound 已按规则 CLOSED，并写 AuditEvent。

只有至少存在 1 个非取消订单时，才在以下全部满足后把 OPEN 自动推进为 READY_TO_SETTLE：

- 所有非取消快递已 DELIVERED；
- 所有相关 ExpressRound 已 CLOSED，且其中必要 ConsolidationRound 已 COMPLETED；
- 所有 Express size 已非 UNKNOWN；
- 无 `OPEN && blocks_settlement=true` 的 ExceptionCase；
- 费用可完整计算。

`reopen_proxy_batch()`：READY_TO_SETTLE → OPEN；只允许 recorder/admin；使未结算汇总图失效并写 AuditEvent。

`cancel_proxy_batch(batch, operator, reason)`：只允许 `status=OPEN`，并且批次内不存在任何 `PICKED / DELIVERING / DELIVERED` 的有效快递。该操作必须在一个事务中完成，不要求录单员先逐单取消：

1. 锁定/重新读取批次及其非取消订单，重复校验没有已取实物或已完成订单；
2. 将仍为 NEW/ASSIGNED 的订单按“代理批次取消”原因走正常取消逻辑；
3. 对 ASSIGNED 但未 PICKED 的订单释放 Assignment/任务占用；
4. 收集受影响的 ExpressRound 并逐个调用 `evaluate_express_round()`；全取消轮次应自动 CLOSED；
5. ProxyBatch → CANCELED；
6. 写批次级和必要的订单级 AuditEvent。

任一有效快递已 PICKED/DELIVERING/DELIVERED 时整个事务拒绝，不做部分批次取消。此时仍可逐单取消尚未取件订单；已取实物/已完成订单走配送、异常或人工处理。READY_TO_SETTLE 不允许整批取消。

SETTLED 后禁止追加成员或订单。

## 18. Settlement 构建、编辑、冻结与废弃

### 普通客户

不跨业务。快递按选定的 CLOSED/可结算 ExpressRound 建立 Settlement；简单业务通常一单一结算。

### 代理单

ProxyBatch 由 Agent 统一付款。只有 READY_TO_SETTLE 才能建立最终 Agent Settlement。

### build_settlement()

DRAFT 阶段不冻结费用：

1. 事务内确认每个待结算 Order 当前不属于其他 DRAFT/WAITING_PAYMENT/SETTLED Settlement；
2. 创建 `Settlement(status=DRAFT, amount_due_snapshot=NULL)`；
3. 用 SettlementOrder 固定本轮订单集合；
4. 返回“SettlementOrder 对应订单的 ACTIVE ORDER 费用项 + 当前 settlement_id 的 ACTIVE SETTLEMENT 费用项”的 preview amount；该预览不是历史事实，且不得按 Customer/ProxyRecipient/ExpressRound 扫描历史费用。

DRAFT 阶段允许继续添加/作废 WEATHER、CUSTOMER_EXTRA、MANUAL_SURCHARGE、MANUAL_DISCOUNT、MULTI_ITEM_DISCOUNT 等 ChargeItem。这些结算时创建的费用项必须 `scope_type=SETTLEMENT` 且绑定当前 `settlement_id`；快递 WEATHER/MULTI_ITEM_DISCOUNT 同时记录对应 `express_round_id`，WEATHER 记录 Customer/ProxyRecipient 归属。SettlementOrder 不随意增删；如选错订单，优先 VOID 整份 DRAFT 后重建。旧 VOIDED Settlement 上的结算级费用项不会被新 Settlement 自动拾取。

### freeze_settlement_for_payment() / generate-valid-receipt

点击“生成有效结算凭证 / 进入待付款”时在一个事务内：

1. 校验 Settlement 仍为 DRAFT，并重新查询 Order/ProxyBatch/异常状态；所有 EXPRESS 必须已确认大小且存在有效 BASE_SERVICE；
2. 只收集两类费用：SettlementOrder 对应 `order_id` 的 ACTIVE `scope_type=ORDER` ChargeItem，以及 `settlement_id=当前 Settlement` 的 ACTIVE `scope_type=SETTLEMENT` ChargeItem；禁止按 Customer/ProxyRecipient/ExpressRound 全量扫描历史费用；
3. 逐项复制为不可变 SettlementLine，并保留 order/recipient/express_round 等归属快照；
4. `amount_due_snapshot = Σ SettlementLine.amount`。若结果 `< 0` 则拒绝冻结并提示检查减免/费用项；`= 0` 允许；通过后写 frozen_at；
5. 生成本次有效结算凭证；
6. Settlement → WAITING_PAYMENT；
7. 所有 SettlementOrder 对应 Order：UNSETTLED → WAITING_PAYMENT。

冻结后金额只能读取 SettlementLine，不得实时回查 ChargeItem 改写历史。

### void_settlement()

- DRAFT 可以直接 VOIDED；Order 原本仍是 UNSETTLED。
- WAITING_PAYMENT 在尚未实际付款时可以 VOIDED；相关 Order 回 UNSETTLED，当前有效凭证标记 INVALID/VOIDED。
- VOIDED Settlement/SettlementLine/图片记录保留审计历史，不物理删除；重新结算创建新 DRAFT。
- SETTLED 不允许 VOIDED，误确认付款走 REVERSED。

## 19. 特殊天气、优惠与客户自愿加价

特殊天气按“一个收件归属的一次结算轮”计一次，默认 +2。添加时必须绑定当前 `settlement_id`；快递场景同时记录 `express_round_id`，不得在后续 Settlement 中按收件人历史自动复用：

- 普通客户：Customer 当前 round；
- 代理单：ProxyRecipient 当前 round；
- 简单业务通常一单一 round。

代理批次中如果两个 ProxyRecipient 都勾选天气，应分别产生两项天气费。

多件优惠：

```python
discount_count = max(parcel_count - 5, 0)
discount_amount = -(discount_count * Decimal('0.50'))
```

只计算当前 ExpressRound/当前结算轮，不跨轮累计，不自动应用。应用时创建绑定当前 `settlement_id + express_round_id` 的负 ChargeItem。

CUSTOMER_EXTRA 由录单员填写，每一条必须明确 `beneficiary_courier_id`，且 100% 锁定给该配送员。若本轮只有一个最终配送员可自动选中；若有多个最终配送员，UI 必须要求录单员选择。客户明确给多名配送员加价时，拆成多条 CUSTOMER_EXTRA，不做自动平均。

## 20. 结算/代理图片

DRAFT 可以提供预览，但带价格的“正式有效结算凭证”必须由 freeze_settlement_for_payment() 基于冻结后的 SettlementLine 生成。

每个 ProxyRecipient 生成可转发凭证；`show_price_on_receipt` 默认 true，可关闭。Agent 获得无照片的批次汇总图；代理人下游定价不入库。

普通客户结算图、ProxyRecipient 凭证、Agent 汇总图都作为 `GENERATED_RECEIPT`/对应版本媒体管理，默认执行 30 天保留策略。媒体文件清理后保留版本元数据和 SettlementLine：

- Agent 汇总图可完全按结构化数据重新生成；
- 普通客户/ProxyRecipient 凭证若原配送照片仍在，可完整重新生成；
- 原配送照片也已清理时，只能生成“无照片历史凭证”，图片区明确写明历史照片已按保留策略清理。

生成 ProxyRecipient 无价格配送凭证本身不改变 ProxyBatch 状态；Agent 最终结算图的正式生成属于 Settlement freeze 流程。

## 21. 确认结算

`confirm_settlement()`：仅 recorder/admin，且 Settlement 必须 WAITING_PAYMENT。

事务内：

1. Settlement → SETTLED；
2. 相关 Order.settlement_status → SETTLED；
3. 将配送完成时建立的 BASE_DELIVERY PENDING_PAYMENT CourierEarning 按最终收益规则确定金额、绑定 Settlement 并转为 SETTLED；
4. 根据 SettlementLine/ChargeItem 来源为 UPSTAIRS、CUSTOMER_EXTRA、MANUAL_EXTRA 等创建或完成独立 CourierEarning 收益行；所有收益行用确定性 earning_key 保证幂等；
5. CUSTOMER_EXTRA 100% 计入费用项指定的 beneficiary courier；
6. ProxyBatch（若适用）→ SETTLED；
7. AuditEvent。

重复 confirm 必须幂等，不重复收益。

## 22. 撤销误结算

`reverse_settlement()` 只处理误确认，不等同真实退款。

事务内：

1. 原 Settlement：SETTLED → REVERSED；
2. 创建 `FinancialAdjustment(type=SETTLEMENT_REVERSAL)`；
3. 相关 Order.settlement_status → UNSETTLED；
4. 原 CourierEarning：SETTLED → REVERSED；
5. 原结算图片保留并标记历史/已撤销；
6. ProxyBatch（若适用）：SETTLED → READY_TO_SETTLE；
7. AuditEvent。

再次收款时创建新的 Settlement、新 SettlementLine、新 CourierEarning、新图片版本。不得复用原 Settlement 或把原 CourierEarning 改回 PENDING_PAYMENT。

真实退款使用 REFUND/FinancialAdjustment，保留原 SETTLED 事实。

## 23. 工资计算器

`available_pool` 定义为：所选周期已经完成客户/代理结算的净服务营业收入，扣除影响计薪的退款/减免，不包含待付款、商品采购款和 REVERSED 结算。

其中具有强制收益归属的金额先锁定。例如 CUSTOMER_EXTRA 100% 锁定其 beneficiary courier：

```text
available_pool = 900
locked_to_couriers = 20
manual_allocatable_remaining = 880
```

`calculate_wages(filters, mode)`：

- RATIO：普通业务收益按业务分成快照计算，强制归属收益直接加入对应人员；
- MANUAL：管理员分配剩余可人工分配池，强制归属部分不可转给别人。

MANUAL 硬约束 `sum(manual_allocations) <= manual_allocatable_remaining`。个人最终工资高于本人直接产生的普通配送收益只返回 warning，不阻塞。

## 24. Dashboard Selector

统一 Filter DTO：时间、业务、成员、source_type、agent、pickup_area、destination、size、route、urgent、upstairs、weather、异常、退款、charge_type 等。

`upstairs` 必须读取 `Order.requires_upstairs`，不能根据楼层字段猜测。

所有 cards/chart/export 使用同一 filter parser，避免不同页面口径不一致。

## 25. 异常图片保护

ExceptionCase 可以直接通过 ExceptionCaseAttachment 关联 MediaFile，也可以通过 ExceptionEvidenceLink 引用 DeliveryEvidence/归拢证据。

图片清理 selector 在遇到 OPEN ExceptionCase 的直接或间接关联时必须跳过。

业务阻塞不通过 reason_code 临时猜测。ExceptionCase 显式保存 `blocks_consolidation` 和 `blocks_settlement`；reason_code 仅负责给默认值。归拢/结算 service 分别统一检查 `OPEN && 对应 blocks_* = true`。管理员/录单员修改阻塞属性必须写 AuditEvent。

异常解决后的删除时间按：

```text
delete_after = max(
    media.created_at + retention_days,
    exception.resolved_at + retention_days
)
```

计算。异常刚解决时至少再保留一个完整 retention 周期。

## 26. 备份与 scheduler

V1 不存在快递收工 service。

scheduler 主要任务：

- 每日 03:00 自动备份；
- 每月图片清理；
- stale login lease 清理；
- 必要的临时文件清理。

所有任务必须 JobRun 幂等记录。

## 27. 幂等

关键写操作使用 `operation_id` 或业务唯一状态判断：路线接单、直送接单、配送完成、归拢完成、Settlement 构建、结算确认/撤销、代理图片生成、ProxyBatch 重新打开、备份、恢复保护备份。

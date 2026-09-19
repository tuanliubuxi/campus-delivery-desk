# 04. 数据模型设计

本文件为概念模型。编码时可微调命名，但不得改变实体边界、责任和核心约束。

## 1. User 与 ActiveLoginLease

### User

```text
id
username                  内部唯一，可自动生成
display_name
role                      ADMIN / RECORDER / COURIER
emoji_avatar
is_active
accepting_orders          courier only
accepting_business        nullable
ui_theme
created_at
last_login
```

### ActiveLoginLease

```text
id
user_id                   unique active
session_key
lease_token_hash
last_seen_at
created_at
expires_at
revoked_at
revoked_by
revoke_reason
```

同一用户最多一个未撤销且未 stale 的 lease。

## 2. Customer

```text
id
wechat_nickname           nullable/推荐
recipient_names           text，可用 / 分隔
phone_suffixes            text，可用 / 分隔
building_id               nullable
floor                     nullable
room                      nullable
long_term_note            nullable
created_by
created_at
updated_at
```

客户历史订单保存快照。

## 3. Agent / ProxyBatch / ProxyRecipient

V1 代理体系只服务 `EXPRESS` 快递。

### Agent

```text
id
name                      必填
contact_text              nullable
note                      nullable
is_active
created_at
```

### ProxyBatch

```text
id
agent_id
batch_date
sequence
status                    OPEN / READY_TO_SETTLE / SETTLED / CANCELED
note
created_by
created_at
ready_at nullable
settled_at nullable
```

ProxyBatch 状态迁移限定为 `OPEN → READY_TO_SETTLE → SETTLED`、`OPEN → CANCELED`、`READY_TO_SETTLE → OPEN`（显式重新打开）和 `SETTLED → READY_TO_SETTLE`（仅误结算撤销）。整批取消不要求先逐单操作：`cancel_proxy_batch()` 在 OPEN 且不存在 PICKED/DELIVERING/DELIVERED 有效快递时，事务内取消仍可取消的 NEW/ASSIGNED 订单、释放未取件 Assignment、重新评估相关 ExpressRound 并最终置批次为 CANCELED。若订单被逐单取消后批次的非取消订单数量变为 0，也应自动将 OPEN 批次置为 CANCELED，而不是进入 READY_TO_SETTLE。

### ProxyRecipient

```text
id
proxy_batch_id
display_name              必填，可自动生成 15号楼#1
recipient_names           nullable
wechat_nickname           nullable
phone_suffixes            nullable
building_id               必填（校园配送时）
floor                     nullable
room                      nullable
note                      nullable
show_price_on_receipt     bool default true
created_at
```

ProxyRecipient 不进入 Customer，不跨批次复用。

## 4. Building

```text
id
code
name
zone                      SOUTH / NORTH
route_order
is_active
```

## 5. Order

```text
id                        BigAutoField
business_type             EXPRESS / TAKEOUT / KFC / GROCERY / ERRAND / LUGGAGE_UPSTAIRS
sequence_date             date
daily_sequence            int
service_date              date nullable   # 全局字段可空；business_type=EXPRESS 时必须非空，默认当前本地日期

source_type               DIRECT / AGENT
customer_id               nullable
proxy_recipient_id        nullable
proxy_batch_id            nullable

delivery_status           NEW / ASSIGNED / PICKED / DELIVERING / DELIVERED / CANCELED
settlement_status         UNSETTLED / WAITING_PAYMENT / SETTLED
is_urgent                 bool
requires_upstairs         bool default false
entry_mode                NORMAL / DIRECT_COMPLETE / HISTORICAL_BACKFILL

destination_type          CAMPUS_BUILDING / OFF_CAMPUS_ADDRESS
building_snapshot         nullable
zone_snapshot             nullable
floor_snapshot            nullable
room_snapshot             nullable
off_campus_address        nullable

recipient_name_snapshot
recipient_phone_snapshot
order_note

created_by
created_at
updated_at
canceled_by
canceled_at
cancel_reason
version
soft_deleted_at
```

约束：

- DIRECT 普通单应有 `customer_id`，且 `proxy_recipient_id/proxy_batch_id` 为空；
- AGENT 代理单应有 `proxy_recipient_id + proxy_batch_id`，且 `customer_id` 为空；
- `source_type=AGENT` 时 `business_type` 必须是 `EXPRESS`；
- `business_type=LUGGAGE_UPSTAIRS` 时 `requires_upstairs=true`；
- `business_type=EXPRESS` 时 `service_date` 必须非空；UI 与后端默认当前本地日期，不使用 sequence_date 隐式兜底；
- 唯一编号约束：`(business_type, sequence_date, daily_sequence)`。

固定展示编号由三元组生成：`{业务代码}-{YYMMDD}-{三位序号}`。动态展示编号额外插入当前状态代码。

## 6. 业务 Detail

### ExpressOrderDetail

```text
order_id one-to-one
express_round_id          FK ExpressRound，创建订单时确定
pickup_area               SOUTH / NORTH / OUTSIDE
outside_pickup_location   OUTSIDE 时必填
pickup_identifier_type    PICKUP_CODE / WAYBILL / OTHER
pickup_identifier         必填自由文本
size_class                UNKNOWN / SMALL / MEDIUM / LARGE / OVERSIZE
dispatch_mode             ROUTE / DIRECT_CUSTOMER

small_price_snapshot      Decimal
medium_price_snapshot     Decimal
large_price_snapshot      Decimal
oversize_price_snapshot   Decimal
```

快递创建时保存完整大小价目快照。已知大小可立即按对应快照创建 BASE_SERVICE；UNKNOWN 暂不创建基础价，配送员确认大小时使用这里保存的订单创建时价格。

### TakeoutOrderDetail

```text
order_id
pickup_gate               SOUTH_GATE / NORTH_GATE / OTHER
other_pickup_location     OTHER 时必填
identifier                必填自由文本
```

### KfcOrderDetail

```text
order_id
pickup_location
pickup_code
```

### GroceryOrderDetail

```text
order_id
pickup_location
item_list                 多行文本
```

### ErrandOrderDetail

```text
order_id
pickup_location
delivery_location_text    跑腿送达地点文本，可与校园楼栋快照并存
item_description
size_class                UNKNOWN / SMALL / MEDIUM / LARGE / OVERSIZE
```

### LuggageUpstairsDetail

```text
order_id
small_medium_count        int >=0
large_oversize_count      int >=0
floor                     positive int
special_pickup_note       nullable
```

## 7. ExpressRound

`ExpressRound` 是快递业务中“某个收件归属的本轮快递”的唯一显式边界。多件优惠、归拢和普通快递按轮结算均引用它，不再根据“当前已录入”或模糊时间窗口推断。

```text
id
recipient_kind            CUSTOMER / PROXY_RECIPIENT
customer_id nullable
proxy_recipient_id nullable
service_date              date
round_no                  int
status                    OPEN / CLOSED
created_at
closed_at nullable
```

核心约束：

- Customer / ProxyRecipient 二选一；
- 新快递加入“同一收件归属 + 相同 service_date + OPEN”的 ExpressRound；没有则创建新 round_no；
- 一个 round CLOSED 后，同一天后续新快递也进入新的 round；
- 不同 service_date 永不互相阻塞；
- round 内不再存在 NEW/ASSIGNED/PICKED/DELIVERING 后：若未取消且已送达数量为 0，则代表全取消并自动 CLOSED；为 1 时直接 CLOSED；>=2 时仅在存在必要归拢候选时等待 ConsolidationRound，若无候选则直接 CLOSED；
- CLOSED round 不再接收新订单，同一 service_date 的后续订单进入新的 round_no。

## 8. DeliveryTask / Assignment

### DeliveryTask

```text
id
task_type                 ROUTE_BATCH / CUSTOMER_DIRECT / SIMPLE
business_type
status                    ACTIVE / COMPLETED / CANCELED
courier_id
created_at
accepted_at
completed_at
```

### RouteBatch

```text
task_id one-to-one
pickup_area               SOUTH / NORTH / OUTSIDE
destination_zone          SOUTH / NORTH / OUTSIDE / MIXED
```

### Assignment

```text
id
order_id
task_id
courier_id
is_active
assigned_at
ended_at
end_reason                COMPLETED / RETURNED / TRANSFERRED / CANCELED
```

数据库约束：同一 order 同时最多一个 active assignment。

## 9. Transfer

```text
TransferRequest
- from_courier
- to_courier
- status
- reason_code / reason_text
- handoff_required
- handoff_location
- created_at / accepted_at

TransferItem
- transfer_id
- order_id
```

## 10. DeliveryDrop

一次真实放置动作。

```text
id
courier_id
recipient_kind            CUSTOMER / PROXY_RECIPIENT
customer_id nullable
proxy_recipient_id nullable
business_type
building_snapshot nullable
location_type             RACK / ROOM / HANDOFF / OTHER
final_location_text       必填（行李当面完成可允许固定值“客户现场确认”）
delivered_at
```

### DeliveryDropItem

```text
drop_id
order_id
```

一个 DeliveryDrop 表示“一次真实放置动作”。同一 Drop 的所有订单必须同时满足：当前配送员拥有有效配送责任、状态允许完成、同一 Customer 或同一 ProxyRecipient、business_type 相同、目的楼栋/实际放置动作兼容、同一 final_location_text 与同一组照片能够真实描述全部物品。不同客户或实际放置位置不同的订单必须拆成不同 DeliveryDrop。

## 11. MediaFile 与配送凭证

### MediaFile

```text
id
storage_key
mime_type
width
height
size_bytes
sha256
variant_type              ORIGINAL_COMPRESSED / THUMBNAIL / ANNOTATED / GENERATED_RECEIPT
parent_media_id nullable
created_at
deleted_at nullable           # 文件清理后保留 metadata
delete_reason nullable
protected_until nullable
```

### DeliveryEvidence

```text
id
drop_id
order_id nullable
media_id
role                      NEAR / FAR / OTHER
annotated_media_id nullable
created_at
```

普通配送至少一条 evidence；行李上楼允许 0 条。

## 12. ConsolidationRound

```text
id
express_round_id          FK ExpressRound
recipient_kind            CUSTOMER / PROXY_RECIPIENT
customer_id nullable
proxy_recipient_id nullable
round_no
status                    PENDING / IN_PROGRESS / COMPLETED
created_mode              AUTO / MANUAL
assigned_courier_id
frozen_at
final_location_text
final_near_media_id
final_far_media_id nullable
final_far_annotated_media_id nullable
started_at
completed_at
```

### ConsolidationItem

```text
round_id
order_id
found_status              PENDING / FOUND / CUSTOMER_TAKEN / EXCEPTION
found_at
```

创建 ConsolidationRound 后成员立即冻结，完成后 items 不允许增删。默认 `assigned_courier_id` 为该归拢成员中最后完成配送的配送员。负责人后续只能通过独立 `reassign_consolidation_round()` 修改并写 AuditEvent；不得修改已完成订单的 Assignment。

## 13. Settlement

```text
id
business_type
party_type                CUSTOMER / AGENT
customer_id nullable
agent_id nullable
proxy_batch_id nullable
status                    DRAFT / WAITING_PAYMENT / SETTLED / VOIDED / REVERSED
created_by
created_at
frozen_at nullable
voided_at nullable
voided_by nullable
void_reason nullable
settled_by nullable
settled_at nullable
reversed_at nullable
amount_due_snapshot       Decimal nullable   # DRAFT 未冻结时为空；冻结后必须 >= 0，0 元允许
```

### SettlementOrder

```text
id
settlement_id
order_id
```

唯一约束：同一 Settlement 内一个 Order 只能出现一次。

SettlementOrder 在 DRAFT 创建时就固定本次准备结算的订单集合。一个 Order 可以保留 VOIDED/REVERSED 的历史 SettlementOrder，但同一时刻最多只能属于一个状态为 DRAFT/WAITING_PAYMENT/SETTLED 的有效 Settlement。VOIDED/REVERSED 不占用订单。该跨表约束由 build service 的事务检查与测试保证。

## 14. ChargeItem 与 SettlementLine

### ChargeItem

ChargeItem 是业务费用来源，可在录单、配送或结算准备阶段创建。`customer_id/proxy_recipient_id/express_round_id` 只用于归属、展示和报表，不作为跨 Settlement 自动拾取费用的依据。

```text
id
scope_type                ORDER / SETTLEMENT
order_id nullable
express_round_id nullable    # 快递轮次归属；快递 WEATHER / MULTI_ITEM_DISCOUNT 必填
customer_id nullable         # 归属维度，不作为费用选择主键
proxy_recipient_id nullable  # 归属维度，不作为费用选择主键
settlement_id nullable       # scope_type=SETTLEMENT 时必填
charge_type               BASE_SERVICE / OFF_CAMPUS_PICKUP / CAMPUS_TO_OFF_CAMPUS /
                          URGENT / WEATHER / UPSTAIRS / CUSTOMER_EXTRA /
                          MANUAL_SURCHARGE / MANUAL_DISCOUNT / MULTI_ITEM_DISCOUNT
label
quantity                   Decimal
unit_price                 Decimal
amount                     signed Decimal
source                     SYSTEM_RULE / USER_ADDED
config_snapshot            text/JSON，仅用于规则快照
beneficiary_type           PLATFORM / COURIER / NONE
beneficiary_courier_id     nullable
status                    ACTIVE / VOIDED
created_by
created_at
voided_at nullable
voided_by nullable
void_reason nullable
```

典型作用域与绑定规则：

- `BASE_SERVICE / OFF_CAMPUS_PICKUP / CAMPUS_TO_OFF_CAMPUS / URGENT / UPSTAIRS`：`scope_type=ORDER`，`order_id` 必填；
- `WEATHER / CUSTOMER_EXTRA / MANUAL_SURCHARGE / MANUAL_DISCOUNT / MULTI_ITEM_DISCOUNT`：在 DRAFT 结算中创建，`scope_type=SETTLEMENT` 且 `settlement_id` 必填；
- 快递 `WEATHER` 与 `MULTI_ITEM_DISCOUNT` 还要保存对应 `express_round_id`；WEATHER 同时保存 Customer/ProxyRecipient 归属；
- 同一个已 VOIDED/历史 Settlement 上的结算级费用项不得被新 Settlement 自动复用，需要时在新的 DRAFT 中重新创建。

冻结某 Settlement 时，只读取：`SettlementOrder.order_id` 对应的 ACTIVE ORDER 费用项，以及 `settlement_id=当前 Settlement` 的 ACTIVE SETTLEMENT 费用项。禁止仅按 Customer/ProxyRecipient/ExpressRound 扫描历史 ChargeItem。

ChargeItem 不允许物理删除。错误/取消费用项通过 `ACTIVE → VOIDED` 逻辑作废，冻结 SettlementLine 时只读取 ACTIVE 项。

`CUSTOMER_EXTRA` 的 `beneficiary_type=COURIER` 且必须有 `beneficiary_courier_id`。若本轮只有一个最终配送员可自动填写；若存在多个最终配送员，录单员必须选择收益人；需要多人分配时创建多条 CUSTOMER_EXTRA。

### SettlementLine

SettlementLine 是 DRAFT Settlement 在“生成有效结算凭证 / 进入待付款”时，从当前 ACTIVE ChargeItem 复制得到的不可变财务快照。`build_settlement()` 本身不创建 SettlementLine。

```text
id
settlement_id
source_charge_item_id        # 必填，ChargeItem 永不物理删除
order_id nullable
customer_id nullable
proxy_recipient_id nullable
express_round_id nullable
charge_type
label
quantity
unit_price
amount
source
config_snapshot
beneficiary_type
beneficiary_courier_id nullable
created_at
```

Settlement 在 DRAFT 阶段的金额仅为“SettlementOrder 对应订单的 ACTIVE ORDER 费用项 + 当前 settlement_id 的 ACTIVE SETTLEMENT 费用项”的实时预览。预览暂时可以小于 0，但 UI 必须警告。冻结时重新校验并要求 `Σ SettlementLine.amount >= 0`；0 元结算允许，负数不得进入 WAITING_PAYMENT。冻结后最终应收只按自身 `SettlementLine.amount` 求和；配置变化、ChargeItem 后续变化、VOID/REVERSE 后再次结算均不得修改旧 SettlementLine。

## 15. SettlementImageVersion / ProxyRecipientReceipt

### SettlementImageVersion

普通客户或代理批次汇总图版本：

```text
id
settlement_id
version_no
media_id
image_type                CUSTOMER_SETTLEMENT / AGENT_SUMMARY
is_active                 bool
created_at
```

Settlement 被撤销后，关联图片保留并标记为历史/已撤销，不覆盖。普通客户结算图、ProxyRecipient 凭证、Agent 汇总图都遵循默认 30 天媒体文件生命周期；清理只删除文件实体，保留 MediaFile/版本元数据。结构化 SettlementLine 永久保留，可重新生成凭证；原配送照片已清理时只能生成不含原照片的历史凭证，并明确提示照片已按保留策略清理。

### ProxyRecipientReceipt

```text
id
proxy_recipient_id
proxy_batch_id
settlement_id nullable
version_no
show_price                bool
media_id
is_active                 bool
created_at
```

## 16. FinancialAdjustment

退款、结算撤销、人工账务修正 append-only。

```text
id
settlement_id
type                      REFUND / DISCOUNT_AFTER_SETTLEMENT / EXTRA_AFTER_SETTLEMENT / SETTLEMENT_REVERSAL
amount                     signed Decimal
reason
impact_wage                bool
wage_courier_id nullable
wage_amount nullable
created_by
created_at
```

## 17. CourierEarning

```text
id
earning_key               unique，service 生成的确定性幂等键
order_id nullable          # 业务收益通常有 Order；纯工资调整可空
settlement_id nullable
source_charge_item_id nullable
courier_id
source_type               BASE_DELIVERY / UPSTAIRS / CUSTOMER_EXTRA / MANUAL_EXTRA / WAGE_ADJUSTMENT
amount_base               Decimal nullable
commission_rate_snapshot  Decimal nullable
suggested_wage_amount     Decimal nullable
status                    PENDING_PAYMENT / SETTLED / REVERSED
created_at
```

CourierEarning 按收益来源拆行，正常业务收益的粒度为“Settlement × Order（如适用）× Courier × source/source ChargeItem”，而不是把一个订单所有收益混成一条。配送完成时创建 BASE_DELIVERY `PENDING_PAYMENT` 归属记录，`settlement_id=NULL`；结算确认时按 SettlementLine/ChargeItem 来源生成或完成 UPSTAIRS、CUSTOMER_EXTRA、MANUAL_EXTRA 等收益行。

`earning_key` 必须是确定性的，避免 SQLite nullable UNIQUE 语义导致重复。例如基础归属可使用 `base:{order_id}:{courier_id}:initial`；结算派生可包含 settlement/order/charge_item/courier。Settlement 撤销时原记录转为 REVERSED；再次结算创建新 CourierEarning，不复用旧记录。

## 18. WageCalculationSnapshot（可选但建议）

工资计算器不表示“已发工资”，但可保存一次计算结果便于复核：

```text
id
period_start / period_end
mode                      RATIO / MANUAL
available_pool_snapshot
locked_amount_snapshot
allocatable_remaining_snapshot
total_allocated
created_by
created_at
```

明细表记录每个成员建议/手工金额，其中强制归属费用（如 CUSTOMER_EXTRA）单独记录为 locked amount。

## 19. 异常、图片保护、审计与运维

### ExceptionCase

```text
id
status                    OPEN / RESOLVED
order_id nullable
task_id nullable
drop_id nullable
consolidation_round_id nullable
reason_code
reason_text
blocks_consolidation      bool
blocks_settlement         bool
created_by
created_at
resolved_by nullable
resolved_at nullable
resolution_text nullable
```

### ExceptionCaseAttachment

异常直接上传图片：

```text
id
exception_case_id
media_id
created_at
```

### ExceptionEvidenceLink

异常引用已有配送/归拢证据：

```text
id
exception_case_id
delivery_evidence_id nullable
media_id nullable       # 归拢最终图等不经过 DeliveryEvidence 时可直接引用
created_at
```

OPEN 异常直接或间接关联到的 MediaFile 受到清理保护。创建异常时可按 reason_code 给出 `blocks_consolidation / blocks_settlement` 默认值，但实际流程统一读取这两个显式字段；特殊情况修改阻塞属性必须写 AuditEvent。

### AuditEvent

Append-only：actor、event_type、entity_type/id、diff/metadata、created_at。

### BackupRecord

备份路径、DB/配置/照片归档状态、大小、类型（AUTO/MANUAL/PRE_RESTORE）、时间。

### JobRun

scheduler job 的幂等执行与结果记录。

### MaintenanceState

单例配置：是否维护、进入时间、操作者、原因。

## 20. 不建立的模型

V1 不建立：

- BusinessDay；
- ExpressDailyDiscount；
- 每日经营汇总真值表；
- 客户合并关系；
- 商品采购账务；
- 站内通知；
- GPS/地图实体。

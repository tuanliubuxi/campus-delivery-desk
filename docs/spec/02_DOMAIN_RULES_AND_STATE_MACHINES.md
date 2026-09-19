# 02. 领域规则与状态机

## 1. 总体原则

- 状态只描述现实已发生动作。
- 服务器重启不得回退实物状态。
- 异常独立于主状态。
- 历史通过追加事件修正，不做无痕覆盖。
- 金额变化通过 ChargeItem/FinancialAdjustment 表达。
- Settlement 只读取冻结后的 SettlementLine 作为本次结算金额事实。

## 2. 订单编号

固定用户可见编号：

```text
业务类型字母-YYMMDD-三位序号
```

动态展示编号：

```text
业务类型字母-当前状态字母-YYMMDD-三位序号
```

业务字母：

- `P` 快递 Parcel
- `F` 外卖 Food
- `K` KFC
- `G` 果蔬 Grocery
- `E` 跑腿 Errand
- `L` 行李上楼 Luggage-upstairs

状态字母：

- `N` 待接单
- `A` 已接单/待取
- `P` 已取到
- `D` 配送中
- `V` 已送达/待结算
- `S` 已结算
- `C` 已取消

例如固定编号 `K-260829-023` 与动态编号 `K-V-260829-023` 指向同一订单。

异常只显示 Badge，不改变编号状态字母。真正固定身份由 `(business_type, sequence_date, daily_sequence)` + DB 主键构成。搜索必须同时支持固定编号和动态展示编号。

## 3. 公共配送状态

```text
NEW
→ ASSIGNED
→ PICKED
→ DELIVERING
→ DELIVERED
```

订单配送状态与结算状态分开保存。

结算状态：

```text
UNSETTLED → WAITING_PAYMENT → SETTLED
```

DRAFT Settlement 不改变 Order 的结算状态。只有生成有效结算凭证并冻结 SettlementLine 时，相关 Order 才从 `UNSETTLED` 进入 `WAITING_PAYMENT`。付款前账单被 VOIDED 时，相关 Order 回到 `UNSETTLED`。已确认付款后的误结算使用 REVERSED 流程，原 Settlement 和原收益记录保留为历史。

### 取消

- NEW：可取消；
- ASSIGNED 且未取：可取消；
- PICKED 以后：不能普通取消，走人工处理；
- DELIVERED 后：不能普通取消。

## 4. 快递状态、大小与上楼要求

### ASSIGNED → PICKED

`PICKED` 是实物责任分界线：

- 不得退公共池；
- 转单必须实物交接；
- 客户不要了走人工处理；
- 重启后仍保持 PICKED。

### 大小 UNKNOWN

快递可在录单时 UNKNOWN。订单创建时必须保存当时完整的快递大小价格快照。最终配送员接触实物后确认实际大小等级，并按订单创建时的对应档位价格生成 BASE_SERVICE 费用项；未确认不能最终结算。

### 是否上楼

订单使用显式 `requires_upstairs` 字段表达本单是否要求收费上楼。楼层/房间只是地址快照，不能用于推断是否上楼；最终 `DeliveryDrop.location_type` 也不能替代该字段。

行李搬上楼业务始终 `requires_upstairs=true`。

## 5. 快递路线池

路线接单按：

```text
pickup_area + destination_scope/zone
```

取件区域：SOUTH / NORTH / OUTSIDE。

OUTSIDE 路线可以把多个相近校外站点放在同一个池里，但每个订单仍保留具体取件地点。

目的地：校园楼栋（自动得到 SOUTH/NORTH）或 OFF_CAMPUS_ADDRESS。

校内送校外属于低频场景，任务卡必须突出详细地址；可以进入普通调度，但不得丢失地址信息。

### 动态组批

配送员从路线池勾选若干订单后确认接取。勾选期间不锁单，确认时服务器原子处理，允许部分成功。

推荐排序：加急 → 等待时间 → 楼栋集中。

不做地图路线算法。

## 6. 客户直送

快递可通过客户直送处理急件。同一个实际客户或 ProxyRecipient 当前未接单的快递可以组成直送任务。

已经被其他配送员接走的件不自动抢回，只高亮加急；需要换人走转单。

## 7. 配送员业务类型限制

- 同一时间只允许一个活跃业务类型。
- 同业务可有多个活跃批次/任务。
- 完成或转走当前业务全部任务后才能切业务。
- 接单开关只影响是否接新任务，不影响已有任务。

## 8. 取件与配送

快递批次每件单独确认取件。

批次状态由成员汇总，例如：

```text
取件中 3/8
已取 7/8，异常 1
```

开始配送只把已 PICKED 的订单改成 DELIVERING，异常/未取件不阻塞其他物件。

配送阶段按：

```text
楼栋 → 收件归属（Customer/ProxyRecipient）→ 单件
```

同一归属连续配送时，上一件位置可作为下一件建议值。

## 9. 简单业务

外卖、KFC、果蔬、跑腿、行李上楼复用简单配送骨架：

```text
NEW → ASSIGNED → PICKED → DELIVERING → DELIVERED
```

其中行李上楼可视为“接到任务 → 开始服务 → 完成”，UI 可以简化，但底层仍保持可审计状态。

## 10. 转单

### 未取件

允许退池或转给指定配送员。

### 已取件

必须：发起 → 填交接地点/原因 → 接收人实际拿到 → 接收确认 → assignment 切换。

### 已完成

不能转单，有问题走异常/重新配送。

## 11. 配送完成与照片

普通配送：至少一张照片 + 最终位置。

推荐：

1. 近距离物件照片；
2. 远距离环境照片；
3. 远景可生成标注派生图（圈/箭头）。

第二张照片和标注不阻塞完成。

行李上楼照片可选。

配送完成时创建 `PENDING_PAYMENT` CourierEarning 基础记录，用于固定收益归属；此时 `settlement_id` 为空，金额允许待结算后最终确定。

## 12. 快递轮次与归拢

### ExpressRound：明确“本轮快递”

快递不得再通过“当前已录入”“某个时间窗口”等隐式方式猜测轮次。每个 EXPRESS 订单必须属于一个 `ExpressRound`：

```text
Customer / ProxyRecipient
        ↓
ExpressRound
        ↓
Express Orders
```

EXPRESS 的 `service_date` 必须非空；录单 UI 与后端默认当前本地日期，提前录未来快递时才修改。录单时优先查找“同一收件归属 + 相同 service_date + OPEN”的 ExpressRound；存在则加入，不存在则创建新轮。一个 ExpressRound 关闭后，之后新录入的快递即使 service_date 相同，也进入新的 round_no。

ExpressRound 的关闭判定先确认不存在 `NEW/ASSIGNED/PICKED/DELIVERING` 的有效快递，再统计“未取消且已 DELIVERED”的数量：

- `0` 件：说明本轮全部订单都已取消，立即自动 `CLOSED`，不创建 ConsolidationRound；
- `1` 件：无需归拢，立即 `CLOSED`；
- `>=2` 件：计算归拢候选；若没有任何需要归拢的候选（例如均为上楼/当面交付），直接 `CLOSED`；若存在必要归拢，则创建/完成对应 ConsolidationRound，全部必要归拢完成后再 `CLOSED`；
- 只要仍有 NEW/ASSIGNED/PICKED/DELIVERING 的有效快递，保持 OPEN。

不同 service_date 的快递永远属于不同 ExpressRound，因此明天的 NEW 快递不会阻塞今天的归拢。

### ConsolidationRound

归拢对象不是“账号”，而是收件归属：

- 普通单：Customer；
- 代理单：ProxyRecipient。

进入自动归拢候选的快递必须同时满足：

- `business_type=EXPRESS`；
- `delivery_status=DELIVERED`；
- 属于同一 ExpressRound；
- 尚未加入其他 ConsolidationRound；
- 不是客户已经自行取走的物件；
- 不是送上楼或当面交付完成的物件；
- 不存在 `OPEN && blocks_consolidation=true` 的异常。

录单员/管理员可以对已经送达的合格子集手动提前创建 ConsolidationRound。ConsolidationRound 创建后成员立即冻结；同一 ExpressRound 后续仍可能对剩余合格物件建立新的 ConsolidationRound，直到该 ExpressRound 的必要归拢全部完成。

默认归拢负责人为对应归拢成员中最后一个完成配送的配送员。负责人调整不能复用普通 Order Transfer，必须调用独立 `reassign_consolidation_round(round, new_courier, reason)`：只改变归拢负责人并记录原负责人、新负责人、原因、操作者和 AuditEvent，不改变已经 DELIVERED 订单的 Assignment。

流程：找件 → FOUND/人工处置 → 放一堆 → 最终近景/位置（推荐远景标注）→ 完成。

## 13. 代理单与 ProxyBatch 状态

V1 的 Agent / ProxyBatch / ProxyRecipient 仅用于 `EXPRESS` 快递业务。其他业务类型不得使用 `source_type=AGENT`。

```text
Agent
→ ProxyBatch
→ ProxyRecipient
→ Express Orders
```

ProxyRecipient 生命周期只在当前批次内。配送、归拢、照片按 ProxyRecipient；财务由 Agent 与平台结算。客户凭证与代理汇总图是两个不同输出。

ProxyBatch 状态：

```text
OPEN → READY_TO_SETTLE → SETTLED
OPEN → CANCELED
READY_TO_SETTLE → OPEN          # 录单员/管理员显式重新打开
SETTLED → READY_TO_SETTLE       # 仅误结算撤销
```

`OPEN`：允许新增 ProxyRecipient 和快递。

进入 `READY_TO_SETTLE` 前必须至少存在 1 个非取消快递。若批次所有订单都已逐单取消，则 OPEN 批次应自动转 `CANCELED`，不得因空集合条件进入 READY_TO_SETTLE。

存在至少 1 个非取消快递时，进入 `READY_TO_SETTLE` 必须同时满足：

- 所有非取消快递都已完成配送；
- 需要归拢的轮次均已完成；
- 所有 UNKNOWN 大小都已确认；
- 不存在 `OPEN && blocks_settlement=true` 的异常；
- 所有费用均可完整计算。

只要还有待接单、待取、已取、配送中、待归拢、价格未知或 `blocks_settlement=true` 的 OPEN 异常，就不能 READY。

满足条件后系统可自动重新计算并进入 `READY_TO_SETTLE`。生成客户凭证或 Agent 汇总图本身不改变批次状态。

`READY_TO_SETTLE` 默认冻结批次成员。需要补录遗漏订单时，录单员/管理员必须执行“重新打开批次”，状态回到 OPEN，已生成但尚未结算的汇总图失效并写 AuditEvent。

`SETTLED` 后禁止追加 ProxyRecipient 或订单。新的快递必须建立新的 ProxyBatch。

整批 `CANCELED` 通过 `cancel_proxy_batch()` 完成，采用原子事务，不要求先逐单取消。仅 `OPEN` 批次且批次内不存在 `PICKED / DELIVERING / DELIVERED` 的有效快递时允许：系统自动将仍为 `NEW / ASSIGNED` 的非取消订单按“批次取消”原因取消，释放对应未取件 Assignment/任务占用，随后逐个重新评估相关 ExpressRound；因此变成全部取消的轮次应自动 `CLOSED`；最后把 ProxyBatch 置为 `CANCELED` 并写 AuditEvent。

如果批次中任意有效快递已经 `PICKED / DELIVERING / DELIVERED`，整批取消必须拒绝。录单员仍可逐单取消尚未取件的订单；已经拿到实物或已完成的订单只能走正常配送、异常或人工处理，批次继续按剩余有效订单推进。`READY_TO_SETTLE` 不允许转 `CANCELED`。

## 14. Settlement 生命周期与费用冻结

Settlement 状态：

```text
DRAFT → WAITING_PAYMENT → SETTLED
DRAFT → VOIDED
WAITING_PAYMENT → VOIDED
SETTLED → REVERSED
```

`build_settlement()` 只完成两件事：创建 DRAFT Settlement，并通过 SettlementOrder 固定本轮订单集合。DRAFT 阶段允许继续新增、作废当前 Settlement 的结算级 ChargeItem；页面金额只按 SettlementOrder 对应订单的 ACTIVE ORDER 费用项 + 当前 settlement_id 的 ACTIVE SETTLEMENT 费用项实时预览，不按收件人历史扫描，此时不生成 SettlementLine，Order 仍保持 UNSETTLED。UNKNOWN 快递允许存在于 DRAFT。

当录单员执行“生成有效结算凭证 / 进入待付款”时，在一个事务中：

1. 校验 Settlement 仍为 DRAFT、订单仍允许结算；
2. 只收集两类 ACTIVE 费用项：SettlementOrder 对应订单的订单级 ChargeItem，以及 `settlement_id=当前 Settlement` 的结算级 ChargeItem；不得按 Customer/ProxyRecipient 扫描历史费用项；
3. 重新校验所有 EXPRESS 已确认大小、无阻塞结算异常，并逐项复制为不可变 SettlementLine；
4. `Settlement.amount_due_snapshot = Σ SettlementLine.amount`，且必须 `>= 0`；0 元允许，负数拒绝冻结；
5. 生成有效凭证；
6. Settlement → WAITING_PAYMENT；
7. 所有 SettlementOrder 对应 Order：UNSETTLED → WAITING_PAYMENT。

从冻结时点起，历史金额只按 SettlementLine 读取，不能修改 SettlementLine，也不能通过修改原 ChargeItem 改写该账单。

DRAFT 或尚未付款的 WAITING_PAYMENT 如金额有误/放弃，整份 Settlement 标记 VOIDED。若已经进入 WAITING_PAYMENT，则其 Order 回到 UNSETTLED，已生成凭证标记无效/历史；需要结算时重新创建新的 DRAFT。

## 15. 结算撤销与退款

已确认付款后的误结算采用“保留旧记录 + 反向记录 + 新结算”的方式：

- 原 Settlement：`SETTLED → REVERSED`；
- 创建 `FinancialAdjustment(type=SETTLEMENT_REVERSAL)`；
- 相关 Order：`SETTLED → UNSETTLED`，重新建立 DRAFT 后仍保持 UNSETTLED，直到新的有效凭证冻结时再进入 WAITING_PAYMENT；
- 原 CourierEarning：`SETTLED → REVERSED`；
- 原结算图片保留并标记为已撤销历史版本。

再次结算必须创建新的 Settlement、新的 SettlementLine、新的 CourierEarning 和新的图片版本，不复用或覆盖原记录。

真实付款后的退款不是 Settlement Undo，使用退款/FinancialAdjustment 流程处理。

ProxyBatch 的已结算批次在误结算撤销后回到 `READY_TO_SETTLE`。

## 16. 费用项、天气与优惠

ChargeItem 是业务费用来源，采用：

```text
ACTIVE → VOIDED
```

录错、取消或替换费用项时只做逻辑作废，保存 `voided_at / voided_by / void_reason`，禁止物理删除。冻结 SettlementLine 时只读取 ACTIVE ChargeItem。

多件快递优惠只针对当前 ExpressRound/结算轮，并在 DRAFT 中作为 `settlement_id=当前 Settlement` 且记录对应 `express_round_id` 的结算级 ChargeItem：

```text
max(parcel_count - 5, 0) × 0.5
```

默认不应用，由录单员结算时勾选。

特殊天气费按“一个收件归属的一次结算轮”计一次，默认 +2 元。它必须作为当前 DRAFT Settlement 的结算级 ChargeItem 保存 `settlement_id`；快递场景同时保存对应 `express_round_id`：

- 普通客户：每个 Customer 当前 Settlement round 一次；
- 代理单：每个 ProxyRecipient 当前 round 一次；
- 简单业务通常一单就是一个 round。

特殊天气只在 DRAFT 结算阶段人工勾选，不自动判断。

`CUSTOMER_EXTRA` 必须明确 `beneficiary_courier_id`。若本轮只有一个最终配送员，可以自动选择；若涉及多个最终配送员，录单员必须选择收益人。需要给多人加价时拆成多条 CUSTOMER_EXTRA，不做自动平均。

## 17. 收益归属与工资基础

- 基础配送收益归最终完成人。
- 甲取件后转乙、乙送达：基础收益归乙。
- `CUSTOMER_EXTRA` 100% 锁定归费用项指定的 beneficiary courier，不参与人工重新分配。
- 归拢只统计工作量，不自动产生收益。
- 退款是否影响工资由人工处理时明确选择。

CourierEarning 按收益来源拆行，而不是一个订单只保留一个混合总额。常见来源包括 BASE_DELIVERY、UPSTAIRS、CUSTOMER_EXTRA、MANUAL_EXTRA。配送完成时先创建确定性的 BASE_DELIVERY `PENDING_PAYMENT` 归属记录；结算确认时为最终费用来源生成/完成对应收益行。

每条收益使用确定性的 `earning_key` 保证幂等。结算派生收益至少能够唯一对应 Settlement、Order（如适用）、Courier、source type 和 source ChargeItem；不得因重复 confirm 生成重复收益。

CourierEarning 生命周期：

```text
PENDING_PAYMENT → SETTLED
SETTLED → REVERSED
```

配送完成时的基础归属记录允许 `settlement_id=NULL`；确认客户结算时绑定 Settlement、写入最终金额并进入 SETTLED。

## 18. BusinessDay 不属于 V1

V1 不使用快递业务日 OPEN/CLOSED、22:00 收工或每日优惠返还。

`service_date` 仅表示计划/归属日期，用于提前录第二天订单和筛选，不产生“封账状态”。

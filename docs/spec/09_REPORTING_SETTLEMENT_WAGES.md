# 09. 价格、结算、经营分析与工资

## 1. ChargeItem、DRAFT 与 SettlementLine

ChargeItem 是业务费用来源，采用 `ACTIVE / VOIDED`，错误费用项逻辑作废而不物理删除。

建立 DRAFT Settlement 时，只通过 SettlementOrder 固定本轮订单集合；此时仍可添加/作废结算相关 ChargeItem，页面金额是 ACTIVE ChargeItem 的实时预览，不形成历史财务事实。

生成有效结算凭证/进入 WAITING_PAYMENT 时，才将“SettlementOrder 对应订单的 ACTIVE ORDER 费用项 + `settlement_id=当前 Settlement` 的 ACTIVE SETTLEMENT 费用项”复制为不可变 SettlementLine，并冻结。Customer/ProxyRecipient/ExpressRound 仅作为归属维度，不能用于跨 Settlement 扫描历史费用：

```text
Settlement.amount_due_snapshot = Σ SettlementLine.amount
```

冻结时 `amount_due_snapshot` 必须 `>= 0`；0 元允许，负数拒绝冻结。DRAFT preview 可以暂时小于 0，但必须提示录单员修正费用项。禁止直接覆盖总价，也禁止冻结后的 Settlement 通过实时查询 ChargeItem 改变历史金额。

固定费用类型：BASE_SERVICE、OFF_CAMPUS_PICKUP、CAMPUS_TO_OFF_CAMPUS、URGENT、WEATHER、UPSTAIRS、CUSTOMER_EXTRA、MANUAL_SURCHARGE、MANUAL_DISCOUNT、MULTI_ITEM_DISCOUNT。

## 2. 默认价格

### 快递

- UNKNOWN：待确认
- 小 2
- 中 4
- 大 6
- 超大 8
- 校外取件 +1/件
- 校内送校外 +2/件

快递订单创建时保存四档价格快照。UNKNOWN 后续确认大小时使用订单创建时对应档位价格。

### 外卖

基础 3/单。

### KFC

基础 10/单，默认周四开放。

### 果蔬

配送 5/单，商品金额不入账。

### 跑腿

3 元起，特殊距离/大小通过手工费用项。

### 行李搬上楼/快递上楼

小/中：0.5 元/层/件；大/超大：1 元/层/件，从 1 楼算。

## 3. 加急

| 业务 | 默认 |
|---|---:|
| 快递 | +1/件 |
| 外卖 | +2/单 |
| KFC | +5/单 |
| 果蔬 | +2/单 |
| 跑腿 | +2/单 |
| 行李上楼 | 不支持 |

## 4. 特殊天气

结算时人工勾选，无天气 API。

计费单位为“一个收件归属的一次结算轮”，默认 +2 元。费用项在 DRAFT 中创建并绑定当前 `settlement_id`；快递场景同时记录对应 `express_round_id`：

- 普通 Customer：当前 Settlement round 一次；
- ProxyRecipient：当前 round 一次；
- 简单业务通常一单即一 round。

同一个 Agent 批次中的不同 ProxyRecipient 分别判断和计费。

## 5. 多件优惠

只对一个收件归属的当前快递结算轮可选应用：

```text
优惠金额 = max(本轮件数 - 5, 0) × 0.5
```

以负 ChargeItem 记录，不跨轮累计。该项在 DRAFT 中绑定当前 `settlement_id` 与对应 `express_round_id`，不得被后续 Settlement 自动复用。

## 6. 客户自愿加价

固定费用类型 `CUSTOMER_EXTRA`。每一条必须明确 `beneficiary_courier_id`，100% 强制归该配送员，属于 locked earning，不允许在手工工资模式中转给其他成员。

本轮只有一个最终配送员时可以自动选择；存在多个最终配送员时，录单员必须选择。若客户明确给多名配送员加价，则创建多条 CUSTOMER_EXTRA，分别指定 beneficiary，不自动平均。

## 7. 普通客户结算图

显示：客户/楼栋、近景或归拢合照、可选远景标注、最终位置、件数、SettlementLine 费用明细、应付、完成时间。

不显示配送员姓名、内部任务、内部备注。

## 8. 代理结算

V1 代理体系仅用于快递。

### ProxyRecipient 客户凭证

每个临时收件人一张，供 Agent 转发给自己的客户。

`show_price=true` 默认显示该 ProxyRecipient 在本轮中的我方价格；关闭后只显示配送信息/位置/件数/时间，不显示价格。

### Agent 汇总图

无照片，列每个临时收件人、件数、对应 SettlementLine 汇总和批次总额。Agent 与平台按该图结算。

生成客户凭证/汇总图不改变 ProxyBatch 状态。

## 9. Settlement 生命周期

```text
DRAFT → WAITING_PAYMENT → SETTLED
DRAFT → VOIDED
WAITING_PAYMENT → VOIDED
SETTLED → REVERSED
```

DRAFT 只固定订单集合并允许费用编辑，不生成 SettlementLine，Order 仍是 UNSETTLED。

生成有效结算图片时，在同一事务冻结 ACTIVE ChargeItem → SettlementLine，并使 Settlement 与所有对应 Order 一起进入 WAITING_PAYMENT。

DRAFT 或尚未付款的 WAITING_PAYMENT 账单如有错误/放弃，标记 VOIDED；WAITING_PAYMENT 被 VOID 后对应 Order 回 UNSETTLED，凭证标记无效。重新结算新建 DRAFT，不修改旧 SettlementLine。

收到钱后确认 SETTLED。已确认付款的误结算使用 REVERSED；相关 Order 回 UNSETTLED，原 Settlement、SettlementLine、CourierEarning、图片保留为历史，再次结算创建新记录，直到新凭证冻结时 Order 才再次进入 WAITING_PAYMENT。真实退款使用 FinancialAdjustment，不把原历史账单改写。

## 10. 配送员收益

基础收益归最终完成人。CourierEarning 按收益来源拆行，而不是把 BASE_DELIVERY、UPSTAIRS、CUSTOMER_EXTRA、MANUAL_EXTRA 混成一条。

配送完成时先建立：

```text
source_type = BASE_DELIVERY
status = PENDING_PAYMENT
settlement_id = NULL
earning_key = 确定性唯一键
```

用于固定基础收益归属。

结算确认后，根据最终 SettlementLine/ChargeItem 来源，为每个对应配送员生成或完成独立收益行，绑定 Settlement 并转为 SETTLED。`CUSTOMER_EXTRA` 按其 beneficiary_courier_id 100% 归属。

`earning_key` 必须保证重复 confirm、重试请求不会生成重复收益。结算撤销后原收益转为 REVERSED；再次结算创建新的收益记录。

退款是否影响工资由人工处理时指定。

## 11. 工资计算器

### 可分配池定义

`available_pool` 是所选统计周期内已经完成客户/代理结算的净服务营业收入：

- 包含已 SETTLED 的服务费和有效增费；
- 扣除影响计薪的退款/减免；
- 不包含 WAITING_PAYMENT；
- 不包含商品采购款；
- 不包含 REVERSED 结算/收益。

它不是“比例模式算出的建议工资合计”，也不以 CourierEarning 建议分成结果作为上限。

### 强制归属收益

例如 CUSTOMER_EXTRA 100% 属于费用项指定的 beneficiary courier，先从 available_pool 中锁定：

```text
available_pool = 900
locked_amount = 20
manual_allocatable_remaining = 880
```

### 比例模式

普通业务收益按业务分成配置和快照计算；强制归属收益直接加入对应人员，不乘普通业务分成。

### 手工模式

管理员输入每人金额，但只能分配 `manual_allocatable_remaining`。强制归属金额自动附加到对应成员且不可改给别人。

硬约束：

```text
Σ人工可分配金额 <= manual_allocatable_remaining
```

个人最终工资 > 个人直接产生的普通配送收益只软提醒。

工具不管理“工资已发放”。可保存/导出计算快照用于复核。

## 12. 结算凭证图片生命周期

普通客户结算图、ProxyRecipient 凭证、Agent 汇总图默认都执行 30 天媒体保留策略。删除文件不删除 Settlement/SettlementLine/图片版本 metadata。Agent 汇总图可结构化重建；包含配送照片的凭证在原照片已清理后只能重建为无照片历史凭证，并明确提示照片已清理。

## 13. 经营分析统一筛选器

建议维度：

- 时间；
- 业务类型；
- 成员；
- 普通/代理；
- Agent；
- pickup_area；
- destination zone/scope；
- 路线；
- 快递大小；
- 是否加急；
- `requires_upstairs`；
- 是否天气费；
- settlement status；
- 是否异常/退款；
- charge type；
- 路线配送/客户直送。

## 14. Dashboard 指标

订单数、物件数、已结算收入、待收款、退款/减免、附加费用、平均客单价、异常数、配送员收益。

图表：收入趋势、订单量趋势、业务收入构成、成员贡献、快递大小分布、路线分布、楼栋分布、费用项构成、普通/代理占比等。

## 15. 实时计算

V1 不保存“每日经营汇总真值”。需要报表时实时查询事实表。若未来性能确实不足，再引入缓存/汇总表。

## 16. Excel

导出继承当前筛选条件，至少包含订单明细、费用项明细、SettlementLine、结算/退款、配送员收益和代理维度（若适用）。

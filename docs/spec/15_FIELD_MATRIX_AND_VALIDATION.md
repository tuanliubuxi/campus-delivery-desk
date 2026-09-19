# 15. 字段矩阵与校验

## 1. Customer

| 字段 | 创建 | 说明 |
|---|---|---|
| 微信昵称/显示名 | 至少一个可识别名称 | 可空其一 |
| 收件人名称 | 可空 | 文本，允许 `/` |
| 手机尾号 | 可空 | 文本，允许 `/` |
| 楼栋 | 可空 | 真正配送时补 |
| 楼层 | 可空 | 上楼时必填 |
| 房间 | 可空 | 上楼时必填 |
| 长期备注 | 可空 | |

## 2. ProxyRecipient

| 字段 | 必填 | 说明 |
|---|---:|---|
| display_name | 是 | 可自动生成 |
| ProxyBatch | 是 | |
| 楼栋 | 校园配送时是 | |
| 收件人/昵称/尾号 | 否 | 临时信息 |
| 楼层/房间 | 上楼时是 | |
| show_price_on_receipt | 是 | 默认 true |

## 3. 所有订单公共字段

- 收件归属：普通 Customer 或 ProxyRecipient 二选一；ProxyRecipient 仅允许 EXPRESS；
- 业务类型；
- service_date：EXPRESS 必填，UI 与后端默认当前本地日期；其他业务可选；
- 目的地；
- `requires_upstairs` 明确布尔值；
- `requires_upstairs=true` 时原则上楼栋、楼层、房间必填；`LUGGAGE_UPSTAIRS` 为业务例外，房间可空；
- 本单备注；
- 加急（行李业务禁止）。

## 4. 快递

| 字段 | 必填 | 规则 |
|---|---:|---|
| pickup_area | 是 | SOUTH/NORTH/OUTSIDE |
| outside_pickup_location | 条件 | OUTSIDE 时必填 |
| pickup_identifier_type | 是 | 取件码/运单号/其他 |
| pickup_identifier | 是 | max 128/255 |
| size_class | 是 | UNKNOWN 允许 |
| dispatch_mode | 是 | ROUTE/DIRECT_CUSTOMER |
| 目的楼栋或校外地址 | 是 | 校内/校外二选一 |
| off_campus_address | 条件 | 送校外时必填 |

UNKNOWN 在 Settlement 前必须被配送员确认。ExpressOrderDetail 必须在订单创建时保存 SMALL/MEDIUM/LARGE/OVERSIZE 四档价格快照，确认大小时使用该快照。

## 5. 外卖

- pickup_gate 必填；
- OTHER 时具体地点必填；
- identifier 必填；
- 目的地必填。

## 6. KFC

- pickup_location 必填；
- pickup_code 必填；
- 目的地必填；
- 非周四仅提示，不阻止。

## 7. 果蔬

- pickup_location 必填；
- item_list 必填；
- 商品金额字段不存在。

## 8. 跑腿

- pickup_location 必填；
- delivery_location_text/目的地必填；
- item_description 必填；
- size_class 可 UNKNOWN；
- 额外距离费用不直接改总价，添加 MANUAL_SURCHARGE。

## 9. 行李搬上楼

- 楼栋、楼层必填，房间可空；
- 小/中件数量与大/超大件数量至少一类 >0；
- 不允许加急；
- 照片可空；
- 若需从其他地点取行李，写备注并结算加费用项。

## 10. 配送完成

普通业务：至少 1 张照片 + final_location_text。

第二张远景和标注可空。

行李：照片可空；final_location_text 可自动为“客户现场确认/送至X楼X室”，但必须有可读值。

一个 DeliveryDrop 包含多个订单时，必须为同一 Customer/ProxyRecipient、同业务类型、同一配送员有效责任、允许完成状态，且目的地/实际放置动作/位置文字/照片全部兼容；否则必须拆 Drop。

## 11. 归拢

- 所有 item FOUND/人工处置；
- final near photo 必填；
- final location 必填；
- far/annotated 可空。

## 12. ChargeItem / Settlement

金额 Decimal，两位小数。除负向类型外不允许负数。

ChargeItem `status` 必须为 ACTIVE/VOIDED；不允许物理删除。VOIDED 必须记录 voided_at、voided_by、void_reason。Settlement DRAFT 预览和 freeze 都只读取 ACTIVE 项。

CUSTOMER_EXTRA、MANUAL_SURCHARGE、MANUAL_DISCOUNT 要求 label/理由可读。CUSTOMER_EXTRA 必须指定 beneficiary_courier_id；本轮有多个最终配送员时 UI 不得自动猜，需选择；多人受益时拆成多条。

WEATHER 在 DRAFT 结算时可选，按一个 Customer/ProxyRecipient 的当前结算轮计一次；CUSTOMER_EXTRA、WEATHER、MANUAL_SURCHARGE、MANUAL_DISCOUNT、MULTI_ITEM_DISCOUNT 等结算时费用必须绑定当前 `settlement_id`。快递 WEATHER/MULTI_ITEM_DISCOUNT 同时记录对应 `express_round_id`；MULTI_ITEM_DISCOUNT 只在快递且当前 ExpressRound 数量 >5 时可选。

DRAFT Settlement 本身不产生 SettlementLine；preview 只读取 SettlementOrder 对应订单的 ACTIVE ORDER 费用项 + 当前 settlement_id 的 ACTIVE SETTLEMENT 费用项。正式生成有效结算凭证时必须重新校验 UNKNOWN/阻塞异常，并 freeze 为 SettlementLine，同时将相关 Order 置 WAITING_PAYMENT。冻结总额必须 >=0；0 元允许，负数拒绝。

## 13. 代理凭证

ProxyRecipientReceipt `show_price` 默认 true；false 时模板不得渲染任何我方价格/总价。

## 14. 快速完成

DIRECT_COMPLETE：关键业务字段、实际配送员、完成时间、最终位置；普通配送图片仍必填，行李可选。

HISTORICAL_BACKFILL：照片允许为空但补录说明必填。

## 15. 搜索

订单号固定格式 `{业务代码}-{YYMMDD}-{三位序号}`，动态展示格式 `{业务代码}-{状态代码}-{YYMMDD}-{三位序号}`；搜索同时支持两种格式。Customer 的名称/尾号字段搜索时支持 `/` 分隔 token。pickup_identifier 原值保留，同时保存/计算 normalized 版本用于查重。

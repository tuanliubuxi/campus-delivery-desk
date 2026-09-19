# 10. 自动测试与验收清单

本文件既是测试规范，也是编码 AI 的验收标准。任何 Phase 完成前，相关测试必须通过。

## 1. 登录与单会话

1. 同一账号首次登录成功并创建 ActiveLoginLease。
2. fresh lease 存在时，第二浏览器登录被拒绝。
3. 心跳持续刷新 `last_seen_at`。
4. 超过 stale timeout 后，新浏览器可登录，旧租约失效。
5. 管理员强制下线后，旧 Session 不能继续写操作。
6. 多标签共享同一 Session 不造成“多会话”误判。
7. 停用账号/重置密码后旧 Session 失效。

## 2. 客户与代理

### 普通客户

- 客户仅填写最少字段可以创建。
- `/` 分隔的多个收件人名称/手机尾号可被搜索。
- 修改客户后历史订单快照不变。
- 疑似重复客户只提示，不阻止。

### 代理

- Agent 可创建 ProxyBatch。
- ProxyRecipient 不进入 Customer 表。
- 可自动生成 `15号楼#1` 形式临时名。
- 每件代理快递必须绑定 ProxyRecipient。
- 不同 ProxyBatch 中同名临时收件人互不关联。
- 只有 EXPRESS 可以使用 `source_type=AGENT`；外卖/KFC/果蔬/跑腿/行李代理单创建必须拒绝。

## 3. 订单编号

- 固定号如 `K-260829-023` 可以搜索到订单。
- 动态号如 `K-V-260829-023` 可以搜索到同一订单。
- 状态变化只改变动态展示号，不改变固定三元组身份。

## 4. 快递录单

1. SOUTH/NORTH 不要求具体校外地点。
2. OUTSIDE 时具体取件地点必填。
3. pickup_identifier 必填，可为运单号或取件码。
4. size=UNKNOWN 可保存，基础价显示待确认。
5. 创建订单时保存当时 SMALL/MEDIUM/LARGE/OVERSIZE 四档价格快照。
6. 校内送校外时详细地址必填，并产生默认 +2/件费用项。
7. 校外取件产生默认 +1/件费用项。
8. 重复取件标识命中时弹强提醒，但“仍然创建”成功。

## 5. 大小确认与价格快照

1. UNKNOWN 可以被 `build_settlement()` 纳入 DRAFT，但 `freeze_settlement_for_payment()` / 生成有效结算凭证时仍未确认 → 必须拒绝冻结。
2. 配送员确认 SMALL/MEDIUM/LARGE/OVERSIZE 后使用订单创建时对应价格快照。
3. 例：创建时 LARGE=6，后台之后改为 7，UNKNOWN 订单之后确认 LARGE 仍生成 6 元 BASE_SERVICE。
4. 已存在的费用项和 SettlementLine 不受配置变化影响。

## 6. 上楼字段

- Customer 地址中存在 floor/room，但本单 `requires_upstairs=false` 时，不得被 Dashboard 或计价误判为上楼单。
- `requires_upstairs=true` 时缺楼层/房间应按业务规则拒绝提交/完成。
- 行李搬上楼始终 true。

## 7. 路线接单并发

- 两名配送员同时争抢同一订单，只能一个成功。
- 批量选 8 件，其中 1 件被抢走时，允许 7 件成功。
- OUTSIDE 路线可包含多个不同具体校外站点，但每张任务卡仍显示具体地点。
- 同一 order 同时最多一条 active assignment。

## 8. 配送员业务限制

- 有快递活跃任务时不能切外卖。
- 同类型允许多个活跃批次。
- 停止接单不影响已接任务。
- 停止接单账号仍可通过协商接受转单（UI警告）。

## 9. 取件/转单

1. ASSIGNED 才能正常 mark PICKED。
2. PICKED 后不能退公共池。
3. PICKED 转单必须 handoff。
4. 接收人确认实物后责任才切换。
5. DELIVERED 后不能普通转单。
6. 重启不回退 PICKED/DELIVERING。

## 10. 配送完成与照片/待结算收益

### 普通业务

- 至少 1 张照片，第二张/标注可选。
- 多订单合并到一个 DeliveryDrop 时，必须验证：同一配送员有效责任、允许完成状态、同一 Customer/ProxyRecipient、同业务类型、目的地/实际放置动作兼容、同一位置文字和照片能够真实描述全部物品。
- 不同客户或不同实际放置位置强制拆成不同 DeliveryDrop。
- 配送完成创建 BASE_DELIVERY `PENDING_PAYMENT` CourierEarning，`settlement_id=NULL`，并使用确定性 earning_key 保证重复提交不重复创建。
- 不为了收益外键创建虚假 DRAFT Settlement。

### 行李搬上楼

- 图片允许 0 张；最终位置仍需可读。
- room 允许为空，building/floor 必填。

## 11. 上楼费用

例如 4 楼：

- 1 小件 → 2 元；
- 2 小件 → 4 元；
- 1 大件 → 4 元；
- 1 中 + 1 大 → `4*0.5 + 4*1 = 6` 元。

快递上楼与行李上楼使用同一费率逻辑。

## 12. ExpressRound 与归拢

- EXPRESS 的 service_date 必须非空；未显式填写时 UI/后端默认当前本地日期。新快递加入同一收件归属 + 同一 service_date + OPEN 的 ExpressRound；没有则建新 round_no。
- 不同 service_date 永不相互阻塞。
- ExpressRound CLOSED 后，同日新增快递进入下一轮。
- OPEN round 存在 NEW/ASSIGNED/PICKED/DELIVERING 时不能自动关闭。
- 不再存在 NEW/ASSIGNED/PICKED/DELIVERING 后：若本轮所有订单均 CANCELED、有效已送达数量为 0，ExpressRound 必须自动 CLOSED 且不创建 ConsolidationRound；1 件 DELIVERED 直接 CLOSED；>=2 件按 eligibility 建立必要 ConsolidationRound。
- 当某 ExpressRound 已存在 `PENDING` 或 `IN_PROGRESS` ConsolidationRound 时，即使这些成员因“已进入归拢轮次”而导致当前剩余候选集合为空，ExpressRound 仍必须保持 OPEN；只有现有归拢全部 COMPLETED，且重新评估后剩余合格候选少于 2，才能 CLOSED。
- 已完成一个 ConsolidationRound 后若仍有至少 2 个尚未归拢的合格物件，应继续创建下一必要 ConsolidationRound；若只剩 0 或 1 个合格物件，则无需再归拢并允许 ExpressRound CLOSED。
- 归拢候选遇到 `OPEN && blocks_consolidation=true` 异常必须排除。
- ConsolidationRound 成员冻结后不能追加。
- 默认负责人是对应成员中最后完成配送员。
- `reassign_consolidation_round()` 只改变归拢负责人并写 AuditEvent，不改变任何已 DELIVERED Order Assignment。
- 手工提前建立合格子集后，同一 ExpressRound 后续剩余物件仍可按规则形成其他 ConsolidationRound。

## 13. 简单业务字段

### 外卖

- identifier 必填；OTHER gate 时具体地点必填。

### KFC

- pickup_code 必填；非默认周四时提示但允许继续。

### 果蔬

- item_list、pickup_location 必填；商品金额不能进入账务。

### 跑腿

- 起点、终点、物品描述必填；额外距离费通过 ChargeItem。

### 行李上楼

- 不允许选择加急；允许手工费用项兼容特殊取行李场景。

## 14. 加急、天气与多件优惠

默认加急规则：快递 +1/件、外卖 +2/单、KFC +5/单、果蔬 +2/单、跑腿 +2/单、行李无加急。

天气费只在结算时人工添加，默认 +2/收件归属/结算轮：

- 同一 Customer 当前快递 round 有 5 件，只产生一项 +2；
- 一个 ProxyBatch 有两个 ProxyRecipient 且都勾选天气，产生两项 +2；
- 未勾选不产生费用项。

多件优惠：

- 5 件：0；
- 6 件：-0.5；
- 8 件：-1.5；
- 第二轮 4 件不与第一轮累计；
- 默认未勾选时不应用；
- 应用后形成负 ChargeItem，而不是改基础价。

## 15. ChargeItem、DRAFT、VOID 与 SettlementLine

- ChargeItem 采用 ACTIVE/VOIDED，录错费用项逻辑作废并保留 voided_by/at/reason，不物理删除。
- `build_settlement()` 只创建 DRAFT + SettlementOrder，不产生 SettlementLine。
- DRAFT 阶段允许新增/作废 WEATHER、CUSTOMER_EXTRA、人工增减、多件优惠等费用项；这些结算级费用必须绑定当前 settlement_id，快递 WEATHER/MULTI_ITEM_DISCOUNT 同时记录 express_round_id；preview total 只按当前 SettlementOrder 的订单级 ACTIVE 项 + 当前 Settlement 的结算级 ACTIVE 项计算。
- 同一 Order 已存在 DRAFT/WAITING_PAYMENT/SETTLED Settlement 时，不允许构建另一个有效 Settlement。
- “生成有效结算凭证”时重新校验 UNKNOWN/异常，再只把当前 Settlement 的合法 ACTIVE ChargeItem 复制为 SettlementLine，并同时 Settlement/Order → WAITING_PAYMENT。
- Settlement 总额冻结后只按 SettlementLine 求和；冻结值必须 >=0，0 元成功，负数必须拒绝；DRAFT preview 为负只提示、不形成有效账单。
- DRAFT 可 VOIDED；WAITING_PAYMENT 未付款可 VOIDED 且 Order → UNSETTLED、凭证失效；VOIDED 后允许新建 DRAFT。
- 冻结后修改配置、作废原 ChargeItem 或新增其他轮费用，都不改变旧 SettlementLine。
- S100 DRAFT 上创建的 WEATHER/MULTI_ITEM_DISCOUNT 等结算级费用即使 S100 后续 VOIDED，也不得被新建 S101 按 Customer/ProxyRecipient 自动复用；S101 需要时必须重新创建并绑定 S101。
- CUSTOMER_EXTRA 每条必须有 beneficiary；多人收益拆成多条，不自动平均。

## 16. 代理图片、批次状态与结算

1. OPEN 可新增 ProxyRecipient/快递。
2. 有未完成配送、未关闭 ExpressRound/待归拢、UNKNOWN 大小或 `OPEN && blocks_settlement=true` 异常时不能进入 READY_TO_SETTLE。
3. 全部条件满足且至少存在 1 个非取消订单时可自动进入 READY_TO_SETTLE；刚创建、历史订单数为 0 的空 ProxyBatch 必须保持 OPEN；只有历史上至少存在订单且现在全部逐单取消时，才自动 CANCELED，不能因空集合判断进入 READY_TO_SETTLE。
4. READY_TO_SETTLE 后成员冻结；显式 reopen 后回 OPEN，未结算汇总图失效。
5. 生成 ProxyRecipient 凭证/Agent 汇总图不改变 ProxyBatch 状态。
6. 每个 ProxyRecipient 能独立生成客户凭证。
7. show_price 默认 true；false 时凭证不出现费用信息。
8. Agent 汇总图没有任何配送照片。
9. Agent 汇总金额与 SettlementLine 总额一致。
10. SETTLED 后不能追加成员/订单。
11. OPEN 空批次（历史订单数为 0）不会被自动状态评估取消，但显式执行 `cancel_proxy_batch()` 必须允许直接将其置为 CANCELED 并写 AuditEvent。
12. OPEN 非空批次且没有 PICKED/DELIVERING/DELIVERED 有效快递时，`cancel_proxy_batch()` 必须一次事务自动取消仍为 NEW/ASSIGNED 的非取消订单、释放未取件 Assignment、关闭因此全取消的 ExpressRound，并将 ProxyBatch 置 CANCELED；不要求先逐单取消。
13. 批次已有任一 PICKED/DELIVERING/DELIVERED 有效快递时，整批取消必须整体拒绝且不能产生半取消状态；READY_TO_SETTLE/SETTLED 也不能整批取消。尚未取件订单仍允许单独取消。
14. 代理人的下游价格无字段、无统计。

## 17. 结算确认、VOID 与撤销

1. 不跨业务类型合并。
2. DRAFT 不改变 Order settlement_status。
3. 生成有效图片/冻结时 Settlement=WAITING_PAYMENT，所有 SettlementOrder 对应 Order=WAITING_PAYMENT。
4. confirm 后 Settlement/Order 进入 SETTLED。
5. 重复 confirm 不重复生成 CourierEarning；earning_key 幂等生效。
6. DRAFT 或未付款 WAITING_PAYMENT 可 VOIDED；WAITING_PAYMENT VOID 后 Order=UNSETTLED，旧有效图片标记 VOIDED/INVALID。
7. 已付款误结算采用 REVERSED：相关 Order 回 UNSETTLED，原 Settlement/CourierEarning/图片保留历史，再次结算创建新 Settlement/SettlementLine/CourierEarning/图片版本；新凭证冻结时 Order 才重新进入 WAITING_PAYMENT。
8. ProxyBatch 的已结算批次撤销后回 READY_TO_SETTLE。
9. 真实退款 append-only，不修改原 SettlementLine。

## 18. 工资

### 比例模式

- 普通业务按分成快照正确计算。
- CUSTOMER_EXTRA 100% 直接加入费用项指定的 beneficiary courier，不乘普通业务分成；多配送员场景必须显式选择或拆成多条。

### 手工模式

- available_pool 来自已结算净服务营业收入，而不是建议工资合计。
- 强制归属金额先锁定给指定成员。
- 人工分配总额 <= `available_pool - locked_amount` 成功。
- 超出剩余池拒绝。
- 某人最终金额 > 个人直接普通配送收益只 warning。

## 19. 异常与媒体生命周期

- ExceptionCase 显式保存 blocks_consolidation / blocks_settlement；不同 service 统一读取字段，不自行猜 reason_code。
- OPEN ExceptionCase 直接上传的图片不清理。
- OPEN ExceptionCase 引用的 DeliveryEvidence/归拢图片不清理。
- 异常关闭后 `delete_after = max(media.created_at + retention, resolved_at + retention)`。
- 图片已经超过 30 天但异常今天才解决时，仍至少再保留 30 天。
- 普通客户结算图、ProxyRecipient 凭证、Agent 汇总图同样默认 30 天清理文件，但保留 MediaFile/版本 metadata 和 SettlementLine。
- 原配送照片仍在时可完整重建凭证；原照片已清理时只能重建无照片历史凭证并显示清理提示；Agent 汇总图可完整结构化重建。

## 20. Dashboard

同一组筛选条件必须同时约束 cards、charts、table、Excel。

验收示例：`业务=快递 + 成员=张三 + pickup=南区 + size=大件 + 本月`，所有指标必须只来自该集合。

`是否上楼` 必须按 `requires_upstairs` 筛选，不根据 floor/room 推断。

代理筛选、Agent 筛选、费用项筛选必须生效。

## 21. 快速完成/历史补录

- DIRECT_COMPLETE 正常计收益。
- HISTORICAL_BACKFILL 无照片允许，但补录说明必填。
- 不存在“已关闭业务日”限制。

## 22. 备份/恢复

- 每日自动备份 DB+配置成功并写 BackupRecord/JobRun。
- 手动备份可用。
- restore 前自动 PRE_RESTORE。
- 缺旧照片不阻塞 DB restore。
- 管理员可只删除备份照片归档。

## 23. 维护与故障恢复

- maintenance 阻止普通写操作。
- 管理员仍能备份/恢复。
- 异常断电重启后业务状态不回退。
- 临时半文件被清理。
- stale login lease 被恢复检查或任务清理。

## 24. UI/PWA

- 管理员/录单员 1366px 桌面布局可用，360px 手机布局无横向溢出。
- 配送员桌面打开仍呈现移动卡片布局。
- 至少亮/暗/暖/蓝青 4 主题切换正常。
- PWA 可安装。
- 上传失败保留表单。
- 重复点击不会产生重复业务记录。

## 25. 性能基线

目标：客户/代理/订单合计 10 万级以内、同时用户 3～10。普通列表 50/页。小主机正常负载下大多数非图片页面目标 <500ms。

不得为了该规模提前引入 Redis/ES/ClickHouse。

# 11. 实现阶段与 TODO

编码 AI 必须按阶段推进；阶段内所有可完成 TODO、测试、迁移完成后再进入下一阶段。

## Phase 0：工程骨架

- [ ] Django 工程、dev/prod settings
- [ ] Dockerfile / Compose / Caddy
- [ ] SQLite WAL
- [ ] pytest / pytest-django / Ruff
- [ ] health endpoints
- [ ] HTMX / Alpine / Bootstrap
- [ ] PWA manifest/service worker 基础
- [ ] 四套主题 CSS Variables
- [ ] README 安装说明

## Phase 1：账号、会话、客户、配置

- [ ] Custom User + 3 角色
- [ ] 下拉登录
- [ ] ActiveLoginLease
- [ ] 心跳 endpoint + stale lease
- [ ] 管理员强制下线
- [ ] 接单开关/当前业务类型
- [ ] Customer CRUD + 快照
- [ ] `/` 多名称/尾号搜索
- [ ] Building/Zone
- [ ] 业务/价格/加急/上楼/分成/主题配置
- [ ] KFC 默认开放日配置

## Phase 2：代理人体系

- [ ] Agent
- [ ] ProxyBatch 状态机 + `cancel_proxy_batch()` 原子整批取消（取消 NEW/ASSIGNED、释放未取件 Assignment、联动关闭全取消 ExpressRound）
- [ ] ProxyRecipient
- [ ] 仅 EXPRESS 可使用代理来源的约束
- [ ] 自动临时命名
- [ ] 代理批次录单 UI
- [ ] show_price_on_receipt 默认值
- [ ] 代理搜索/审计

## Phase 3：订单、费用与结算基础模型

本阶段完成后，后续配送、凭证和结算阶段依赖的核心表结构必须已经存在；业务 workflow 可以在后续 Phase 实现。

- [ ] Order 公共模型 + `requires_upstairs`
- [ ] 6 类 Detail
- [ ] 固定/动态订单编号 service
- [ ] pickup_identifier 统一模型
- [ ] EXPRESS service_date 必填/默认当前本地日期 + ExpressRound 显式“本轮快递”模型 + 订单归轮 service
- [ ] 快递 UNKNOWN 大小 + 四档订单创建时价格快照
- [ ] 校外取件/校内送校外
- [ ] 普通录单/连续录入
- [ ] 条件校验
- [ ] 重复订单提醒
- [ ] ChargeItem ACTIVE/VOIDED + pricing/void service
- [ ] Settlement 基础模型
- [ ] SettlementOrder
- [ ] SettlementLine 不可变快照模型（仅 freeze 时生成）
- [ ] FinancialAdjustment 基础模型
- [ ] CourierEarning 来源拆行 + earning_key 幂等 + settlement nullable
- [ ] 订单修改/取消/审计

## Phase 4：简单配送业务

先实现外卖/KFC/果蔬/跑腿/行李上楼：

- [ ] Simple DeliveryTask
- [ ] 业务类型限制
- [ ] 接单/取到/配送
- [ ] DeliveryDrop
- [ ] `requires_upstairs` 校验
- [ ] 照片压缩
- [ ] 近景/远景证据
- [ ] 标注派生图
- [ ] 行李照片可选
- [ ] 配送完成创建 PENDING_PAYMENT CourierEarning 归属记录
- [ ] 转单
- [ ] 基础异常模型

## Phase 5：快递复杂配送

- [ ] 南/北/校外路线池
- [ ] 校外具体地点展示
- [ ] 动态组批并发 claim
- [ ] 客户直送
- [ ] 加急
- [ ] 单件取件
- [ ] UNKNOWN 大小确认并使用订单创建时价格快照
- [ ] 楼栋/收件归属排序
- [ ] 已取实物交接转单
- [ ] 快递配送完成收益归属
- [ ] ExpressRound 完成/关闭判定（含全部取消、有效已送达=0 自动 CLOSED）

## Phase 6：归拢、结算构建与凭证

- [ ] 归拢 eligibility selector（读取 ExpressRound + blocks_consolidation）
- [ ] Customer/ProxyRecipient 自动/手动归拢
- [ ] 默认归拢负责人 = 归拢成员最后完成配送员
- [ ] `reassign_consolidation_round()` 独立改派 + AuditEvent
- [ ] frozen ConsolidationRound
- [ ] 找件清单
- [ ] 最终近景/远景标注/位置
- [ ] ProxyBatch READY_TO_SETTLE 判定/重新打开
- [ ] `build_settlement()`
- [ ] SettlementOrder 固定本轮订单
- [ ] DRAFT 阶段费用项编辑/VOID
- [ ] CUSTOMER_EXTRA 显式 beneficiary，多配送员拆项
- [ ] 其他人工增费/减免费用项
- [ ] 结算级费用绑定当前 settlement_id；快递 WEATHER/MULTI_ITEM_DISCOUNT 绑定 express_round_id
- [ ] 生成有效凭证时 ChargeItem → SettlementLine 冻结
- [ ] freeze 时 UNKNOWN/异常/amount>=0 最终硬校验
- [ ] Settlement VOIDED 流程
- [ ] 特殊天气按收件归属/结算轮计费
- [ ] 多件本轮优惠
- [ ] 普通客户结算图
- [ ] ProxyRecipient 客户凭证
- [ ] show price 开关
- [ ] Agent 无照片汇总图
- [ ] 图片版本/下载
- [ ] 生成有效图片后 Settlement + SettlementOrder 对应 Order → WAITING_PAYMENT

## Phase 7：结算确认、收益与工资

- [ ] confirm Settlement
- [ ] Order settlement_status 联动
- [ ] PENDING_PAYMENT CourierEarning 最终金额/Settlement 绑定
- [ ] CUSTOMER_EXTRA/UPSTAIRS/MANUAL_EXTRA 对应 CourierEarning 生成与归属
- [ ] CourierEarning 按收益来源拆行/earning_key 幂等
- [ ] Settlement reversal
- [ ] REVERSED CourierEarning + 再结算新记录
- [ ] FinancialAdjustment/真实退款
- [ ] 分业务分成
- [ ] 工资可分配净营业收入池
- [ ] locked earning
- [ ] 工资比例模式
- [ ] 工资手工模式 + 剩余池总额约束

## Phase 8：异常、人工处理、快速补录

- [ ] ExceptionCase 完整 UI + blocks_consolidation/blocks_settlement
- [ ] ExceptionCaseAttachment
- [ ] ExceptionEvidenceLink
- [ ] OPEN 异常图片保护
- [ ] ManualHandling
- [ ] 退款影响工资
- [ ] DIRECT_COMPLETE
- [ ] HISTORICAL_BACKFILL

## Phase 9：经营分析、搜索、Excel

- [ ] 统一 Dashboard Filter DTO
- [ ] 多维筛选 cards
- [ ] `requires_upstairs` 筛选
- [ ] Chart.js 图表
- [ ] Agent/代理维度
- [ ] 路线/大小/费用项等维度
- [ ] 固定/动态订单号全局搜索
- [ ] Excel 继承筛选条件
- [ ] SettlementLine/收益导出
- [ ] 配送员个人统计

## Phase 10：运维

- [ ] 每日 03:00 自动备份
- [ ] 手动备份
- [ ] 月度 30 天图片清理（含生成结算/代理凭证）
- [ ] 凭证重建：完整/无照片历史模式
- [ ] OPEN 异常直接/间接图片保护
- [ ] resolved_at 后完整 retention 周期
- [ ] 备份照片独立管理
- [ ] restore + PRE_RESTORE
- [ ] Maintenance mode
- [ ] startup recovery check
- [ ] JobRun 幂等
- [ ] stale lease 清理

## Phase 11：PWA/弱网/收尾

- [ ] PWA install 验证
- [ ] 文本草稿保留
- [ ] 图片上传失败重试
- [ ] operation_id 幂等
- [ ] Android 真机测试
- [ ] Windows 管理员/录单员测试
- [ ] 配送员桌面移动布局测试
- [ ] Demo seed
- [ ] 开源 README / MIT License
- [ ] 最终回归测试

## 停止条件

只有全部 Phase 完成，或存在无法解决的真实外部阻塞且其余 TODO 已全部完成时，编码 AI 才允许停止。

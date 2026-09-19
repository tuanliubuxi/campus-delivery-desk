# 16. 系统配置中心

所有配置只允许管理员修改，并写 AuditEvent。历史订单/费用项保留当时快照。

## 1. 业务类型

固定 6 种：EXPRESS、TAKEOUT、KFC、GROCERY、ERRAND、LUGGAGE_UPSTAIRS。

可配置启用、显示名、图标、颜色、排序。V1 不允许后台创建任意第七种业务。

## 2. 基础价格

快递：小2、中4、大6、超大8；UNKNOWN 无价。

外卖 3；KFC 10；果蔬 5；跑腿建议基础 3；行李上楼无单一 base fee，以楼层/件数费率计算。

## 3. 加急

- 快递 1/件
- 外卖 2/单
- KFC 5/单
- 果蔬 2/单
- 跑腿 2/单
- 行李：不支持（核心业务规则，不能后台打开）

金额可修改，计价单位固定。

## 4. 快递附加费

- 校外取件：默认 +1/件；
- 校内送校外：默认 +2/件。

## 5. 上楼费率

- SMALL/MEDIUM：0.5 元/层/件；
- LARGE/OVERSIZE：1 元/层/件。

快递和行李上楼共用。

## 6. 特殊天气

默认金额 +2/一个收件归属的一次结算轮，只作为结算时人工可选费用项。普通客户按 Customer 当前轮一次，代理快递按每个 ProxyRecipient 当前轮分别一次。不开全局天气自动模式。

## 7. 多件优惠

配置：threshold=5，per_extra_item=0.5，enabled=true。

只在单次结算轮可选，不自动应用、不跨轮累计。

## 8. 配送员分成

普通业务收益按业务/收益来源配置分成比例。CUSTOMER_EXTRA 为强制归属收益，100% 计入费用项指定的 beneficiary courier；单一最终配送员可自动选择，多配送员时必须显式选择或拆成多条，不参与普通业务分成，也不能在手工工资模式中转给其他成员。

## 9. KFC 开放日

默认星期四。非开放日只提示，不强制禁止。

## 10. 楼栋与路线顺序

Building：zone、route_order、启用状态。默认 1～10 SOUTH、11～18 NORTH。

## 11. 快捷位置词

快递架、外卖架、左/右、顶层、最底层、从上往下第N层、靠墙等；只作为文本快捷插入。

## 12. 主题

至少 Light、Dark、Warm、Fresh Blue/Cyan。管理员设默认主题，用户可覆盖。

## 13. 图片生命周期

retention_days 默认 30。月度清理任务删除超过期限的配送/归拢照片、标注图以及普通客户结算图、ProxyRecipient 凭证、Agent 汇总图文件；结构化账务与 MediaFile/版本 metadata 保留。OPEN 异常保护不可关闭。

## 14. 登录租约参数

建议放系统配置但仅管理员高级设置可见：heartbeat interval 30s、stale timeout 150s。修改需限制合理范围。

## 15. 不允许配置的核心不变量

- 单订单最多一个 active assignment；
- 已取件转单必须交接；
- 异常独立主状态；
- 历史快照不可污染；
- 不跨业务结算；
- 代理体系仅用于 EXPRESS，临时收件人不进 Customer；
- 行李不支持加急；
- 无 BusinessDay/日终收工；
- 未确认快递大小可以进入 DRAFT，但不能 freeze/生成有效结算凭证/进入 WAITING_PAYMENT；
- DRAFT 只固定 SettlementOrder 并允许编辑 ACTIVE ChargeItem；结算时创建的 WEATHER/CUSTOMER_EXTRA/人工增减/MULTI_ITEM_DISCOUNT 必须绑定当前 settlement_id，快递 WEATHER/MULTI_ITEM_DISCOUNT 同时记录 express_round_id。正式凭证生成时才冻结 SettlementLine。冻结前必须重新校验 UNKNOWN、阻塞异常及总额 >=0；冻结后总价只能来自 SettlementLine。
- ChargeItem 不物理删除，只能 ACTIVE → VOIDED。
- 快递“本轮”必须来自 ExpressRound，不允许各模块自行按时间猜测。
- 快递 UNKNOWN 确认大小时使用订单创建时价格快照。
- 上楼业务判断使用 Order.requires_upstairs，不从地址字段推断。

# V1 回归验收记录

本记录逐项映射 `docs/spec/10_TESTING_ACCEPTANCE.md`。自动化结果只证明代码与测试环境中的行为；真实设备步骤见 `MANUAL_ACCEPTANCE.md`。

| 规格章节 | 验证方式 | 当前结果 |
|---|---|---|
| 1 登录与单会话 | accounts 租约/登录测试；核心工作台使用真实登录租约的路由冒烟测试 | 通过 |
| 2 客户与代理 | customers、agents 测试 | 通过 |
| 3 订单编号 | orders 编号与搜索测试 | 通过 |
| 4 快递录单 | orders 字段、价格快照、created_at 滚动 72 小时重复提醒及取消排除测试 | 通过 |
| 5 大小确认与价格快照 | orders/dispatch/settlements 联合测试 | 通过 |
| 6 上楼字段 | orders/dispatch/dashboard 测试 | 通过 |
| 7 路线接单并发 | dispatch SQLite 条件写入测试 | 通过 |
| 8 配送员业务限制 | accounts/dispatch 测试 | 通过 |
| 9 取件/转单 | dispatch 状态机测试 | 通过 |
| 10 配送完成与收益 | dispatch、settlements 测试 | 通过 |
| 11 上楼费用 | settlements pricing 测试 | 通过 |
| 12 ExpressRound 与归拢 | orders、consolidation 测试 | 通过 |
| 13 简单业务字段 | orders 表单/service 测试 | 通过 |
| 14 加急、天气、多件优惠 | orders、settlements 测试 | 通过 |
| 15 ChargeItem/SettlementLine | settlements 测试 | 通过 |
| 16 代理图片、批次、结算 | agents、settlements 测试 | 通过 |
| 17 结算确认、VOID、撤销 | settlements 测试 | 通过 |
| 18 工资 | settlements 工资测试；空比例仅阻止 RATIO、MANUAL 可用测试 | 通过 |
| 19 异常与媒体生命周期 | exceptions、operations 测试；ManualHandling 不可变动作与既有服务编排测试 | 通过 |
| 20 Dashboard | dashboard 同筛选器/Excel 测试 | 通过 |
| 21 快速完成/历史补录 | exceptions/orders workflow 测试 | 通过 |
| 22 备份/恢复 | operations 专项测试 | 通过 |
| 23 维护与恢复 | operations 专项测试 | 通过 |
| 24 UI/PWA | manifest/service worker/弱网脚本自动测试；核心角色页面渲染和越权拒绝测试；Windows 无头 Edge 宽窄屏渲染；真实设备清单 | 自动部分通过；Android 真机与交互式 Windows PWA 安装待人工 |
| 25 性能基线 | 独立 SQLite 中生成 Customer 20,000 + Agent 1,000 + Order 79,000；测量列表、搜索和 Dashboard selector | 本机代表路径中位数均 <500ms；明细查询优化记录见 `V1_HARDENING_REPORT.md`；目标小主机及 3～10 并发仍待部署验收 |

## 发布边界

- Demo seed 仅在 DEBUG 环境可运行，生产初始化和 Compose 启动不调用。
- 所有 migration 必须在空 SQLite 数据库顺序执行；Docker 空卷回归时再次验证。
- 仓库扫描不得包含 `.env`、数据库、真实客户信息、媒体、日志、备份或临时文件。
- 真实设备交互、目标小主机端到端/并发负载基准和目标机恢复演练完成前，V1 仍不能宣称为无条件验收通过。

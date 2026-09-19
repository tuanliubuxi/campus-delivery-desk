# 校驿 · Campus Delivery Desk

> 面向 0 上下文编码 AI 的 V1 完整工程规格文档。

## 项目定位

校驿是一个面向约 3～5 人校园代取/配送团队的轻量级、自托管配送运营系统。客户通过微信联系团队，由录单员规范化录入；配送员使用手机端接单、取件、配送、拍照和提交；录单员负责结算与客户反馈；管理员负责人员、配置、经营分析、备份恢复和维护。

### V1 正式业务类型

1. 快递代取
2. 校门口外卖代取
3. 周四石湫肯德基代取
4. 蔬菜/水果/零食代购配送
5. 跑腿送东西
6. 行李搬上楼

V1 只提供“行李搬上楼”，不提供复杂行李搬运路线系统。客户若要求从其他地点取行李再搬上楼，通过“行李搬上楼 + 备注 + 额外费用项”处理。

## V1 技术栈（已确定）

- Python 3.12+
- Django 5.2 LTS
- Django Templates
- HTMX 2.x
- Alpine.js 3.x
- Bootstrap 5.3 + 自定义 CSS Variables
- SQLite + WAL
- Pillow
- Chart.js
- openpyxl
- APScheduler（独立 scheduler 进程）
- Gunicorn
- Caddy
- Docker Compose
- Responsive Web + PWA
- cpolar 仅作为外部内网穿透手段，不耦合业务代码

## 编码 AI 必读顺序

1. `00_AI_EXECUTION_RULES.md`
2. `01_PRODUCT_REQUIREMENTS.md`
3. `02_DOMAIN_RULES_AND_STATE_MACHINES.md`
4. `03_ARCHITECTURE_AND_DIRECTORY.md`
5. `04_DATA_MODEL.md`
6. `05_BACKEND_IMPLEMENTATION.md`
7. `06_UI_UX_PWA.md`
8. `07_AUTH_SECURITY_AUDIT.md`
9. `08_OPERATIONS_BACKUP_RECOVERY.md`
10. `09_REPORTING_SETTLEMENT_WAGES.md`
11. `10_TESTING_ACCEPTANCE.md`
12. `11_IMPLEMENTATION_PLAN.md`
13. `12_OPEN_SOURCE_REFERENCES.md`
14. `13_FUTURE_PRO_STACK.md`
15. `14_ROUTES_AND_INTERACTIONS.md`
16. `15_FIELD_MATRIX_AND_VALIDATION.md`
17. `16_CONFIGURATION_CENTER.md`
18. `17_DEPLOYMENT_ENVIRONMENT.md`

## 文档优先级

冲突时：

`00 执行约束 > 01 产品需求 > 02 领域规则 > 04 数据模型 > 05 后端实现 > 06 UI > 其他文档`

发现无法消解的冲突时，编码 AI 不得擅自改业务，应记录到 `docs/IMPLEMENTATION_QUESTIONS.md`，并继续完成其他不受影响的任务。

## V1 核心规则概览

- 快递不使用 `BusinessDay / 22:00 收工 / 日终优惠返还` 体系；统计基于事实数据实时聚合。
- 使用 `ChargeItem` 记录业务费用来源；DRAFT 阶段可编辑/作废费用项，生成有效结算凭证时才冻结为不可变 `SettlementLine`。
- 快递大小为未知/小/中/大/超大，价格 2/4/6/8 元。
- 取件信息统一使用“取件标识”，支持取件码、运单号等。
- 快递取件区域支持南区/北区/校外，并支持校内送校外地址。
- 正式业务包含跑腿送东西、轻量“行李搬上楼”。
- 支持代理人/代理批次/临时收件人体系。
- 配送凭证要求至少一张照片，并推荐近景+远景标注。
- 采用单账号单活跃会话 + 心跳租约。
- 仪表盘采用统一多维筛选分析。
- 工资计算器支持比例模式和手工分配模式，并区分净服务收入池与强制归属收益。
- `13_FUTURE_PRO_STACK.md` 列出多个专业级技术栈方案。

## 核心工程原则

- V1 优先简单可靠，不堆技术名词。
- 业务写操作集中在 service 层，View/Template/JS 不承载核心规则。
- 所有关键写操作可审计、可幂等、可恢复。
- 历史订单与价格均保存快照。
- 所有价格变化统一由费用项组成，总价不可直接覆盖。
- 快递采用复杂配送模型；其他业务尽量复用简单配送模型。
- 代理单的临时收件人不进入正式客户库。
- 服务器重启不得回滚现实中的“已取件/配送中/已完成”状态。
- 统一使用响应式 Web + PWA，不做 V1 原生客户端。

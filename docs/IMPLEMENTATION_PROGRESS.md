# 实施进度

权威 TODO 与验收范围见 [V1 实施计划](spec/11_IMPLEMENTATION_PLAN.md)。本文件记录各阶段进展，不替代需求规格。

## Phase 0：工程骨架（已完成）

- [x] Django 工程、dev/prod settings
- [x] Dockerfile / Compose / Caddy
- [x] SQLite WAL
- [x] pytest / pytest-django / Ruff
- [x] health endpoints
- [x] HTMX / Alpine / Bootstrap
- [x] PWA manifest/service worker 基础
- [x] 四套主题 CSS Variables
- [x] README 安装说明
- [x] 当前阶段测试、diff 审查、提交与推送

本地验证：Python 3.12.5；Django 5.2.17；初始自定义 User 迁移成功；SQLite journal_mode=wal；Django dev/prod check、collectstatic、健康接口及 5 项 pytest 测试通过。Docker Compose 已完成镜像构建、迁移和三服务启动验证；经 Caddy 访问 `/health/live`、`/health/ready` 均返回 200，HTTP 自动跳转 HTTPS，scheduler 正常常驻。因本机 Windows 保留 80 端口，容器验收临时使用宿主机 8080/8443 映射，正式 Compose 配置仍保持 80/443。

## 后续阶段

- [ ] Phase 1：账号、会话、客户、配置（全部 TODO 见实施计划）
- [ ] Phase 2：代理人体系（基础模型；原子整批取消留到 Phase 5）
- [ ] Phase 3：订单、费用与结算基础模型
- [ ] Phase 4：简单配送业务
- [ ] Phase 5：快递复杂配送、基础 ExpressRound 关闭、原子整批取消
- [ ] Phase 6：归拢、多件轮次关闭、结算构建与凭证
- [ ] Phase 7：结算确认、收益与工资
- [ ] Phase 8：异常、人工处理、快速补录
- [ ] Phase 9：经营分析、搜索、Excel
- [ ] Phase 10：运维
- [ ] Phase 11：PWA/弱网/收尾

## 模块边界确认

| App | 主要职责及未来核心实体 |
|---|---|
| accounts | User、ActiveLoginLease、身份与会话 |
| customers | Customer、长期资料与历史快照 |
| agents | Agent、ProxyBatch、ProxyRecipient |
| config_center | 楼栋、区域、业务与价格配置 |
| orders | Order、六类 Detail、ExpressRound、录单与取消 |
| dispatch | DeliveryTask、Assignment、Transfer、DeliveryDrop |
| consolidation | ConsolidationRound/Item、归拢工作流 |
| settlements | ChargeItem、Settlement/Order/Line、FinancialAdjustment、CourierEarning |
| exceptions | ExceptionCase、人工处理 |
| mediafiles | MediaFile、配送证据、受控存储 |
| audit | 仅追加 AuditEvent |
| operations | BackupRecord、JobRun、MaintenanceState |
| dashboard | 只读筛选、聚合与导出 |

写入由各 App 的 `services/` 主持事务与状态迁移；复杂读取由 `selectors/` 提供。关键约束包括订单编号唯一、每单至多一个有效 Assignment、ExpressRound 收件归属二选一、代理来源仅限快递、费用项逻辑作废、SettlementLine 冻结后不可变。Phase 0 仅建立目录及运行基础，不提前创建业务模型或迁移。

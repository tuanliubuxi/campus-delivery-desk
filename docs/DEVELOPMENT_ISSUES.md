# 开发问题记录

本文件记录实施过程中发现的问题、影响和最终处理状态。权威需求缺口仍以 `IMPLEMENTATION_QUESTIONS.md` 为准。

| 编号 | 问题 | 处理结果 | 状态 |
|---|---|---|---|
| DEV-001 | 初始入口文档文件名曾误写为 `AGENT.md`。 | 已统一为根目录 `AGENTS.md`。 | 已解决 |
| DEV-002 | `docs/spec-backup` 和 `docs/prompts` 属于本地历史/提示词资料，不应进入产品仓库。 | 目录保留在本机并通过 `.gitignore` 排除。 | 已解决 |
| DEV-003 | ProxyBatch 取消、空批次和 ExpressRound/归拢关闭边界曾存在阶段依赖与空集合歧义。 | 权威规格已补齐，分别在 Phase 5/6 按最终状态机实现并测试。 | 已解决 |
| DEV-004 | Docker Compose 的 Web 与 scheduler 是两个必要应用进程，曾被误认为重复实例。 | 已明确进程职责；阶段验证结束主动关闭 Docker，不遗留项目运行容器。 | 已解决 |
| DEV-005 | 开发数据库中的管理员/成员测试账号需要恢复为空状态。 | 已按用户授权清空开发数据；正式初始化改用显式管理员命令。 | 已解决 |
| DEV-006 | 国内 Docker Hub 链路存在超时。 | 本机配置 DaoCloud 镜像并保留回退说明。 | 已解决 |
| DEV-007 | Windows pytest 临时目录偶发 ACL/缓存写入警告。 | 测试业务断言不受影响；Phase 测试目录改到受控 `data/tmp` 并在收尾清理。 | 已缓解 |
| DEV-008 | 初始录单缺少持久化 `operation_id`，弱网重试可能创建重复订单。 | Phase 11 增加 Order 唯一创建幂等键、表单透传、service 重试回查和迁移测试。 | 已解决 |
| DEV-009 | 部署规格列出的 `create_app_admin`、`seed_initial_config` 尚无实际命令。 | Phase 11 补充幂等命令，并让 README 只使用真实可执行命令。 | 已解决 |
| DEV-010 | 浏览器默认提交失败无法可靠保留图片引用，文本草稿也没有统一恢复能力。 | Phase 11 增加显式弱网状态、localStorage 文本草稿和页面内图片失败重试。 | 已解决 |
| DEV-011 | Android 真机安装、相机上传和触控行为无法由桌面自动化等价证明。 | 建立 `MANUAL_ACCEPTANCE.md`；必须在真实 Android + 正式 HTTPS 环境执行后才能关闭。 | 待人工验收 |
| DEV-012 | ManualHandling 缺少权威数据模型与状态机。 | 已转入 `IMPLEMENTATION_QUESTIONS.md`，不自行发明规则。 | 待需求补充 |
| DEV-013 | 默认配送员分成比例与快递重复提醒跨日窗口未给出。 | 保持安全拒绝/同 service_date 口径，并已记录待确认问题。 | 待需求补充 |
| DEV-014 | 本机 Windows UI 自动化运行资产缺失，无法驱动登录后的 Edge 做完整交互回放。 | 已用临时数据库、无头 Edge 宽/窄屏渲染、Django 集成测试和模板/CSS 契约检查替代；真实设备步骤继续保留在人工验收清单。 | 已缓解 |

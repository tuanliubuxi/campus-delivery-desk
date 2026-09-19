开始 Phase 0：项目初始化。

严格按照 docs/spec 中的 V1 要求执行。

本阶段完成：

1. 建立 Django 项目基础骨架；
2. 建立文档要求的模块目录；
3. 配置依赖管理；
4. 配置 SQLite WAL；
5. 建立开发环境配置；
6. 建立 `.env.example`；
7. 完善 `.gitignore`；
8. 建立基础日志；
9. 建立基础测试框架；
10. 创建项目根 README.md；
11. 准备 Docker Compose / Gunicorn / Caddy 的基础结构；
12. 不提前开发后续阶段的业务功能。

完成后：

1. 执行所有当前可运行测试；
2. 检查 git status 和 git diff；
3. 确认没有 secrets、数据库、照片、日志、备份等被纳入版本管理；
4. 给出本阶段完成报告。

如果 GitHub CLI 已认证，并且当前尚不存在远程仓库：

创建名为 `campus-delivery-desk` 的 PRIVATE GitHub 仓库，
将当前项目作为首次提交推送。

提交信息使用：

chore: initialize campus delivery desk

如果远程仓库已经存在，则不要重新创建，只正常提交并 push。

任何认证失败、仓库重名、权限异常都必须停止相关操作并报告，不允许自行删除或覆盖远程仓库。
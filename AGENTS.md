# Coding Agent Instructions

本项目名称：Campus Delivery Desk（校驿）。

## 必读文档

在进行任何设计、编码、重构或修复前，必须首先阅读：

1. `docs/spec/README.md`
2. `docs/spec/00_AI_EXECUTION_RULES.md`
3. 与当前任务相关的其他 `docs/spec/*.md`

`docs/spec/` 是本项目 V1 的权威需求来源。

如果代码实现、个人判断与需求文档冲突，以需求文档为准。

禁止在没有阅读相关需求文档的情况下自行猜测业务规则。

## 开发原则

- 按需求文档规定的 V1 技术栈开发。
- 不擅自引入专业版技术栈。
- 不擅自增加需求外的大型基础设施。
- 每个开发阶段完成后必须：
  1. 执行测试；
  2. 检查 Git diff；
  3. 更新必要文档；
  4. 创建 Git commit；
  5. 推送到远程仓库。
- 不允许为了通过测试而删除、弱化或绕过需求。
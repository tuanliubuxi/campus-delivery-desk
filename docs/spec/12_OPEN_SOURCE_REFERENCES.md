# 12. 开源项目与参考实现

以下项目用于参考思想、模块边界和交互，不建议直接 fork 作为校驿底座。

> 参考信息于 2026-09 复核；真正编码时如需复制任何第三方代码，必须再次确认具体文件许可证。

## 1. Fleetbase

地址：`https://github.com/fleetbase/fleetbase`

定位：模块化物流/供应链操作系统。

建议参考：

- Order Board 信息组织；
- Driver/dispatch 概念；
- Service Zones；
- Activity/audit；
- Dashboard；
- 模块边界和自托管思路。

不要照搬地图/GPS、复杂 IAM、企业扩展系统。

当前主仓库为 AGPL-3.0/商业双许可方向；校驿计划 MIT，只参考公开架构概念，不复制受 AGPL 约束的源码。

## 2. Witylogix

地址：`https://github.com/wityliti/witylogix`

定位：自托管 last-mile delivery 平台。

建议参考：

- Proof of Delivery；
- audit trail；
- dashboard；
- 文件存储抽象；
- worker/job 边界；
- Docker/health/recovery 思路。

它使用 PostgreSQL/PostGIS、Redis、BullMQ、实时跟踪等重型组件，校驿 V1 不照搬。

当前仓库为 AGPL-3.0，只参考思想。

## 3. Delivery Management System

地址：`https://github.com/mrmarufpro/Delivery-management-system`

建议参考：多角色页面拆分、基础配送后台信息架构。不要用它替换校驿领域模型。

## 4. Campus Runner

地址：`https://github.com/saismrutiranjan18/Campus_Runner`

校园跑腿/配送移动应用。建议参考移动端任务卡、校园场景 UX；不要照搬 Firebase、地图、Push、客户自助发单。

## 5. 官方/框架参考

- Django：`https://www.djangoproject.com/`
- HTMX：`https://htmx.org/`
- Alpine.js：`https://alpinejs.dev/`
- Bootstrap：`https://getbootstrap.com/`
- Chart.js：`https://www.chartjs.org/`
- Caddy：`https://caddyserver.com/`

## 6. 参考原则

1. 先服从校驿需求，再参考第三方。
2. 第三方存在某功能不代表 V1 要加入。
3. 不复制许可证不兼容的源码。
4. 优先参考数据流、UI 信息密度、Proof of Delivery、审计和任务边界。
5. 3～5 人系统以简单可靠为第一目标。

# 13. 未来专业版技术栈方案

本文件不是 V1 TODO。V1 已确定 Django 单体，先稳定运营，再根据学习/求职方向选择专业版重构。

## 1. 总原则

专业版的价值应来自：领域建模、并发抢单、事务、幂等、审计、文件一致性、故障恢复、查询分析、测试和部署，而不是堆 Kafka/K8s/ES。

## 2. 方案 A：Go 精简专业版（首推）

```text
React + TypeScript + Vite
Ant Design / Ant Design Pro
TanStack Query + ECharts
        ↓ REST/OpenAPI
Go + Gin
        ↓
PostgreSQL
本地文件/Storage Adapter
Docker Compose + Caddy
```

DB：pgx + sqlc；Migration：Goose；日志：slog/zap。

后台任务第一阶段可使用 PostgreSQL Job 表 + scheduler，不必默认上 Redis。

### 优点

- 简历辨识度高；
- Go 并发/事务/服务层很适合讲系统设计；
- 基础设施仍克制；
- 能展示前后端分离和 API 设计。

### 适合

想做 Go 后端、云原生/基础设施相关岗位，又希望项目真实可解释。

## 3. 方案 A+：Go 完整专业版

在 A 基础上，真实有需求后再加：

- Redis；
- Asynq；
- WebSocket（只有调度确实需要实时更新才加）；
- S3/MinIO Storage Adapter。

不建议一开始就启用全部组件。

## 4. 方案 B：Django/DRF 专业升级版

```text
React + TypeScript
Ant Design
Django + Django REST Framework
PostgreSQL
Celery + Redis（按需）
Docker Compose
```

### 优点

- 最容易复用 V1 的 Django 领域模型和业务知识；
- 迁移成本低；
- Django Admin/ORM/生态成熟；
- 同样可以展示前后端分离、异步任务和 PostgreSQL。

### 适合

希望尽快得到“专业架构”而不想重写全部后端。

## 5. 方案 C：NestJS + React/Next.js

```text
NestJS (TypeScript)
React / Next.js
PostgreSQL
Prisma / TypeORM
Redis + BullMQ（按需）
```

### 优点

- 全栈 TypeScript；
- DI、Module、Guard、DTO、Validation 结构化；
- 企业 Node 生态常见。

### 缺点

依赖和构建链比 Go/Django 更复杂。

### 适合

目标岗位为 Node.js/TypeScript 全栈或后端。

## 6. 方案 D：Spring Boot 企业版

```text
Spring Boot
Spring Security
JPA/MyBatis
PostgreSQL
Redis（按需）
React / Vue
```

### 优点

- 企业后端简历价值高；
- 权限、事务、分层、测试、工程规范可展示内容丰富。

### 缺点

对 3～5 人实际系统明显更重，开发迭代速度慢于 Django。

### 适合

明确面向 Java 后端、大型企业、银行/政企等岗位。

## 7. 方案 E：Laravel 专业全栈版

```text
Laravel
PostgreSQL/MySQL
React/Vue + Inertia 或 API 分离
Laravel Queue（按需 Redis）
```

### 优点

开发效率高、后台业务生态成熟、部署简单度仍不错。

### 适合

团队或个人本身偏 PHP/Laravel。

## 8. 方案对比

| 方案 | 开发成本 | 运维 | 简历价值 | 迁移 V1 成本 | 推荐场景 |
|---|---:|---:|---:|---:|---|
| Go 精简 | 中 | 中低 | 很高 | 高 | 首选专业重构 |
| Go + Redis | 中高 | 中 | 很高 | 高 | 真需要异步/扩展 |
| DRF + React | 中 | 中 | 高 | **低** | 最平滑升级 |
| NestJS | 中高 | 中 | 高 | 高 | TS 全栈 |
| Spring Boot | 高 | 中高 | 很高 | 高 | Java 求职 |
| Laravel | 中 | 低中 | 中高 | 高 | PHP 生态 |

## 9. V1 为未来迁移应保持的约束

- 领域 service 清晰；
- Audit/FinancialAdjustment append-only；
- 文件通过 Storage abstraction；
- 不把业务逻辑写模板/View；
- 枚举/状态机显式；
- ChargeItem 与代理模型关系化；
- Dashboard filters 有统一 DTO；
- SQLite 特有机制不成为领域语义。

## 10. 不建议为了简历加入

Kubernetes、Kafka、多微服务、CQRS/Event Sourcing、服务网格、Elasticsearch、复杂 GIS，除非真实规模和需求证明需要。

## 11. 推荐路线

1. 先完成 Django V1 并真实运营；
2. 记录真实痛点/查询/并发/性能数据；
3. 若要做第二实现，优先选择 Go 精简版；
4. 若希望最低迁移成本，选择 DRF + React；
5. 根据求职方向再考虑 NestJS/Spring Boot。

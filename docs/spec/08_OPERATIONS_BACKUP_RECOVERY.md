# 08. 运维、备份、恢复与故障处理

## 1. 业务流程与运维任务解耦

V1 不使用 22:00 收工和 BusinessDay。运维任务与业务流程完全解耦。

## 2. 自动备份

建议每天 03:00：

```text
/data/backups/2026-09-19_030000/
├─ database.sqlite3
├─ config.json
├─ manifest.json
└─ photos.tar   # 当期/增量照片归档策略可实现为当日新增照片
```

数据库和配置快照长期保留，直到管理员手工删除。

照片占大头：主媒体和备份照片均遵循约 30 天策略。

## 3. 图片清理、生成凭证与异常保护

每月执行一次：删除超过 retention_days（默认 30）的普通业务图片和备份照片归档。

默认 30 天范围包括：

- 配送近景/远景；
- 标注派生图；
- 归拢照片；
- 普通客户结算图；
- ProxyRecipient 客户凭证；
- Agent 汇总结算图。

订单、Settlement、SettlementLine、ChargeItem、审计以及 MediaFile/图片版本 metadata 不删除。媒体文件被清理后记录 `deleted_at/delete_reason`，不得让数据库引用悄悄消失。

生成凭证重建规则：

- Agent 汇总图无配送照片依赖，可根据 Settlement/SettlementLine 完整重建；
- 普通客户/ProxyRecipient 凭证在原配送照片仍存在时可完整重建；
- 原配送照片已清理时，只允许生成“无照片历史凭证”，保留位置、件数、时间、金额/费用明细，并明确提示照片已按数据保留策略清理。

ExceptionCase 与图片存在两类保护关系：

1. `ExceptionCaseAttachment → MediaFile`：异常直接上传的图片；
2. `ExceptionEvidenceLink → DeliveryEvidence/MediaFile`：异常引用已有配送、归拢等业务证据。

只要 MediaFile 被 OPEN ExceptionCase 直接或间接引用，自动清理必须跳过。

异常解决后的最早删除时间：

```text
delete_after = max(
    media.created_at + retention_days,
    exception.resolved_at + retention_days
)
```

因此即使图片在异常解决时已经超过 30 天，也至少从 `resolved_at` 起再保留完整一个 retention 周期。

管理员支持图片浏览、下载、手动删除、批量删除、查看空间占用。手动删除也必须阻止删除 OPEN 异常保护中的图片，除非先解决/解除异常关系并有明确审计。

## 4. 手动备份管理

管理员可以立即备份、下载、删除整个备份、只删除备份中的照片归档、查看大小和 manifest。

## 5. 恢复

只支持全量数据库/配置恢复，不做局部订单恢复。

恢复前自动创建 PRE_RESTORE 保护备份。

恢复页面显示备份时间、当前/备份记录规模、可能丢失的后续数据警告。

历史照片若已按策略清理，不应导致数据库恢复失败。

## 6. 维护模式

管理员可进入 MAINTENANCE：阻止普通业务写操作，管理员仍能查看、备份、恢复和退出维护。

真正 Docker/宿主机关机由运维命令完成，不给 Web 进程宿主机 shutdown 权限。

## 7. 异常断电/重启

启动 Recovery Check：

1. 检查 SQLite 可读写；
2. 检查 data 目录；
3. 清理孤立临时上传；
4. 识别未完成 JobRun；
5. 检查备份任务是否长时间未成功；
6. 清理 stale login lease；
7. 写启动审计。

不得把 PICKED/DELIVERING/DELIVERED 回退。

## 8. 文件原子性

上传先写 `/data/tmp`，校验/压缩完成后原子移动到正式 storage，然后才创建/绑定正式 MediaFile。

断电最多留下 tmp，不允许数据库引用半文件。

## 9. JobRun

至少：

- daily_backup；
- monthly_media_cleanup；
- stale_login_cleanup；
- tmp_cleanup。

每个 job 应保存开始、结束、状态、错误摘要、幂等 key。

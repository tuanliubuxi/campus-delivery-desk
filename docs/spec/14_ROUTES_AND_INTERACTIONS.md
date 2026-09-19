# 14. 页面路由与 HTMX 交互建议

## 1. 认证

```text
GET/POST /login/
GET/POST /login/admin/
POST     /logout/
POST     /session/heartbeat/
```

管理员：

```text
POST /admin-console/users/<id>/force-logout/
```

## 2. 录单员

```text
GET  /recorder/
GET  /recorder/orders/new/
POST /recorder/orders/new/<business_type>/
GET  /recorder/orders/continuous/<customer_id>/
POST /recorder/orders/quick-complete/

GET  /recorder/proxy/
POST /recorder/proxy/batches/new/
POST /recorder/proxy/batches/<id>/cancel/
POST /recorder/proxy/batches/<id>/reopen/
POST /recorder/proxy/batches/<id>/recipients/new/
POST /recorder/proxy/recipients/<id>/express/new/

GET  /recorder/customers/
GET  /recorder/orders/history/

GET  /recorder/settlements/<id>/
POST /recorder/settlements/build/
POST /recorder/settlements/<id>/charge-items/add/
POST /recorder/settlements/<id>/charge-items/<item_id>/void/
POST /recorder/settlements/<id>/preview/
POST /recorder/settlements/<id>/generate-image/   # freeze + WAITING_PAYMENT
POST /recorder/settlements/<id>/void/
POST /recorder/settlements/<id>/confirm/
POST /recorder/settlements/<id>/reverse/

POST /recorder/proxy/recipients/<id>/generate-receipt/
POST /recorder/proxy/batches/<id>/generate-summary/

GET/POST /recorder/exceptions/...
GET/POST /recorder/manual-handling/...
```

## 3. 配送员

```text
GET  /courier/
POST /courier/accepting/start/
POST /courier/accepting/stop/
POST /courier/business/select/

GET  /courier/tasks/
GET  /courier/tasks/new/

GET  /courier/express/route-pool/
POST /courier/express/route-claim/
GET  /courier/express/direct-pool/
POST /courier/express/direct-claim/

POST /courier/orders/<id>/picked/
POST /courier/orders/<id>/confirm-size/
POST /courier/tasks/<id>/start-delivery/
POST /courier/drops/complete/
POST /courier/media/<id>/annotate/

GET/POST /courier/transfers/...
GET/POST /courier/consolidations/...
POST /courier/consolidations/<id>/reassign/
GET/POST /courier/exceptions/...
```

## 4. 管理员

```text
GET /admin-console/
GET /admin-console/orders/
GET /admin-console/customers/
GET /admin-console/agents/
GET /admin-console/proxy-batches/
GET /admin-console/users/
GET /admin-console/config/
GET /admin-console/reports/
GET /admin-console/wages/
GET /admin-console/audit/
GET /admin-console/media/
GET /admin-console/backups/
GET /admin-console/maintenance/
```

正式业务 UI 不塞进 Django 自带 `/admin/`。

## 5. Dashboard 查询

```text
GET /admin-console/reports/?date_from=&date_to=&business_type=&courier=&source_type=&agent=&pickup_area=&size=&route=&urgent=&upstairs=&weather=&exception=&charge_type=
```

同一 query 参数对象应用于 cards/charts/table/export。

## 6. HTMX partial

适合：工作台 Tab、客户/代理搜索、路线池、任务卡、DRAFT 费用项编辑/作废、结算预览、归拢进度、Dashboard cards/table、时间线。

## 7. 业务错误 partial

至少覆盖：订单已被抢、状态已变化、账号已在线、缺取件地点/地址、快递大小未确认、缺位置/照片、业务类型不可切、非快递尝试代理来源、ProxyBatch 状态不允许追加、转单需要交接、工资分配超剩余可分配池。

## 8. 写操作

关键表单 hidden `operation_id=UUID`；首次点击立即 disabled/loading；失败保留表单/图片状态。

## 9. 页面刷新

不上 WebSocket。工作台/接单池可 HTMX polling 10～60 秒；关键提交后以服务端真实状态刷新。

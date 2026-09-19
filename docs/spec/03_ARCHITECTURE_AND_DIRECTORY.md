# 03. V1 架构、模块边界与目录结构

## 1. 总体架构

V1 为模块化 Django 单体：

```text
Browser / PWA
    ↓ HTTPS
Caddy
    ↓
Gunicorn + Django
    ↓
SQLite(WAL) + Local Media

独立 Scheduler
    ├─ 每日备份
    ├─ 月度图片清理
    └─ 会话租约清理/维护任务
```

## 2. Django App 边界

### `accounts`

User、角色、登录、单活跃会话租约、心跳、强制下线、接单开关、主题偏好。

### `customers`

普通长期客户档案、快照、重复客户提醒。

### `agents`

Agent、ProxyBatch、ProxyRecipient、代理录单工作流、代理凭证/汇总图关联。

### `config_center`

业务开关、价格、加急、特殊天气默认值、上楼规则、楼栋、路线顺序、KFC 默认开放日、快捷位置词、主题、分成。

### `orders`

公共 Order、6 类 Detail、ExpressRound、编号、录单、修改、取消、重复检查、快速完成/补录。ExpressRound 是快递“本轮”的唯一业务边界，供归拢、多件优惠和快递结算复用。

### `dispatch`

任务、Assignment、路线批次、客户直送、简单任务、取件、配送、转单、DeliveryDrop。

### `consolidation`

快递 ConsolidationRound、找件状态、最终位置与合照、归拢负责人独立改派。不得复用已完成订单的 Assignment/Transfer 表示归拢负责人变化。

### `settlements`

ChargeItem（ACTIVE/VOIDED）、Settlement、SettlementOrder、SettlementLine、FinancialAdjustment、凭证图片版本、CourierEarning、工资计算 DTO/服务。DRAFT 只固定订单和编辑费用；生成有效凭证时才冻结 SettlementLine。

### `exceptions`

异常 case、处理记录、人工处理。

### `mediafiles`

上传、压缩、缩略图、近景/远景/标注派生图、生命周期清理、受控下载。

### `audit`

Append-only AuditEvent 和实体时间线。

### `operations`

JobRun、BackupRecord、恢复、维护模式、启动 Recovery Check。

### `dashboard`

只读 selector：统一多维筛选、图表数据、Excel 导出。

## 3. 推荐目录

```text
campus-delivery-desk/
├─ manage.py
├─ pyproject.toml
├─ README.md
├─ LICENSE
├─ .env.example
├─ Dockerfile
├─ docker-compose.yml
├─ Caddyfile
│
├─ config/
│  ├─ urls.py
│  ├─ wsgi.py
│  └─ settings/
│     ├─ base.py
│     ├─ dev.py
│     └─ prod.py
│
├─ apps/
│  ├─ common/
│  │  ├─ enums.py
│  │  ├─ money.py
│  │  ├─ timezone.py
│  │  ├─ idempotency.py
│  │  └─ tests/
│  ├─ accounts/
│  │  ├─ models.py
│  │  ├─ forms.py
│  │  ├─ views.py
│  │  ├─ services/
│  │  │  ├─ login.py
│  │  │  ├─ heartbeat.py
│  │  │  └─ force_logout.py
│  │  ├─ selectors/
│  │  └─ tests/
│  ├─ customers/
│  ├─ agents/
│  │  ├─ models/
│  │  │  ├─ agent.py
│  │  │  ├─ proxy_batch.py
│  │  │  └─ proxy_recipient.py
│  │  ├─ services/
│  │  ├─ selectors/
│  │  └─ tests/
│  ├─ config_center/
│  ├─ orders/
│  │  ├─ models/
│  │  │  ├─ order.py
│  │  │  ├─ express.py
│  │  │  ├─ express_round.py
│  │  │  ├─ takeout.py
│  │  │  ├─ kfc.py
│  │  │  ├─ grocery.py
│  │  │  ├─ errand.py
│  │  │  └─ luggage_upstairs.py
│  │  ├─ services/
│  │  │  ├─ create_express.py
│  │  │  ├─ create_simple.py
│  │  │  ├─ update.py
│  │  │  ├─ cancel.py
│  │  │  ├─ duplicate_check.py
│  │  │  ├─ numbering.py
│  │  │  └─ quick_complete.py
│  │  ├─ selectors/
│  │  ├─ forms/
│  │  └─ tests/
│  ├─ dispatch/
│  │  ├─ models/
│  │  │  ├─ task.py
│  │  │  ├─ assignment.py
│  │  │  ├─ route_batch.py
│  │  │  ├─ transfer.py
│  │  │  └─ delivery_drop.py
│  │  ├─ services/
│  │  │  ├─ claim.py
│  │  │  ├─ pickup.py
│  │  │  ├─ start_delivery.py
│  │  │  ├─ complete_drop.py
│  │  │  ├─ return_to_pool.py
│  │  │  └─ transfer.py
│  │  └─ selectors/
│  ├─ consolidation/
│  ├─ settlements/
│  │  ├─ models/
│  │  │  ├─ charge_item.py
│  │  │  ├─ settlement.py
│  │  │  ├─ settlement_order.py
│  │  │  ├─ settlement_line.py
│  │  │  ├─ adjustment.py
│  │  │  └─ earning.py
│  │  ├─ services/
│  │  │  ├─ pricing.py
│  │  │  ├─ build.py
│  │  │  ├─ freeze.py
│  │  │  ├─ void.py
│  │  │  ├─ confirm.py
│  │  │  ├─ proxy_receipts.py
│  │  │  └─ wages.py
│  │  └─ selectors/
│  ├─ exceptions/
│  ├─ mediafiles/
│  ├─ audit/
│  ├─ operations/
│  └─ dashboard/
│     ├─ filters.py
│     ├─ selectors/
│     ├─ exports/
│     └─ tests/
│
├─ templates/
│  ├─ layouts/
│  │  ├─ desktop.html
│  │  ├─ mobile.html
│  │  └─ courier_mobile.html
│  ├─ components/
│  ├─ accounts/
│  ├─ recorder/
│  ├─ courier/
│  ├─ proxy/
│  └─ admin_console/
│
├─ static/
│  ├─ css/
│  │  ├─ tokens.css
│  │  ├─ app.css
│  │  └─ themes/
│  ├─ js/
│  │  ├─ htmx-init.js
│  │  ├─ heartbeat.js
│  │  ├─ image-compress.js
│  │  ├─ image-annotate.js
│  │  └─ draft.js
│  └─ pwa/
│
├─ tests/
├─ scripts/
└─ docs/
```

## 4. 模块依赖方向

推荐：

```text
accounts/customers/agents/config_center
              ↓
            orders
              ↓
           dispatch
              ↓
        consolidation
              ↓
         settlements
              ↓
     dashboard / operations
```

`audit`、`mediafiles` 是横向基础能力，但不得反过来改变业务状态。

## 5. 避免循环依赖

- Order 不直接 import Dashboard。
- Dashboard 只读。
- MediaFile 只提供文件引用，不决定配送是否完成。
- Agent/ProxyRecipient 通过明确 FK 与订单关联，不把代理逻辑塞进 Customer。
- ChargeItem 是业务费用来源。自动业务费用绑定 Order；结算时人工/可选费用绑定当前 Settlement，并可额外记录 Customer/ProxyRecipient/ExpressRound 作为归属维度。DRAFT 只固定订单集合，生成有效结算凭证时只读取“当前 SettlementOrder 的订单级费用 + 当前 settlement_id 的结算级费用”，再复制成不可变 SettlementLine。订单不保存可直接覆盖的 final total。

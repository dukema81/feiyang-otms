# 飞洋海洋运输管理系统（FeiYang OTMS）设计方案 v1.0

## 1. 系统定位

面向中小航运/货代企业的海洋运输管理系统（Ocean Transport Management System），覆盖
**港口档案 → 船舶管理 → 航次调度 → 订舱 → 提单 → 集装箱箱货跟踪 → 运价管理 → 应收应付 → 风险预警**
的完整业务闭环。零依赖架构（Python 标准库 + SQLite WAL + 原生 JS SPA），单进程可运行，
预留 REST API 供 ERP/货代平台/口岸系统对接。

## 2. 技术架构

| 层 | 选型 |
|---|---|
| 服务 | `http.server.ThreadingHTTPServer`，端口 8031，nginx 前缀 `/ocean/` |
| 数据 | SQLite WAL 模式，30 次锁重试；环境变量 `OY_PORT` / `OY_DB` / `OY_PREFIX` |
| 内核 | `ocean.py` 纯函数业务内核（无 IO 可独立单测） |
| 前端 | 原生 JS SPA，12 页，海洋蓝主题（#0e7490） |
| 鉴权 | Cookie Token / Bearer / X-Token / API Key（`fyo_` 前缀）/ 五通道 |
| 对接 | 幂等键（Idempotency-Key）、增量同步（since 版本号）、CSV 导出 |

## 3. 业务域

### 3.1 港口档案 ports
UN/LOCODE 编码（如 CNSHA 上海、SGSIN 新加坡），名称、国家、状态。
被航次/订舱/运价引用后禁止删除。

### 3.2 船舶 vessels
编码、船名、IMO 号（7 位数字，唯一）、船型（container 集装箱/bulk 散货/tanker 油轮/roro 滚装）、
载重吨 DWT、箱位 TEU、船旗、状态。航次引用后禁删。

### 3.3 航次 voyages
航次号（唯一）、船舶、起运港 POL / 目的港 POD、ETD/ETA 计划、ATD/ATA 实际。
状态机 `VOYAGE_TRANS`：`planned → departed → arrived → closed`，`planned → cancelled`。
离港校验：航次必须挂集装箱方可 departed（软校验）；闭环校验：arrived 方可 closed。

### 3.4 订舱 bookings
订舱号（BK+日期+序号）、航次、托运人（partner）、收货人、POL/POD（默认取航次）、
货物描述、箱数、箱型。状态机 `BOOKING_TRANS`：
`booked → loaded → shipped → delivered`，booked/loaded 可 `cancelled`。
订舱属某航次后随航次状态推进。

### 3.5 集装箱 containers
箱号 ISO 6346（4 字母 + 6 数字 + 校验位，内核做校验位验证）、箱型（20GP/40GP/40HQ/20RF/40RF/45HC）、
封号、所属航次/订舱。状态机 `CONTAINER_TRANS`：
`empty → full → in_transit → unloaded → returned`（full 可直接 returned 退租）。
滞箱计算：以 unloaded_at 为基准、returned_at 回归，超免箱期产生滞箱费。

### 3.6 提单 bills_of_lading
提单号（BL+日期+序号）、订舱、托运/收货/通知人、货物、箱数。
状态机 `BL_TRANS`：`draft → issued → surrendered | telex_released`。
一订舱可多提单（分单）；订舱取消则提单禁发。

### 3.7 运价 rates
航线（POL+POD）× 箱型 的基础运价 base_cents + 附加费 surcharge_cents，有效期 valid_from/to。
报价计算 `freight_quote`：total = (base + surcharge) × TEU 系数 × 箱数；
引用过期运价时拒绝（rate_valid）。

### 3.8 客户/伙伴 partners
客户/货代/船代/供应商，信用额度，应收应付累计（沿用飞售/飞融范式）。

### 3.9 应收应付 bills / bill_settlements
运费账单（AR/AP），部分/全额结算，截断至未结余额，可联动资金账户生成流水。
滞箱费账单 demurrage 类型纳入应收。

### 3.10 风险 risks（四类扫描）
| 类型 | 触发条件 | 分值 |
|---|---|---|
| demurrage_over | 箱已卸货超免箱期 N 天未回归 | 40 |
| bill_overdue | 应收账单逾期（含账龄 0-30/31-60/61-90/91-180/180+） | 40 |
| voyage_overload | 航次装载 TEU 超船舶箱位 | 45 |
| rate_expired | 7 天内到期/已过期且仍被活跃订舱引用的运价 | 25 |

去重：同型同 ref 已 open 不重复建。

## 4. 数据模型（17 表）

ports, vessels, voyages, bookings, containers, bls, rates, partners, bills,
bill_settlements, flows(结算联动流水), risks, users, tokens, api_keys, notices,
logs + idem_keys/sync_state/oy_rules/seq（平台表）。

关键约束：
- vessels.imo / containers.container_no 唯一
- voyages.no / bookings.no / bls.no 唯一（make_no 序列）
- ports/vessels/rates 引用保护
- 过账式状态推进均 `version=version+1` + `bump_sync`

## 5. 内核 ocean.py 纯函数

| 函数 | 说明 |
|---|---|
| money_to_cents / line_amount_cents | 金额分转换（HALF_UP） |
| container_no_valid / container_check_digit | ISO 6346 校验位 |
| teu_of(ctype) | 20ft=1.0，40/45ft=2.0 |
| voyage_load_check(loaded_teu, vessel_teu) | 超载判定 |
| demurrage_days(unloaded, returned, free_days) | 滞箱天数 = max(0, 占用-免箱) |
| demurrage_fee(days, rate_cents, tiers) | 阶梯滞箱费（1-4 天×1，5-8 天×2，9+ 天×4） |
| freight_quote(base, sur, ctype, boxes) | 报价 = (base+sur)×teu×boxes |
| rate_valid(today, from, to) | 运价有效期 |
| VOYAGE/BOOKING/CONTAINER/BL_TRANS + can_transition | 四状态机 |
| aging_bucket / days_overdue | 账龄 |
| bill_remaining / settle_amount | 结算 |
| ROLE_PERMS / has_perm | sea.* 六角色权限 |
| voyage_stats | 看板统计 |

## 6. 角色权限（前缀 sea.*）

admin(*) / ops 操作(sea.voyages.*, sea.bookings.*, sea.containers.*, sea.vessels.*, sea.reports.read)
/ finance 财务(sea.bills.*, sea.partners.*, sea.rates.read, sea.reports.read)
/ doc 单证(sea.bls.*, sea.bookings.read, sea.containers.read)
/ agent 代理(sea.bookings.create + read, sea.bls.read, sea.track.read)
/ reader 只读。

## 7. 对接能力（留作外部系统）

- API Key + `sea.*` 细粒度权限，供 ERP/货代平台调用
- `Idempotency-Key` 幂等写
- `GET /api/sync?since=&entities=` 增量同步（实体版本号）
- `GET /api/export/{entity}` CSV（UTF-8 BOM，Excel 直开）
- 订舱/提单/箱号全链路可被外部跟踪系统拉取（`/api/track/{no}`）

## 8. 部署

systemd `feiyang-otms`（OY_PORT=8031，DB /opt/feiyang-otms/data/feiyang.db），
nginx `location /ocean/`，健康检查 `/api/health`。

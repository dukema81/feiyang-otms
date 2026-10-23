# 飞洋 OTMS API 契约 v1.0

Base：`http://<host>:8031`（nginx：`http://<host>/ocean/`）。
统一响应 `{"code":200,"message":"ok","data":...}`；错误 401/403/404/409/422/500 同码。
分页：`?page=1&size=20` → `{"items":[],"total":n,"page":p,"size":s}`。

## 0. 鉴权五通道
1. `Authorization: Bearer <token>`
2. `X-Token: <token>`
3. Cookie `feiyang_token`
4. `X-Api-Key: fyo_xxx`（perms `sea.*`）
5. `?token=`（导出/轮询场景）

登录 `POST /api/login {username,password}` → `{token,user,perms}`；
`GET /api/me`；`POST /api/logout`；`GET /api/health` 无鉴权。

## 1. 港口 ports
| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | /api/ports?keyword=&country= | sea.ports.read | 分页列表 |
| POST | /api/ports {code,name,country} | sea.ports.write | code 唯一(UN/LOCODE) |
| PUT | /api/ports/{id} {name,country,status} | sea.ports.write | |
| DELETE | /api/ports/{id} | sea.ports.write | 被航次/运价引用 409 |

## 2. 船舶 vessels
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/vessels?vtype=&keyword= | 列表 |
| POST | /api/vessels {code,name,imo,vtype,dwt,teu,flag} | imo 7 位数字唯一；vtype container/bulk/tanker/roro |
| PUT | /api/vessels/{id} | 名称/箱位/状态等 |
| DELETE | /api/vessels/{id} | 有航次 409 |
| GET | /api/vessels/{id}/voyages | 该船航次 |

## 3. 航次 voyages
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/voyages?status=&vessel_id=&month= | 列表（extra：vessel_name/pol/pod 名、loaded_teu） |
| POST | /api/voyages {no?,vessel_id,pol_id,pod_id,etd,eta} | no 默认 VO+日期+seq |
| GET | /api/voyages/{id} | 详情含订舱/箱列表 |
| PUT | /api/voyages/{id} {etd,eta,atd,ata} | planned 可改 |
| POST | /api/voyages/{id}/transition {action} | to_departed/to_arrived/to_closed/to_cancelled；状态机校验 422 |
| DELETE | /api/voyages/{id} | 仅 planned/cancelled 且无订舱 |

## 4. 订舱 bookings
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/bookings?status=&voyage_id=&partner_id= | 列表 |
| POST | /api/bookings {voyage_id,shipper_id,consignee,cargo_desc,boxes,ctype} | 生成 BK 号；航次须 planned |
| GET | /api/bookings/{id} | 详情含提单/箱 |
| PUT | /api/bookings/{id} | booked 可改 |
| POST | /api/bookings/{id}/transition | to_loaded/to_shipped/to_delivered/to_cancelled |
| DELETE | /api/bookings/{id} | 仅 booked/cancelled 且无提单无箱 |

## 5. 集装箱 containers
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/containers?status=&voyage_id=&ctype= | 列表（extra：滞箱天数/费） |
| POST | /api/containers {container_no,ctype,seal_no,voyage_id,booking_id} | ISO 6346 校验 422；箱号唯一 409 |
| POST | /api/containers/{id}/transition | to_full/to_in_transit/to_unloaded/to_returned |
| PUT | /api/containers/{id} | seal_no 等可改（in_transit 后禁改 seal） |
| DELETE | /api/containers/{id} | 仅 empty/full |
| GET | /api/containers/{id}/demurrage?free_days=&rate_cents= | 滞箱测算 |

## 6. 提单 bls
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/bls?status=&booking_id= | 列表 |
| POST | /api/bls {booking_id,shipper,consignee,notify_party,cargo_desc,boxes} | BL 号；订舱须非 cancelled |
| POST | /api/bls/{id}/transition | to_issued/to_surrendered/to_telex_released（draft 才可改字段） |
| PUT | /api/bls/{id} | draft 可改 |
| DELETE | /api/bls/{id} | 仅 draft |

## 7. 运价 rates
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/rates?pol_id=&pod_id=&ctype= | 列表（extra：expired 标记） |
| POST | /api/rates {pol_id,pod_id,ctype,base_cents,surcharge_cents,valid_from,valid_to} | 有效期校验 from<=to |
| PUT | /api/rates/{id} | 价格/有效期 |
| DELETE | /api/rates/{id} | 被活跃订舱引用 409 |
| GET | /api/rates/quote?pol_id=&pod_id=&ctype=&boxes= | 实时报价；无有效运价 404 |

## 8. 客户 partners / 应收应付 bills
partners CRUD + `/api/partners/{id}/bills`；
bills CRUD + `/api/bills/{id}/settle {amount_cents,method,account_id}`（部分/全额、截断、
联动账户余额并生成流水、冲减往来余额、信用超限自动建险）。
btype 增加 `demurrage`（滞箱费应收）。

## 9. 报表 / 跟踪
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/reports/voyage-summary?month= | 航次汇总：艘次/TEU/订舱/delivered |
| GET | /api/reports/lane-stats?month= | 航线统计：POL→POD 票数/箱量/运费 |
| GET | /api/track/{no} | 按订舱号/提单号/箱号 追全链路事件 |

## 10. 风险
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/risks?status=&grade= | 列表 |
| POST | /api/risks/scan | 四类扫描（去重 open） |
| PUT | /api/risks/{id}/resolve {note} | 处理 |

## 11. 平台域
dashboard、notices CRUD、logs、rules、
`GET /api/sync?since=&entities=ports,vessels,...` 增量同步、
`GET /api/export/{ports|vessels|voyages|bookings|containers|bls|rates|bills}` CSV（BOM）。
用户/API Key 管理同标准契约（perms 默认 sea.*）。

## 12. ERP 对接示例
```bash
curl -X POST https://host/ocean/api/api-keys -H "X-Token: $T" -d '{"name":"erp","perms":"sea.bookings.*,sea.bls.read"}'
curl -X POST https://host/ocean/api/bookings -H "X-Api-Key: fyo_xxx" -H "Idempotency-Key: erp-so-1001" \
  -d '{"voyage_id":1,"shipper_id":1,"cargo_desc":"冷柜火龙果","boxes":2,"ctype":"40RF"}'
curl "https://host/ocean/api/sync?since=42&entities=bookings,containers" -H "X-Api-Key: fyo_xxx"
```

# 飞洋海洋运输管理系统测试报告

## 一、测试范围与结论

| 门禁 | 数量 | 结果 |
| --- | --- | --- |
| 单元测试 pytest（内核 ocean.py） | 22 例 | 全部通过 |
| API 集成测试 pytest（server.py） | 16 例（38 项断言级） | 全部通过 |
| 冒烟测试 smoke_api.py 全链路 | 79 项（连跑 3 次） | 全部通过 |
| UI 巡检 Playwright 12 页面 | 12 页 | 全部通过 |
| 离线 DEMO 页面巡检 | 12 页 | 全部通过 |

结论：四道质量门禁全部通过，放行部署。

## 二、内核单元测试（22 例）

- 金额口径：元转分、行金额 = 单价 × 数量、Decimal HALF_UP 一次量化
- ISO 6346 集装箱校验位：字母值从 10 顺序 +1 并跳过 11 的倍数（I/O/Q 由取值规则自然排除），前 10 位加权 2^0..2^9 mod 11；以知名真实箱号 CSQU3054383（有效）与 CSQU3054380（无效）双向验证
- TEU 折算：20ft=1.0，40/45ft=2.0；箱量×航次装载校验 voyage_load_check 与 voyage_stats
- 滞箱费：demurrage_days = max(0, 占用-免箱)（默认免箱 4 天），阶梯费率 (1-4 天 200/天，5-8 天 400/天，9 天起 800/天，单位分)
- 运价：freight_quote = (基础 + 附加费) × TEU × 箱量；rate_valid 有效期与临期天数
- 状态机四套：航次 planned→departed→arrived→closed（+取消）、订舱 booked→loaded→shipped→delivered（+取消）、集装箱 empty→full→in_transit→unloaded→returned、提单 draft→issued→surrendered/telex_released
- 账龄五桶、逾期天数、账单余额与结算截断 settle_amount
- 权限 ROLE_PERMS：admin/ops/finance/doc/agent/reader，通配符、write 隐含同实体 read
- 信用超限 over_credit

## 三、API 集成测试（16 例，38 项断言）

- 认证与 RBAC：六角色正向放行 + 越权 403 双向验证
- 港口：CRUD、code 正则 ^[A-Z][A-Z0-9]{4}$ 422、重复 409、被航次/运价引用禁删
- 船舶：IMO 7 位数字格式校验与唯一 409、有航次禁删
- 航次生命周期：合法迁移链、非法迁移 422、超载禁止离港
- 订舱：创建含装载预检（超载 422）、状态联动（loaded 联动箱 in_transit、delivered 联动箱 unloaded+时间戳）
- 集装箱：ISO 6346 校验 422、生命周期迁移、在途禁改封号、滞箱费计算
- 提单：draft→issued→surrendered/telex_released
- 运价：报价断言（20GP 双箱 9400000 分）、无有效运价 404、valid_from > valid_to 422
- 账单与结算：部分结算、全额结算、超额截断、结算生成资金流水并冲减往来
- 风险扫描：四类风险（滞箱超期/账单逾期/航次超载/运价到期），同型同引用去重、resolve 处理
- 报表与跟踪：航次汇总、航线统计、按订舱/提单/箱号跟踪时间线
- 平台域：幂等订舱、增量同步、CSV 导出、用户与 API Key（fyo_ 前缀、权限 403）

## 四、冒烟测试（79 项，连跑 3 次）

12 段全链路：登录 → 港口 → 船舶 → 航次 → 订舱 → 装箱 → 提单 → 运价 → 账单结算 → 风险 → 报表/跟踪 → 平台域。脚本内置动态生成 ISO 6346 合法箱号与唯一端口/船舶编码，支持连续重复执行。

## 五、UI 巡检与 DEMO

- Playwright 登录 + 12 页面（工作台/船舶/航次/订舱/提单/箱货/运价/往来/账单/跟踪/风险/系统）文本非空、0 控制台异常
- 离线 DEMO 单文件 HTML 快照 12 页面全部渲染正常，支持 6 视角切换

## 六、缺陷清单（已全部修复）

| # | 缺陷 | 修复 |
| --- | --- | --- |
| 1 | ISO 6346 字母取值误按"跳过 I/O/Q"实现，CSQU3054383 判无效 | 改为从 10 顺序 +1、跳过 11 的倍数 |
| 2 | 工作台 SQL 引用不存在列导致 500 | 移除占位坏 SQL，逐航次累加滞箱费 |
| 3 | 跟踪页按订舱号查询缺 bk 分支返回空 | h_track 重写，补订舱/航次/箱/提单五类事件 |
| 4 | has_perm write 不隐含同实体 read | 权限判定补隐含规则 |
| 5 | 账单创建引用缺失的 over_credit 500 | 内核补函数 |
| 6 | 港口 code 正则过严拒绝字母开头的 5 位混合码 | 改 ^[A-Z][A-Z0-9]{4}$ |
| 7 | 测试夹具 jreq 返回值解包不一致（15 fail） | 统一返回 (status, parsed) 元组 |
| 8 | /api/flows 路由缺失 404 | 补 handler 与路由表项 |

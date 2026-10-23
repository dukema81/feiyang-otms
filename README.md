# FeiRong FMS 飞融金融管理系统

零依赖（Python 标准库 + SQLite）的轻量金融/财务管理系统。

## 功能

- **账套与科目**：多账套、五类科目（资产/负债/权益/成本/收入），发生额保护
- **凭证**：借贷平衡强校验、草稿→过账/作废状态机、过账累加科目发生额
- **报表**：科目余额表、利润表、资产负债表（含平衡校验）、期间过滤
- **账户与流水**：账户余额联动、流水冲回
- **往来与账单**：应收应付、账龄（0-30/31-60/61-90/91-180/180+）、部分/全额结算联动
- **发票**：价税分离（净价/含税双口径）
- **预算**：期间预算与使用率告警（≥90% 提醒、>100% 风险）
- **风险扫描**：预算超支 / 账单逾期 / 账户透支 / 信用超限
- **开放能力**：API Key 鉴权、幂等键、增量同步、CSV 导出，约 70 个 REST 端点
- **RBAC**：admin / accountant / treasurer / ar_ap / auditor / reader 六角色细粒度权限

## 运行

```bash
cd backend
FIN_PORT=8030 FIN_DB=../data/feirong.db python3 server.py
```

访问 `http://127.0.0.1:8030/`，默认账号见 `backend/seed.py`（初始密码 123456）。

## 测试

```bash
python -m pytest tests/ -q   # 68 例全绿
python tools/smoke_api.py    # 冒烟 70 项
python tools/ui_check.py     # UI 12 页
```

## 目录

```
backend/   服务与财务内核（fin.py 纯函数）
frontend/  原生 JS SPA（12 页）
tests/     单测 + API 测试（68 例）
tools/     冒烟/UI/DEMO/文档/知识库工具
docs/      设计/API/测试/用户手册
demo/      离线单文件 DEMO（6 视角）
```

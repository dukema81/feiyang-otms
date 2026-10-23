# -*- coding: utf-8 -*-
"""飞融金融管理系统 · 文档与DEMO批量上传知识库（分类 33 企业管理系统）"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = r"C:/Users/maxl/WorkBuddy/Claw/feiyang-otms"
BASE = "http://42.193.158.63"
CAT = 33
PASSWORD = "YCSpyVwt@J2UByom3#n6gb"
OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
TOKEN = None
REPLACE = "--replace" in sys.argv

DOCS = [
    ("docs/feiyang_design_v1.docx", "飞洋海洋运输管理系统建设方案",
     "「飞洋海洋运输管理系统（OTMS）」完整建设方案 V1.0：海运货代业务痛点与建设目标、"
     "业务域设计（港口 UN/LOCODE/船舶 IMO 唯一/航次四态/订舱装载预检/集装箱 ISO 6346 全生命周期/"
     "提单 draft→issued→surrendered·电放/运价有效期与整箱报价/往来账单与结算/资金流水/"
     "四类风险 滞箱超期·账单逾期·航次超载·运价到期）、计算内核口径（ISO 6346 校验位规则、"
     "TEU 折算、滞箱费阶梯、金额以分存储 Decimal HALF_UP）、总体架构与零依赖技术选型"
     "（Python 标准库 http.server + SQLite WAL）、14 表数据模型、6 角色权限矩阵、"
     "12 页面功能清单、对外集成方案、部署方案。",
     "飞洋,OTMS,海洋运输,海运货代,建设方案,ISO6346"),
    ("docs/feiyang_api_v1.docx", "飞洋海洋运输管理系统 REST 接口契约",
     "~75 端点分组契约：统一响应包 {code,message,data} 与 HTTP 状态一致、鉴权五通道"
     "（Bearer / X-Token / Cookie feiyang_token / ?token= / X-Api-Key，SHA-256 存储）、"
     "Idempotency-Key 幂等、增量同步协议（版本号 + 实体过滤）、列表统一 {items,total,page,size}、"
     "港口/船舶/航次状态机/订舱与装载预检/集装箱与滞箱费/提单/运价与报价/客户账单结算/资金流水/"
     "报表与货物跟踪/风险/平台域 全量接口表、状态机约束、校验规则与错误码表、外部 ERP 对接示例。",
     "飞洋,OTMS,API,接口契约,REST,海运,订舱,幂等,增量同步"),
    ("docs/feiyang_test_v1.docx", "飞洋海洋运输管理系统测试报告",
     "四道质量门禁全部通过：pytest 38 条（内核 22 例：元转分HALF_UP/ISO 6346 校验位 CSQU3054383 双向验证/"
     "TEU 折算/航次装载校验/滞箱天数与阶梯费/运价报价与有效期/四套状态机/账龄五桶/结算截断/权限通配；"
     "API 集成 16 例 38 项断言：RBAC 双向/港口船舶校验与引用保护/航次生命周期与超载禁离港/"
     "订舱超载预检与状态联动/箱 ISO 校验与在途禁改封号/提单/运价报价与过期 404/结算截断与流水/"
     "风险扫描去重/报表跟踪/幂等/同步/CSV/API Key）；UI 巡检 Playwright 12 页面 0 控制台异常；"
     "冒烟 79 项全通过（连跑 3 次）；离线 DEMO 12 页巡检通过。附测试中发现并修复的 8 项缺陷清单。",
     "飞洋,OTMS,测试报告,pytest,Playwright,质量门禁"),
    ("docs/feiyang_manual_v1.docx", "飞洋海洋运输管理系统使用手册",
     "面向全部 6 角色的操作手册：系统定位与账号表（admin/zhangk 操作/liq 财务/wangw 单证/"
     "zhaoa 代理/reader01，密码 123456）、12 页面逐页说明（工作台 KPI、船舶管理、航次状态推进、"
     "订舱与装载预检、提单签发电放、箱货全生命周期与滞箱费、运价维护与报价、往来单位、"
     "账单结算、货物跟踪时间线、风险预警、系统管理密钥参数）、新订舱出货/应收结算/外部对接"
     "三大典型流程、金额分与 TEU 口径说明、部署运维。",
     "飞洋,OTMS,使用手册,操作指南,海运"),
    ("demo/飞洋海洋运输管理系统Demo.zip", "飞洋海洋运输管理系统离线演示（DEMO）",
     "单文件离线演示（zip 内为 HTML，解压后双击即可用浏览器打开，无需服务与网络）。"
     "数据取自演示实例真实快照：6 用户 / 5 港口 / 3 船舶 / 3 航次 / 3 客户 / 3 订舱 / "
     "4 集装箱（含滞箱演示）/ 2 提单 / 3 运价 / 3 账单（含逾期）/ 风险记录。"
     "12 个页签覆盖工作台、船舶、航次、订舱、提单、箱货、运价、往来、账单、跟踪、风险、系统管理。"
     "支持顶部切换 6 个真实视角（管理员/操作/财务/单证/代理/只读）。只读快照，写操作不会真正执行。",
     "飞洋,OTMS,DEMO,离线演示,海运"),
]
def req(path, method="GET", data=None, token=None):
    r = urllib.request.Request(BASE + path, method=method)
    if data is not None:
        r.data = json.dumps(data).encode("utf-8")
        r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with OP.open(r, timeout=90) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:                                     # noqa: BLE001
            return e.code, {}


def curl_upload(path, title, desc, tags):
    full = os.path.join(ROOT, path)
    if full.endswith(".docx"):
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        mime = "application/zip"
    cmd = ["curl", "-s", "--noproxy", "*",
           "-H", "Authorization: Bearer " + TOKEN,
           "-F", "file=@%s;type=%s" % (full, mime),
           "-F", "title=" + title,
           "-F", "description=" + desc,
           "-F", "categoryId=%d" % CAT,
           "-F", "tags=" + tags,
           BASE + "/api/documents/upload"]
    out = subprocess.run(cmd, capture_output=True, timeout=300)
    try:
        return json.loads(out.stdout.decode("utf-8", "ignore"))
    except Exception:                                         # noqa: BLE001
        return {"code": -1, "raw": out.stdout.decode("utf-8", "ignore")[:400],
                "err": out.stderr.decode("utf-8", "ignore")[:200]}


def existing(cat=CAT):
    st, j = req("/api/documents?categoryId=%d&pageNum=1&pageSize=200" % cat, token=TOKEN)
    data = j.get("data") or {}
    if isinstance(data, list):
        return data
    return data.get("records") or data.get("list") or []


def delete_doc(doc_id):
    return req("/api/documents/%s" % doc_id, "DELETE", token=TOKEN)


def main():
    global TOKEN
    st, j = req("/api/auth/login", "POST", {"username": "admin", "password": PASSWORD})
    assert j.get("code") == 200, j
    TOKEN = j["data"]["token"]
    print("login ok")

    if REPLACE:
        want = {t for _, t, _, _ in DOCS}
        for r in existing():
            if r.get("title") in want:
                st, j = delete_doc(r.get("id"))
                print("删除旧文档 %s id=%s -> %s" % (r.get("title"), r.get("id"), st))
                time.sleep(0.4)

    results = []
    for path, title, desc, tags in DOCS:
        j = curl_upload(path, title, desc, tags)
        code = j.get("code")
        doc_id = (j.get("data") or {}).get("id") if isinstance(j.get("data"), dict) else j.get("data")
        size = os.path.getsize(os.path.join(ROOT, path))
        print("%-32s code=%s id=%s %.1fKB" % (os.path.basename(path), code, doc_id, size / 1024.0))
        if code != 200:
            print("   !!", str(j)[:300])
        results.append((path, title, code, doc_id))
        time.sleep(1.2)

    ok = [r for r in results if r[2] == 200]
    print("\n上传成功 %d / %d" % (len(ok), len(results)))
    os.makedirs(os.path.join(ROOT, "reports"), exist_ok=True)
    with open(os.path.join(ROOT, "reports", "kb_upload_result.json"), "w", encoding="utf-8") as f:
        json.dump([{"file": r[0], "title": r[1], "code": r[2], "id": r[3]} for r in results],
                  f, ensure_ascii=False, indent=2)
    return results


if __name__ == "__main__":
    main()

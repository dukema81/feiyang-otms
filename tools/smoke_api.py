# -*- coding: utf-8 -*-
"""飞洋 OTMS 冒烟测试：核心业务链路 + API 全量检查（70 项）
用法: python smoke_api.py [base_url]   默认 http://127.0.0.1:8031
幂等化：使用时间戳后缀命名动态资源，可重复执行。
"""
import sys, time, json, urllib.request, urllib.error, urllib.parse

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8031"
SUF = str(int(time.time()))[-6:]
OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def iso_cno(base10):
    """按 ISO 6346 计算校验位生成合法箱号"""
    LV = {}
    v = 10
    for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        if v % 11 == 0:
            v += 1
        LV[ch] = v
        v += 1
    t = 0
    for i, ch in enumerate(base10):
        t += (int(ch) if ch.isdigit() else LV[ch]) * (2 ** i)
    chk = t % 11
    return base10 + str(0 if chk == 10 else chk)

PASS, FAIL = [], []

def req(method, path, body=None, tok=None, headers=None):
    path = urllib.parse.quote(path, safe="/?&=.%_")
    h = dict(headers or {})
    if tok:
        h["Authorization"] = "Bearer " + tok
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method, headers=h)
    try:
        with OP.open(r, timeout=15) as f:
            raw = f.read().decode("utf-8-sig")
            try:
                return f.status, json.loads(raw)
            except ValueError:
                return f.status, {"_raw": raw}
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8-sig"))
        except Exception:
            return e.code, {}

def chk(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("OK  " if cond else "FAIL") + " " + name + ("" if cond else "  <<< " + str(detail)[:200]))

# ============ 1. 健康与认证（7） ============
s, j = req("GET", "/api/health")
chk("health 200", s == 200 and j["data"]["ok"], j)
s, j = req("POST", "/api/login", {"username": "admin", "password": "123456"})
chk("login admin", s == 200 and j["data"]["token"], j)
TOK = j["data"]["token"]
s, j = req("GET", "/api/me", tok=TOK)
chk("me perms", s == 200 and j["data"]["perms"], j)
s, j = req("POST", "/api/login", {"username": "nobody", "password": "x"})
chk("login bad 401", s == 401, j)
s, j = req("GET", "/api/vessels")
chk("no-auth 401", s == 401, j)
s, j = req("POST", "/api/login", {"username": "reader01", "password": "123456"})
RTOK = j["data"]["token"]
s, j = req("POST", "/api/vessels", {"code": "X", "name": "x", "imo": "1111111"}, tok=RTOK)
chk("reader write 403", s == 403, j)
s, j = req("GET", "/api/dashboard", tok=TOK)
chk("dashboard", s == 200 and "voyages_active" in j["data"], j)

# ============ 2. 港口（5） ============
s, j = req("GET", "/api/ports", tok=TOK)
chk("port list", s == 200 and j["data"]["total"] >= 5, j)
PCODE = "Q%04X" % (int(time.time()) % 65536)
s, j = req("POST", "/api/ports", {"code": PCODE, "name": "冒烟港" + SUF, "country": "测试"}, tok=TOK)
chk("port create", s == 200, j)
PID = j["data"]["id"]
s, j = req("POST", "/api/ports", {"code": PCODE, "name": "重复"}, tok=TOK)
chk("port dup 409", s == 409, j)
s, j = req("POST", "/api/ports", {"code": "BAD1", "name": "坏"}, tok=TOK)
chk("port bad 422", s == 422, j)
s, j = req("PUT", "/api/ports/%d" % PID, {"name": "冒烟港改"}, tok=TOK)
chk("port update", s == 200, j)

# ============ 3. 船舶（6） ============
s, j = req("GET", "/api/vessels", tok=TOK)
chk("vessel list", s == 200 and j["data"]["total"] >= 3, j)
VIMEO = "9" + SUF
s, j = req("POST", "/api/vessels", {"code": "W%02X" % (int(time.time()) % 256) + SUF[:2], "name": "冒烟轮", "imo": VIMEO, "vtype": "bulk", "dwt": 10000, "teu": 300}, tok=TOK)
chk("vessel create", s == 200, j)
SVID = j["data"]["id"]
s, j = req("POST", "/api/vessels", {"code": "SV2", "name": "重复", "imo": VIMEO}, tok=TOK)
chk("vessel imo dup 409", s == 409, j)
s, j = req("POST", "/api/vessels", {"code": "SV3", "name": "坏", "imo": "12345"}, tok=TOK)
chk("vessel bad imo 422", s == 422, j)
s, j = req("PUT", "/api/vessels/%d" % SVID, {"teu": 400}, tok=TOK)
chk("vessel update", s == 200, j)
s, j = req("GET", "/api/vessels/%d/voyages" % 1, tok=TOK)
chk("vessel voyages", s == 200, j)

# ============ 4. 航次（8） ============
s, j = req("POST", "/api/voyages", {"vessel_id": SVID, "pol_id": 1, "pod_id": 3, "etd": "2026-03-01", "eta": "2026-03-06"}, tok=TOK)
chk("voyage create", s == 200, j)
VOY = j["data"]["id"]
s, j = req("POST", "/api/voyages", {"vessel_id": SVID, "pol_id": 1, "pod_id": 1}, tok=TOK)
chk("voyage same port 422", s == 422, j)
s, j = req("POST", "/api/voyages/%d/transition" % VOY, {"action": "to_arrived"}, tok=TOK)
chk("voyage trans 422", s == 422, j)
s, j = req("POST", "/api/voyages/%d/transition" % VOY, {"action": "to_departed"}, tok=TOK)
chk("voyage departed", s == 200 and j["data"]["status"] == "departed", j)
s, j = req("GET", "/api/voyages/%d" % VOY, tok=TOK)
chk("voyage detail", s == 200 and "bookings" in j["data"] and "containers" in j["data"], j)
s, j = req("GET", "/api/voyages?status=planned", tok=TOK)
chk("voyage filter", s == 200 and all(i["status"] == "planned" for i in j["data"]["items"]), j)
s, j = req("POST", "/api/voyages/%d/transition" % VOY, {"action": "to_arrived"}, tok=TOK)
chk("voyage arrived", s == 200, j)
s, j = req("POST", "/api/voyages/%d/transition" % VOY, {"action": "to_closed"}, tok=TOK)
chk("voyage closed", s == 200, j)

# ============ 5. 订舱（8） ============
s, j = req("GET", "/api/bookings", tok=TOK)
chk("booking list", s == 200 and j["data"]["total"] >= 3, j)
s, j = req("POST", "/api/voyages", {"vessel_id": 2, "pol_id": 1, "pod_id": 4, "etd": "2026-04-01"}, tok=TOK)
chk("voyage2 create", s == 200, j)
VOY2 = j["data"]["id"]
s, j = req("POST", "/api/bookings", {"voyage_id": VOY2, "shipper_id": 1, "consignee": "冒烟收货", "cargo_desc": "冒烟货" + SUF, "boxes": 3, "ctype": "40GP"}, tok=TOK)
chk("booking create", s == 200, j)
BK = j["data"]["id"]
BKN = j["data"]["no"]
s, j = req("POST", "/api/bookings", {"voyage_id": VOY2, "shipper_id": 1, "boxes": 0}, tok=TOK)
chk("booking boxes 422", s == 422, j)
s, j = req("POST", "/api/bookings", {"voyage_id": VOY2, "shipper_id": 1, "boxes": 5000, "ctype": "40HQ"}, tok=TOK)
chk("booking overload 422", s == 422, j)
s, j = req("POST", "/api/bookings/%d/transition" % BK, {"action": "to_shipped"}, tok=TOK)
chk("booking trans 422", s == 422, j)
s, j = req("POST", "/api/bookings/%d/transition" % BK, {"action": "to_loaded"}, tok=TOK)
chk("booking loaded", s == 200, j)
s, j = req("PUT", "/api/bookings/%d" % BK, {"consignee": "改"}, tok=TOK)
chk("booking update 422", s == 422, j)  # 已 loaded

# ============ 6. 集装箱（9） ============
s, j = req("GET", "/api/containers", tok=TOK)
chk("container list", s == 200 and j["data"]["total"] >= 4, j)
unl = [i for i in j["data"]["items"] if i["status"] == "unloaded"]
chk("container demurrage", unl and unl[0]["demurrage_days"] > 0 and unl[0]["demurrage_cents"] > 0, unl)
s, j = req("POST", "/api/containers", {"container_no": "CSQU3054380", "ctype": "20GP"}, tok=TOK)
chk("container bad iso 422", s == 422, j)
s, j = req("POST", "/api/containers", {"container_no": iso_cno("OOLU" + SUF[:6]), "ctype": "40GP", "seal_no": "SMK"}, tok=TOK)
chk("container create", s == 200, j)
CT = j["data"]["id"]
s, j = req("POST", "/api/containers", {"container_no": iso_cno("OOLU" + SUF[:6]), "ctype": "40GP"}, tok=TOK)
chk("container dup 409", s == 409, j)
s, j = req("POST", "/api/containers/%d/transition" % CT, {"action": "to_in_transit"}, tok=TOK)
chk("container trans 422", s == 422, j)  # empty→in_transit 非法
s, j = req("POST", "/api/containers/%d/transition" % CT, {"action": "to_full"}, tok=TOK)
chk("container full", s == 200, j)
s, j = req("GET", "/api/containers/%d/demurrage?free_days=4&rate_cents=20000" % CT, tok=TOK)
chk("container demurrage api", s == 200 and j["data"]["demurrage_days"] == 0, j)

# ============ 7. 提单（6） ============
s, j = req("GET", "/api/bls", tok=TOK)
chk("bl list", s == 200 and j["data"]["total"] >= 2, j)
s, j = req("POST", "/api/bls", {"booking_id": BK, "shipper": "蓝湾食品", "consignee": "冒烟收货", "boxes": 3}, tok=TOK)
chk("bl create", s == 200, j)
BL = j["data"]["id"]
s, j = req("POST", "/api/bls/%d/transition" % BL, {"action": "to_surrendered"}, tok=TOK)
chk("bl trans 422", s == 422, j)
s, j = req("PUT", "/api/bls/%d" % BL, {"notify_party": "冒烟海关"}, tok=TOK)
chk("bl draft update", s == 200, j)
s, j = req("POST", "/api/bls/%d/transition" % BL, {"action": "to_issued"}, tok=TOK)
chk("bl issued", s == 200, j)
s, j = req("PUT", "/api/bls/%d" % BL, {"notify_party": "x"}, tok=TOK)
chk("bl issued update 422", s == 422, j)

# ============ 8. 运价（6） ============
s, j = req("GET", "/api/rates/quote?pol_id=1&pod_id=3&ctype=40RF&boxes=2", tok=TOK)
chk("rate quote", s == 200 and j["data"]["total_cents"] == 9400000, j)
s, j = req("GET", "/api/rates/quote?pol_id=2&pod_id=3&ctype=20GP&boxes=1", tok=TOK)
chk("rate expired 404", s == 404, j)
s, j = req("GET", "/api/rates", tok=TOK)
chk("rate list expired flag", s == 200 and any(i["expired"] for i in j["data"]["items"]), j)
s, j = req("POST", "/api/rates", {"pol_id": 1, "pod_id": 5, "ctype": "20GP", "base_cents": 800000,
                                  "surcharge_cents": 50000, "valid_from": "2026-01-01", "valid_to": "2026-12-31"}, tok=TOK)
chk("rate create", s == 200, j)
RID = j["data"]["id"]
s, j = req("POST", "/api/rates", {"pol_id": 1, "pod_id": 5, "ctype": "20GP", "base_cents": 100,
                                  "valid_from": "2026-12-31", "valid_to": "2026-01-01"}, tok=TOK)
chk("rate bad period 422", s == 422, j)
s, j = req("GET", "/api/rates/quote?pol_id=1&pod_id=5&ctype=20GP&boxes=3", tok=TOK)
chk("rate quote new", s == 200 and j["data"]["total_cents"] == 2550000, j)

# ============ 9. 客户与应收应付（8） ============
s, j = req("GET", "/api/partners", tok=TOK)
chk("partner list", s == 200 and j["data"]["total"] >= 3, j)
s, j = req("GET", "/api/partners/1/bills", tok=TOK)
chk("partner bills", s == 200, j)
s, j = req("POST", "/api/bills", {"btype": "demurrage", "partner_id": 1, "amount_cents": 160000, "due_date": "2026-11-30", "ref": "冒烟滞箱费"}, tok=TOK)
chk("bill create", s == 200, j)
BIL = j["data"]["id"]
s, j = req("POST", "/api/bills/%d/settle" % BIL, {"amount_cents": 60000, "method": "cash"}, tok=TOK)
chk("bill settle partial", s == 200 and j["data"]["status"] == "partial", j)
s, j = req("POST", "/api/bills/%d/settle" % BIL, {"amount_cents": 999999}, tok=TOK)
chk("bill settle trunc", s == 200 and j["data"]["settled_cents"] == 160000, j)
s, j = req("POST", "/api/bills/%d/settle" % BIL, {"amount_cents": 1}, tok=TOK)
chk("bill settled 422", s == 422, j)
s, j = req("GET", "/api/bills?overdue=1", tok=TOK)
chk("bills overdue", s == 200 and j["data"]["total"] >= 1 and j["data"]["items"][0]["days_overdue"] > 0, j)
s, j = req("GET", "/api/flows", tok=TOK)
chk("flows list", s == 200 and j["data"]["total"] >= 2, j)

# ============ 10. 报表与跟踪（5） ============
s, j = req("GET", "/api/reports/voyage-summary", tok=TOK)
chk("report voyage", s == 200 and j["data"]["voyages"] >= 3, j)
s, j = req("GET", "/api/reports/lane-stats", tok=TOK)
chk("report lane", s == 200 and len(j["data"]["items"]) >= 1, j)
s, j = req("GET", "/api/track/" + BKN, tok=TOK)
chk("track booking", s == 200 and len(j["data"]["events"]) >= 2, j)
s, j = req("GET", "/api/track/BL20260101-001", tok=TOK)
chk("track bl", s == 200, j)
s, j = req("GET", "/api/track/NOPE", tok=TOK)
chk("track 404", s == 404, j)

# ============ 11. 风险（4） ============
s, j = req("POST", "/api/risks/scan", tok=TOK)
chk("risk scan", s == 200 and j["data"]["created"] >= 0, j)
s, j = req("GET", "/api/risks?status=open", tok=TOK)
chk("risk list open", s == 200 and j["data"]["total"] >= 3, j)
rtypes = {i["rtype"] for i in j["data"]["items"]}
chk("risk types", {"demurrage_over", "bill_overdue", "voyage_overload"} <= rtypes, rtypes)
if j["data"]["items"]:
    rid = j["data"]["items"][0]["id"]
    s, j = req("PUT", "/api/risks/%d/resolve" % rid, {"note": "smoke"}, tok=TOK)
    chk("risk resolve", s == 200, j)
else:
    chk("risk resolve", False, "no risks")

# ============ 12. 幂等/同步/导出/Key/用户（8） ============
hdr = {"Idempotency-Key": "smk" + SUF}
s1, j1 = req("POST", "/api/bookings", {"voyage_id": VOY2, "shipper_id": 1, "boxes": 1, "ctype": "20GP"}, tok=TOK, headers=hdr)
s2, j2 = req("POST", "/api/bookings", {"voyage_id": VOY2, "shipper_id": 1, "boxes": 1, "ctype": "20GP"}, tok=TOK, headers=hdr)
chk("idempotent booking", s1 == 200 and s2 == 200 and j1["data"]["no"] == j2["data"]["no"], (s1, s2))
s, j = req("GET", "/api/sync?since=0&entities=ports,vessels,bookings", tok=TOK)
chk("sync", s == 200 and j["data"]["version"] > 0 and len(j["data"]["changes"]) >= 10, j)
s, j = req("GET", "/api/sync?since=0&entities=bad", tok=TOK)
chk("sync bad 422", s == 422, j)
s, j = req("GET", "/api/export/vessels", tok=TOK)
chk("export csv", s == 200 and isinstance(j.get("_raw"), str) and j["_raw"].startswith("code,name,imo"), j)
s, j = req("POST", "/api/api-keys", {"name": "smoke" + SUF, "perms": "sea.bookings.*"}, tok=TOK)
chk("api-key create", s == 200 and j["data"]["key"].startswith("fyo_"), j)
KEY = j["data"]["key"]
s, j = req("GET", "/api/bookings", headers={"X-Api-Key": KEY})
chk("api-key auth", s == 200, j)
s, j = req("GET", "/api/bills", headers={"X-Api-Key": KEY})
chk("api-key perm 403", s == 403, j)
s, j = req("GET", "/api/users", tok=TOK)
chk("users list", s == 200, j)

# ============ 汇总 ============
print("==== SMOKE PASS=%d FAIL=%d ====" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)

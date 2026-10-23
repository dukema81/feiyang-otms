# -*- coding: utf-8 -*-
"""飞洋 API 测试：认证/RBAC、港口/船舶、航次/订舱/箱/提单全链路、运价、结算、风险、同步、CSV"""
import time

from conftest import jreq
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
import ocean as K


def _no(suf):
    return str(int(time.time()))[-6:] + suf


def test_auth_and_rbac(srv, tok, jreq_fn):
    s, j = jreq_fn("GET", "/api/me", token=tok)
    assert s == 200 and j["data"]["user"]["role"] == "admin"
    s, j = jreq_fn("POST", "/api/login", {"username": "nobody", "password": "x"})
    assert s == 401
    rt = jreq_fn("POST", "/api/login", {"username": "reader01", "password": "123456"})[1]["data"]["token"]
    s, j = jreq_fn("POST", "/api/ports", {"code": "TEST1", "name": "x"}, token=rt)
    assert s == 403
    s, j = jreq_fn("GET", "/api/vessels")
    assert s == 401


def test_port_crud_and_protect(srv, tok, jreq_fn):
    code = "T%04d" % (int(_no("1")) % 10000)
    s, j = jreq_fn("POST", "/api/ports", {"code": code, "name": "测试港", "country": "测试"}, token=tok)
    assert s == 200, j
    pid = j["data"]["id"]
    s, j = jreq_fn("POST", "/api/ports", {"code": code, "name": "重复"}, token=tok)
    assert s == 409
    s, j = jreq_fn("POST", "/api/ports", {"code": "BAD1", "name": "格式"}, token=tok)
    assert s == 422
    s, j = jreq_fn("PUT", "/api/ports/%d" % pid, {"name": "测试港改"}, token=tok)
    assert s == 200
    s, j = jreq_fn("DELETE", "/api/ports/1", token=tok)  # CNSHA 被航次引用
    assert s == 409
    s, j = jreq_fn("DELETE", "/api/ports/%d" % pid, token=tok)
    assert s == 200


def test_vessel_crud_imo(srv, tok, jreq_fn):
    s, j = jreq_fn("POST", "/api/vessels", {"code": "TV1", "name": "测试轮", "imo": "1234567", "vtype": "container", "teu": 500}, token=tok)
    assert s == 200, j
    vid = j["data"]["id"]
    s, j = jreq_fn("POST", "/api/vessels", {"code": "TV2", "name": "重复IMO", "imo": "1234567"}, token=tok)
    assert s == 409
    s, j = jreq_fn("POST", "/api/vessels", {"code": "TV3", "name": "坏IMO", "imo": "12345"}, token=tok)
    assert s == 422
    s, j = jreq_fn("DELETE", "/api/vessels/1", token=tok)
    assert s == 409  # 有航次
    s, j = jreq_fn("DELETE", "/api/vessels/%d" % vid, token=tok)
    assert s == 200


def test_voyage_lifecycle(srv, tok, jreq_fn):
    s, j = jreq_fn("POST", "/api/voyages", {"vessel_id": 1, "pol_id": 1, "pod_id": 3, "etd": "2026-03-01"}, token=tok)
    assert s == 200, j
    vid = j["data"]["id"]
    s, j = jreq_fn("POST", "/api/voyages/%d/transition" % vid, {"action": "to_arrived"}, token=tok)
    assert s == 422  # planned→arrived 非法
    s, j = jreq_fn("POST", "/api/voyages/%d/transition" % vid, {"action": "to_departed"}, token=tok)
    assert s == 200 and j["data"]["status"] == "departed"
    s, j = jreq_fn("PUT", "/api/voyages/%d" % vid, {"etd": "2026-03-02"}, token=tok)
    assert s == 422  # 非 planned 不可改
    s, j = jreq_fn("POST", "/api/voyages/%d/transition" % vid, {"action": "to_arrived"}, token=tok)
    assert s == 200
    s, j = jreq_fn("POST", "/api/voyages/%d/transition" % vid, {"action": "to_closed"}, token=tok)
    assert s == 200
    s, j = jreq_fn("GET", "/api/voyages?status=planned", token=tok)
    assert s == 200 and any(it["no"] == "VO20260101-001" for it in j["data"]["items"])


def test_booking_overload_rejected(srv, tok, jreq_fn):
    # 短驳轮 teu=100：VO-003 已载 120 TEU（超载演示），航次已 arrived；用 planned 航次+大箱数触发预检
    s, j = jreq_fn("POST", "/api/voyages", {"vessel_id": 3, "pol_id": 2, "pod_id": 3}, token=tok)
    assert s == 200, j
    vvid = j["data"]["id"]
    s, j = jreq_fn("POST", "/api/bookings", {"voyage_id": vvid, "shipper_id": 1, "boxes": 60, "ctype": "40HQ"}, token=tok)
    assert s == 422, j
    s, j = jreq_fn("POST", "/api/bookings", {"voyage_id": 1, "shipper_id": 1, "boxes": 2, "ctype": "40RF", "cargo_desc": "测试货"}, token=tok)
    assert s == 200, j
    bid = j["data"]["id"]
    assert j["data"]["no"].startswith("BK")
    s, j = jreq_fn("POST", "/api/bookings/%d/transition" % bid, {"action": "to_loaded"}, token=tok)
    assert s == 200
    s, j = jreq_fn("POST", "/api/bookings/%d/transition" % bid, {"action": "to_shipped"}, token=tok)
    assert s == 422  # 航次未离港不可开船
    return bid


def test_container_iso_and_lifecycle(srv, tok, jreq_fn):
    s, j = jreq_fn("POST", "/api/containers", {"container_no": "TEMU9999999", "ctype": "40GP"}, token=tok)
    assert s == 422  # 校验位错误
    s, j = jreq_fn("POST", "/api/containers", {"container_no": "TEMU3054388"}, token=tok)
    assert s == 409  # 重复
    s, j = jreq_fn("GET", "/api/containers", token=tok)
    assert s == 200 and j["data"]["total"] >= 4
    unloaded = [it for it in j["data"]["items"] if it["status"] == "unloaded"][0]
    assert unloaded["demurrage_days"] > 0 and unloaded["demurrage_cents"] > 0
    # 建箱全生命周期
    s, j = jreq_fn("POST", "/api/containers", {"container_no": "OOLU987654" + str(K.container_check_digit("OOLU9876540")), "ctype": "20GP", "seal_no": "SX1"}, token=tok)
    assert s == 200, j
    cid = j["data"]["id"]
    for act in ("to_full", "to_in_transit"):
        s, j = jreq_fn("POST", "/api/containers/%d/transition" % cid, {"action": act}, token=tok)
        assert s == 200, (act, j)
    s, j = jreq_fn("PUT", "/api/containers/%d" % cid, {"seal_no": "SX2"}, token=tok)
    assert s == 422  # 在途禁改封号
    s, j = jreq_fn("POST", "/api/containers/%d/transition" % cid, {"action": "to_unloaded"}, token=tok)
    assert s == 200
    s, j = jreq_fn("GET", "/api/containers/%d/demurrage?free_days=4&rate_cents=20000" % cid, token=tok)
    assert s == 200 and j["data"]["demurrage_days"] == 0
    s, j = jreq_fn("POST", "/api/containers/%d/transition" % cid, {"action": "to_returned"}, token=tok)
    assert s == 200


def test_bl_lifecycle(srv, tok, jreq_fn):
    s, j = jreq_fn("POST", "/api/bls", {"booking_id": 1, "shipper": "蓝湾食品", "consignee": "新加坡果商", "boxes": 2}, token=tok)
    assert s == 200, j
    blid = j["data"]["id"]
    s, j = jreq_fn("POST", "/api/bls/%d/transition" % blid, {"action": "to_surrendered"}, token=tok)
    assert s == 422  # draft→surrendered 非法
    s, j = jreq_fn("PUT", "/api/bls/%d" % blid, {"notify_party": "海关"}, token=tok)
    assert s == 200
    s, j = jreq_fn("POST", "/api/bls/%d/transition" % blid, {"action": "to_issued"}, token=tok)
    assert s == 200
    s, j = jreq_fn("PUT", "/api/bls/%d" % blid, {"notify_party": "改不了"}, token=tok)
    assert s == 422
    s, j = jreq_fn("POST", "/api/bls/%d/transition" % blid, {"action": "to_telex_released"}, token=tok)
    assert s == 200


def test_rate_quote_and_validity(srv, tok, jreq_fn):
    s, j = jreq_fn("GET", "/api/rates/quote?pol_id=1&pod_id=3&ctype=40RF&boxes=2", token=tok)
    assert s == 200 and j["data"]["total_cents"] == 9400000
    s, j = jreq_fn("GET", "/api/rates/quote?pol_id=2&pod_id=3&ctype=20GP&boxes=1", token=tok)
    assert s == 404  # 已到期
    s, j = jreq_fn("GET", "/api/rates", token=tok)
    exp = [it for it in j["data"]["items"] if it["expired"]]
    assert len(exp) >= 1
    s, j = jreq_fn("POST", "/api/rates", {"pol_id": 1, "pod_id": 4, "ctype": "20GP", "base_cents": 100,
                                          "valid_from": "2026-12-31", "valid_to": "2026-01-01"}, token=tok)
    assert s == 422  # from>to


def test_bill_settle_partial_full(srv, tok, jreq_fn):
    s, j = jreq_fn("POST", "/api/bills", {"btype": "demurrage", "partner_id": 1, "amount_cents": 300000, "due_date": "2026-12-31", "ref": "滞箱费测试"}, token=tok)
    assert s == 200, j
    bid = j["data"]["id"]
    s, j = jreq_fn("POST", "/api/bills/%d/settle" % bid, {"amount_cents": 200000, "method": "bank"}, token=tok)
    assert s == 200 and j["data"]["status"] == "partial"
    s, j = jreq_fn("POST", "/api/bills/%d/settle" % bid, {"amount_cents": 999999}, token=tok)
    assert s == 200 and j["data"]["settled_cents"] == 300000 and j["data"]["status"] == "settled"  # 截断
    s, j = jreq_fn("POST", "/api/bills/%d/settle" % bid, {"amount_cents": 1}, token=tok)
    assert s == 422  # 已结清
    p = jreq_fn("GET", "/api/partners/1", token=tok)[1]["data"]
    s, j = jreq_fn("GET", "/api/flows", token=tok)
    assert s == 200 and any("滞箱费" in (f["category"] or "") for f in j["data"]["items"])


def test_risk_scan_and_resolve(srv, tok, jreq_fn):
    s, j = jreq_fn("POST", "/api/risks/scan", token=tok)
    assert s == 200 and j["data"]["created"] >= 0
    s, j = jreq_fn("POST", "/api/risks/scan", token=tok)
    assert s == 200  # 去重后 created=0 也不报错
    s, j = jreq_fn("GET", "/api/risks?status=open", token=tok)
    assert s == 200 and j["data"]["total"] >= 3
    rtypes = {it["rtype"] for it in j["data"]["items"]}
    assert {"demurrage_over", "bill_overdue", "voyage_overload"} <= rtypes
    rid = j["data"]["items"][0]["id"]
    s, j = jreq_fn("PUT", "/api/risks/%d/resolve" % rid, {"note": "ok"}, token=tok)
    assert s == 200
    s, j = jreq_fn("PUT", "/api/risks/%d/resolve" % rid, {"note": "again"}, token=tok)
    assert s == 422


def test_reports(srv, tok, jreq_fn):
    s, j = jreq_fn("GET", "/api/reports/voyage-summary", token=tok)
    assert s == 200 and j["data"]["voyages"] >= 3
    s, j = jreq_fn("GET", "/api/reports/lane-stats", token=tok)
    assert s == 200 and len(j["data"]["items"]) >= 1
    s, j = jreq_fn("GET", "/api/track/BK20260101-002", token=tok)
    assert s == 200 and len(j["data"]["events"]) >= 2
    s, j = jreq_fn("GET", "/api/track/NOPE123", token=tok)
    assert s == 404


def test_idempotent_booking(srv, tok, jreq_fn):
    body = {"voyage_id": 1, "shipper_id": 1, "boxes": 1, "ctype": "20GP", "cargo_desc": "幂等"}
    hdr = {"Idempotency-Key": "it-" + _no("K")}
    s1, j1 = jreq_fn("POST", "/api/bookings", body, token=tok, headers=hdr)
    assert s1 == 200
    s2, j2 = jreq_fn("POST", "/api/bookings", body, token=tok, headers=hdr)
    assert s2 == 200 and j1["data"]["no"] == j2["data"]["no"]


def test_sync_and_csv(srv, tok, jreq_fn):
    s, j = jreq_fn("GET", "/api/sync?since=0&entities=ports,vessels", token=tok)
    assert s == 200 and j["data"]["version"] > 0 and len(j["data"]["changes"]) >= 8
    ents = {c["entity"] for c in j["data"]["changes"]}
    assert ents <= {"ports", "vessels"}
    s, j = jreq_fn("GET", "/api/sync?since=999999&entities=ports", token=tok)
    assert s == 200 and j["data"]["changes"] == []
    s, j = jreq_fn("GET", "/api/sync?since=0&entities=bad", token=tok)
    assert s == 422
    st, raw = jreq_fn("GET", "/api/export/vessels", token=tok)
    assert st == 200 and raw[1].startswith("code,name,imo")


def test_users_and_keys(srv, tok, jreq_fn):
    s, j = jreq_fn("POST", "/api/users", {"username": "u" + _no("U"), "password": "x12345", "role": "ops"}, token=tok)
    assert s == 200
    uid = j["data"]["id"]
    s, j = jreq_fn("PUT", "/api/users/%d" % uid, {"phone": "123"}, token=tok)
    assert s == 200
    s, j = jreq_fn("DELETE", "/api/users/%d" % uid, token=tok)
    assert s == 200
    s, j = jreq_fn("DELETE", "/api/users/1", token=tok)
    assert s == 422  # 不能删自己
    s, j = jreq_fn("POST", "/api/api-keys", {"name": "erp", "perms": "sea.bookings.*"}, token=tok)
    assert s == 200 and j["data"]["key"].startswith("fyo_")
    key = j["data"]["key"]
    s, j = jreq_fn("GET", "/api/bookings", headers={"X-Api-Key": key})
    assert s == 200
    s, j = jreq_fn("GET", "/api/bills", headers={"X-Api-Key": key})
    assert s == 403  # 权限不含
    s, j = jreq_fn("GET", "/api/bookings", headers={"X-Api-Key": "fyo_bad"})
    assert s == 401

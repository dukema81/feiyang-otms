# -*- coding: utf-8 -*-
"""飞洋 OTMS 服务端：零依赖 HTTP API（端口 8031，前缀可配）"""
import os, re, json, time, hashlib, traceback, urllib.parse, datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from http import cookies as http_cookies

import db as D
from db import q, q1, execute, next_seq, make_no, bump_sync, get_sync
import ocean as K
import seed as S

PORT = int(os.environ.get("OY_PORT", "8031"))
PREFIX = os.environ.get("OY_PREFIX", "")
TOKEN_TTL = 7 * 86400

def now_s():
    return time.strftime("%Y-%m-%d %H:%M:%S")

def today_s():
    return time.strftime("%Y-%m-%d")

def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def jdump(o):
    return json.dumps(o, ensure_ascii=False, default=str)

class ApiError(Exception):
    def __init__(self, code, message):
        self.code = code; self.message = message

def page_args(qs):
    p = max(int(qs.get("page", ["1"])[0] or 1), 1)
    s = min(max(int(qs.get("size", ["20"])[0] or 20), 1), 200)
    return p, s, (p - 1) * s

def listwrap(sql, params, qs, extra=None):
    p, s, off = page_args(qs)
    total = q1("SELECT COUNT(*) AS c FROM (" + sql + ")", params)["c"]
    rows = q(sql + " LIMIT %d OFFSET %d" % (s, off), params)
    items = [dict(r) for r in rows]
    if extra:
        for it in items:
            extra(it)
    return {"items": items, "total": total, "page": p, "size": s}

def csv_export(rows, cols):
    import io, csv as _csv
    buf = io.StringIO()
    w = _csv.writer(buf)
    w.writerow(cols)
    for r in rows:
        w.writerow([r[c] if c in r.keys() else "" for c in cols])
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")

def log_act(user_id, action, detail=""):
    D.execute("INSERT INTO logs(ts,user_id,action,detail) VALUES(?,?,?,?)", (now_s(), user_id, action, detail))

# ---------- 认证 ----------

def auth_token(tok):
    if not tok:
        return None
    row = q1("SELECT t.*, u.username, u.name, u.role FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=?", (tok,))
    if not row:
        return None
    if row["expires_at"] and row["expires_at"] < now_s():
        execute("DELETE FROM tokens WHERE token=?", (tok,))
        return None
    return row

def auth_key(key):
    if not key:
        return None
    row = q1("SELECT * FROM api_keys WHERE key_hash=? AND status=1", (sha(key),))
    if not row:
        return None
    execute("UPDATE api_keys SET last_used=? WHERE id=?", (now_s(), row["id"]))
    return {"username": "apikey:" + (row["prefix"] or "k"), "name": row["name"], "role": "apikey", "perms": (row["perms"] or "sea.read").split(",")}

def do_login(body):
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    u = q1("SELECT * FROM users WHERE username=? AND status=1", (username,))
    if not u or u["password"] != sha(password):
        log_act(None, "login_fail", username)
        raise ApiError(401, "用户名或密码错误")
    tok = sha(username + str(time.time()) + os.urandom(8).hex())[:40]
    exp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() + TOKEN_TTL))
    execute("INSERT INTO tokens(token, user_id, created_at, expires_at) VALUES(?,?,?,?)", (tok, u["id"], now_s(), exp))
    log_act(u["id"], "login", username)
    perms = K.ROLE_PERMS.get(u["role"], K.ROLE_PERMS["reader"])
    return {"token": tok, "expires_at": exp, "user": {"id": u["id"], "username": u["username"], "name": u["name"], "role": u["role"]}, "perms": perms}

def h_login(ctx, m, qs, body):
    return do_login(body)

def h_logout(ctx, m, qs, body):
    execute("DELETE FROM tokens WHERE token=?", (ctx["token"],))
    return {"ok": True}

def h_me(ctx, m, qs, body):
    u = ctx["user"]
    perms = K.ROLE_PERMS.get(u["role"], K.ROLE_PERMS["reader"]) if u.get("role") != "apikey" else u["perms"]
    return {"user": {"id": u.get("id"), "username": u["username"], "name": u["name"], "role": u["role"]}, "perms": perms}

def h_health(ctx, m, qs, body):
    return {"ok": True, "service": "feiyang-otms", "ts": now_s()}

# ---------- 用户 / Key ----------

def h_users(ctx, m, qs, body):
    return listwrap("SELECT id,username,name,role,phone,status,created_at FROM users ORDER BY id", (), qs)

def h_users_create(ctx, m, qs, body):
    if not body.get("username") or not body.get("password"):
        raise ApiError(422, "username/password 必填")
    if q1("SELECT id FROM users WHERE username=?", (body["username"],)):
        raise ApiError(409, "用户名已存在")
    role = body.get("role", "reader")
    if role not in K.ROLE_PERMS:
        raise ApiError(422, "角色非法")
    c = execute("INSERT INTO users(username,password,name,role,phone) VALUES(?,?,?,?,?)",
                (body["username"], sha(body["password"]), body.get("name", body["username"]), role, body.get("phone")))
    return {"id": c.lastrowid}

def h_users_update(ctx, m, qs, body):
    uid = int(m.group(1))
    if not q1("SELECT id FROM users WHERE id=?", (uid,)):
        raise ApiError(404, "用户不存在")
    sets, params = [], []
    for f in ("name", "role", "phone"):
        if f in body:
            if f == "role" and body[f] not in K.ROLE_PERMS:
                raise ApiError(422, "角色非法")
            sets.append(f + "=?"); params.append(body[f])
    if body.get("password"):
        sets.append("password=?"); params.append(sha(body["password"]))
    if "status" in body:
        sets.append("status=?"); params.append(1 if body["status"] else 0)
    if sets:
        params.append(uid)
        execute("UPDATE users SET " + ",".join(sets) + " WHERE id=?", params)
    return {"ok": True}

def h_users_delete(ctx, m, qs, body):
    uid = int(m.group(1))
    if uid == (ctx["user"].get("id") or 0):
        raise ApiError(422, "不能删除自己")
    row = q1("SELECT id FROM users WHERE id=?", (uid,))
    if not row:
        raise ApiError(404, "用户不存在")
    execute("DELETE FROM tokens WHERE user_id=?", (uid,))
    execute("DELETE FROM users WHERE id=?", (uid,))
    return {"ok": True}

def h_keys(ctx, m, qs, body):
    return listwrap("SELECT id,name,prefix,perms,status,last_used,created_at FROM api_keys ORDER BY id", (), qs)

def h_keys_create(ctx, m, qs, body):
    name = body.get("name") or "default"
    raw = "fyo_" + sha(name + str(time.time()) + os.urandom(8).hex())[:32]
    c = execute("INSERT INTO api_keys(name, key_hash, prefix, perms) VALUES(?,?,?,?)",
                (name, sha(raw), raw[:12], body.get("perms", "sea.*")))
    return {"id": c.lastrowid, "key": raw, "note": "仅此一次返回明文，请妥善保存"}

def h_keys_delete(ctx, m, qs, body):
    execute("DELETE FROM api_keys WHERE id=?", (int(m.group(1)),))
    return {"ok": True}

# ---------- 港口 ----------

def h_port_list(ctx, m, qs, body):
    cond, params = "1=1", []
    if qs.get("country", [""])[0]:
        cond += " AND country=?"; params.append(qs["country"][0])
    kw = qs.get("keyword", [""])[0]
    if kw:
        cond += " AND (name LIKE ? OR code LIKE ?)"; params += ["%" + kw + "%"] * 2
    return listwrap("SELECT * FROM ports WHERE " + cond + " ORDER BY code", params, qs)

def h_port_create(ctx, m, qs, body):
    if not body.get("code") or not body.get("name"):
        raise ApiError(422, "code/name 必填")
    code = body["code"].strip().upper()
    if not re.match(r"^[A-Z][A-Z0-9]{4}$", code):
        raise ApiError(422, "code 须为 5 位编码（字母开头）")
    if q1("SELECT id FROM ports WHERE code=?", (code,)):
        raise ApiError(409, "港口编码已存在")
    c = execute("INSERT INTO ports(code,name,country) VALUES(?,?,?)", (code, body["name"], body.get("country")))
    bump_sync("ports")
    return {"id": c.lastrowid, "code": code}

def h_port_update(ctx, m, qs, body):
    pid = int(m.group(1))
    if not q1("SELECT id FROM ports WHERE id=?", (pid,)):
        raise ApiError(404, "港口不存在")
    sets, params = [], []
    for f in ("name", "country", "status"):
        if f in body:
            sets.append(f + "=?"); params.append(body[f])
    if sets:
        params.append(pid)
        execute("UPDATE ports SET " + ",".join(sets) + " WHERE id=?", params)
    bump_sync("ports")
    return {"ok": True}

def h_port_delete(ctx, m, qs, body):
    pid = int(m.group(1))
    if q1("SELECT id FROM voyages WHERE pol_id=? OR pod_id=? LIMIT 1", (pid, pid)):
        raise ApiError(409, "港口已被航次引用，禁止删除")
    if q1("SELECT id FROM rates WHERE pol_id=? OR pod_id=? LIMIT 1", (pid, pid)):
        raise ApiError(409, "港口已被运价引用，禁止删除")
    execute("DELETE FROM ports WHERE id=?", (pid,))
    bump_sync("ports")
    return {"ok": True}

# ---------- 船舶 ----------

def h_vessel_list(ctx, m, qs, body):
    cond, params = "1=1", []
    if qs.get("vtype", [""])[0]:
        cond += " AND vtype=?"; params.append(qs["vtype"][0])
    if qs.get("status", [""])[0]:
        cond += " AND status=?"; params.append(qs["status"][0])
    kw = qs.get("keyword", [""])[0]
    if kw:
        cond += " AND (name LIKE ? OR code LIKE ? OR imo LIKE ?)"; params += ["%" + kw + "%"] * 3
    def ex(it):
        it["loaded_teu"] = _voyage_loaded_teu(it["id"])
        return it
    return listwrap("SELECT * FROM vessels WHERE " + cond + " ORDER BY code", params, qs, ex)

def h_vessel_create(ctx, m, qs, body):
    if not body.get("code") or not body.get("name") or not body.get("imo"):
        raise ApiError(422, "code/name/imo 必填")
    imo = str(body["imo"]).strip()
    if not re.match(r"^\d{7}$", imo):
        raise ApiError(422, "imo 须为 7 位数字")
    if q1("SELECT id FROM vessels WHERE imo=?", (imo,)):
        raise ApiError(409, "IMO 号已存在")
    if q1("SELECT id FROM vessels WHERE code=?", (body["code"],)):
        raise ApiError(409, "船舶编码已存在")
    vtype = body.get("vtype", "container")
    if vtype not in K.VTYPE_SET:
        raise ApiError(422, "vtype 须为 container/bulk/tanker/roro")
    c = execute("INSERT INTO vessels(code,name,imo,vtype,dwt,teu,flag) VALUES(?,?,?,?,?,?,?)",
                (body["code"], body["name"], imo, vtype, int(body.get("dwt", 0) or 0),
                 int(body.get("teu", 0) or 0), body.get("flag")))
    bump_sync("vessels")
    return {"id": c.lastrowid}

def h_vessel_update(ctx, m, qs, body):
    vid = int(m.group(1))
    if not q1("SELECT id FROM vessels WHERE id=?", (vid,)):
        raise ApiError(404, "船舶不存在")
    sets, params = [], []
    for f in ("name", "vtype", "dwt", "teu", "flag", "status"):
        if f in body:
            if f == "vtype" and body[f] not in K.VTYPE_SET:
                raise ApiError(422, "vtype 非法")
            if f == "status" and body[f] not in K.VESSEL_STATUS:
                raise ApiError(422, "status 须为 active/laid_up/retired")
            sets.append(f + "=?"); params.append(body[f])
    if sets:
        params.append(vid)
        execute("UPDATE vessels SET " + ",".join(sets) + " WHERE id=?", params)
    bump_sync("vessels")
    return {"ok": True}

def h_vessel_delete(ctx, m, qs, body):
    vid = int(m.group(1))
    if q1("SELECT id FROM voyages WHERE vessel_id=? LIMIT 1", (vid,)):
        raise ApiError(409, "船舶已有航次记录，禁止删除")
    execute("DELETE FROM vessels WHERE id=?", (vid,))
    bump_sync("vessels")
    return {"ok": True}

def h_vessel_voyages(ctx, m, qs, body):
    vid = int(m.group(1))
    if not q1("SELECT id FROM vessels WHERE id=?", (vid,)):
        raise ApiError(404, "船舶不存在")
    def ex(it):
        _voyage_ex(it)
        return it
    return listwrap("SELECT * FROM voyages WHERE vessel_id=? ORDER BY id DESC", (vid,), qs, ex)

# ---------- 航次 ----------

def _voyage_loaded_teu(vessel_id, voyage_id=None):
    cond = "v.vessel_id=? AND v.status NOT IN ('cancelled','closed')"
    params = [vessel_id]
    if voyage_id:
        cond += " AND v.id=?"; params.append(voyage_id)
    row = q1("""SELECT COALESCE(SUM(CASE WHEN b.ctype LIKE '40%%' OR b.ctype LIKE '45%%' THEN b.boxes*2 ELSE b.boxes END),0) t
                FROM bookings b JOIN voyages v ON v.id=b.voyage_id
                WHERE %s AND b.status NOT IN ('cancelled')""" % cond, params)
    return float(row["t"] or 0)

def _voyage_ex(it):
    v = q1("SELECT name, code, teu FROM vessels WHERE id=?", (it["vessel_id"],))
    it["vessel_name"] = v["name"] if v else None
    it["vessel_teu"] = v["teu"] if v else 0
    p1 = q1("SELECT code, name FROM ports WHERE id=?", (it["pol_id"],))
    p2 = q1("SELECT code, name FROM ports WHERE id=?", (it["pod_id"],))
    it["pol"] = p1["code"] if p1 else None; it["pol_name"] = p1["name"] if p1 else None
    it["pod"] = p2["code"] if p2 else None; it["pod_name"] = p2["name"] if p2 else None
    it["loaded_teu"] = _voyage_loaded_teu(it["vessel_id"], it["id"])
    it["boxes"] = q1("SELECT COALESCE(SUM(boxes),0) c FROM bookings WHERE voyage_id=? AND status NOT IN ('cancelled')", (it["id"],))["c"]
    return it

def h_voyage_list(ctx, m, qs, body):
    cond, params = "1=1", []
    if qs.get("status", [""])[0]:
        cond += " AND status=?"; params.append(qs["status"][0])
    if qs.get("vessel_id", [""])[0]:
        cond += " AND vessel_id=?"; params.append(int(qs["vessel_id"][0]))
    if qs.get("month", [""])[0]:
        cond += " AND substr(etd,1,7)=?"; params.append(qs["month"][0])
    kw = qs.get("keyword", [""])[0]
    if kw:
        cond += " AND no LIKE ?"; params.append("%" + kw + "%")
    return listwrap("SELECT * FROM voyages WHERE " + cond + " ORDER BY id DESC", params, qs, _voyage_ex)

def h_voyage_get(ctx, m, qs, body):
    vid = int(m.group(1))
    r = q1("SELECT * FROM voyages WHERE id=?", (vid,))
    if not r:
        raise ApiError(404, "航次不存在")
    d = _voyage_ex(dict(r))
    d["bookings"] = [dict(x) for x in q("SELECT * FROM bookings WHERE voyage_id=? ORDER BY id", (vid,))]
    d["containers"] = [dict(x) for x in q("SELECT * FROM containers WHERE voyage_id=? ORDER BY id", (vid,))]
    return d

def h_voyage_create(ctx, m, qs, body):
    if not body.get("vessel_id") or not body.get("pol_id") or not body.get("pod_id"):
        raise ApiError(422, "vessel_id/pol_id/pod_id 必填")
    if not q1("SELECT id FROM vessels WHERE id=? AND status='active'", (body["vessel_id"],)):
        raise ApiError(404, "船舶不存在或未启用")
    if body["pol_id"] == body["pod_id"]:
        raise ApiError(422, "起运港与目的港不能相同")
    for pid in (body["pol_id"], body["pod_id"]):
        if not q1("SELECT id FROM ports WHERE id=? AND status='active'", (pid,)):
            raise ApiError(404, "港口不存在或未启用: id=%s" % pid)
    no = body.get("no") or make_no("VO", "voyage_no")
    if q1("SELECT id FROM voyages WHERE no=?", (no,)):
        raise ApiError(409, "航次号已存在")
    c = execute("INSERT INTO voyages(no,vessel_id,pol_id,pod_id,etd,eta,note,created_by) VALUES(?,?,?,?,?,?,?,?)",
                (no, body["vessel_id"], body["pol_id"], body["pod_id"],
                 body.get("etd"), body.get("eta"), body.get("note"), ctx["user"].get("username") or ""))
    bump_sync("voyages")
    return {"id": c.lastrowid, "no": no}

def h_voyage_update(ctx, m, qs, body):
    vid = int(m.group(1))
    r = q1("SELECT * FROM voyages WHERE id=?", (vid,))
    if not r:
        raise ApiError(404, "航次不存在")
    if r["status"] != "planned":
        raise ApiError(422, "仅计划中航次可修改")
    sets, params = [], []
    for f in ("etd", "eta", "note"):
        if f in body:
            sets.append(f + "=?"); params.append(body[f])
    if sets:
        params.append(vid)
        execute("UPDATE voyages SET " + ",".join(sets) + " WHERE id=?", params)
    bump_sync("voyages")
    return {"ok": True}

VOYAGE_ACTIONS = {"to_departed": ("departed", "atd"), "to_arrived": ("arrived", "ata"),
                  "to_closed": ("closed", None), "to_cancelled": ("cancelled", None)}

def h_voyage_transition(ctx, m, qs, body):
    vid = int(m.group(1))
    r = q1("SELECT * FROM voyages WHERE id=?", (vid,))
    if not r:
        raise ApiError(404, "航次不存在")
    action = body.get("action") or ""
    if action not in VOYAGE_ACTIONS:
        raise ApiError(422, "action 须为 to_departed/to_arrived/to_closed/to_cancelled")
    nxt, stamp_col = VOYAGE_ACTIONS[action]
    if not K.can_transition(K.VOYAGE_TRANS, r["status"], nxt):
        raise ApiError(422, "航次 %s 不允许 %s → %s" % (r["no"], r["status"], nxt))
    loaded = _voyage_loaded_teu(r["vessel_id"], vid)
    vessel = q1("SELECT teu FROM vessels WHERE id=?", (r["vessel_id"],))
    over, _ = K.voyage_load_check(loaded, vessel["teu"] if vessel else 0)
    if nxt == "departed" and over:
        raise ApiError(422, "航次装载 %.0f TEU 超过船舶箱位 %d TEU，禁止离港" % (loaded, vessel["teu"]))
    if stamp_col:
        execute("UPDATE voyages SET status=?, %s=?, version=version+1 WHERE id=?" % stamp_col,
                (nxt, today_s(), vid))
    else:
        execute("UPDATE voyages SET status=?, version=version+1 WHERE id=?", (nxt, vid))
    bump_sync("voyages")
    return {"ok": True, "status": nxt}

def h_voyage_delete(ctx, m, qs, body):
    vid = int(m.group(1))
    r = q1("SELECT * FROM voyages WHERE id=?", (vid,))
    if not r:
        raise ApiError(404, "航次不存在")
    if r["status"] not in ("planned", "cancelled"):
        raise ApiError(422, "仅计划中/已取消航次可删除")
    if q1("SELECT id FROM bookings WHERE voyage_id=? LIMIT 1", (vid,)):
        raise ApiError(409, "航次已有订舱，禁止删除")
    execute("DELETE FROM voyages WHERE id=?", (vid,))
    bump_sync("voyages")
    return {"ok": True}

# ---------- 订舱 ----------

def _booking_ex(it):
    v = q1("SELECT no, status FROM voyages WHERE id=?", (it["voyage_id"],))
    it["voyage_no"] = v["no"] if v else None
    p = q1("SELECT name FROM partners WHERE id=?", (it["shipper_id"],))
    it["shipper_name"] = p["name"] if p else None
    it["teu"] = K.boxes_teu(it["ctype"], it["boxes"])
    it["bl_count"] = q1("SELECT COUNT(*) c FROM bls WHERE booking_id=?", (it["id"],))["c"]
    return it

def h_booking_list(ctx, m, qs, body):
    cond, params = "1=1", []
    for f in ("status",):
        if qs.get(f, [""])[0]:
            cond += " AND %s=?" % f; params.append(qs[f][0])
    if qs.get("voyage_id", [""])[0]:
        cond += " AND voyage_id=?"; params.append(int(qs["voyage_id"][0]))
    if qs.get("partner_id", [""])[0]:
        cond += " AND shipper_id=?"; params.append(int(qs["partner_id"][0]))
    kw = qs.get("keyword", [""])[0]
    if kw:
        cond += " AND (no LIKE ? OR cargo_desc LIKE ? OR consignee LIKE ?)"; params += ["%" + kw + "%"] * 3
    return listwrap("SELECT * FROM bookings WHERE " + cond + " ORDER BY id DESC", params, qs, _booking_ex)

def h_booking_get(ctx, m, qs, body):
    bid = int(m.group(1))
    r = q1("SELECT * FROM bookings WHERE id=?", (bid,))
    if not r:
        raise ApiError(404, "订舱不存在")
    d = _booking_ex(dict(r))
    d["bls"] = [dict(x) for x in q("SELECT * FROM bls WHERE booking_id=? ORDER BY id", (bid,))]
    d["containers"] = [dict(x) for x in q("SELECT * FROM containers WHERE booking_id=? ORDER BY id", (bid,))]
    return d

def h_booking_create(ctx, m, qs, body):
    if not body.get("voyage_id") or not body.get("shipper_id"):
        raise ApiError(422, "voyage_id/shipper_id 必填")
    v = q1("SELECT * FROM voyages WHERE id=?", (body["voyage_id"],))
    if not v:
        raise ApiError(404, "航次不存在")
    if v["status"] != "planned":
        raise ApiError(422, "仅计划中航次可订舱")
    if not q1("SELECT id FROM partners WHERE id=?", (body["shipper_id"],)):
        raise ApiError(404, "托运人不存在")
    boxes = int(body.get("boxes", 1) or 0)
    if boxes <= 0:
        raise ApiError(422, "boxes 必须为正整数")
    ctype = body.get("ctype", "20GP")
    if ctype not in K.CTYPE_SET:
        raise ApiError(422, "ctype 须为 20GP/40GP/40HQ/20RF/40RF/45HC")
    # 装载预检：不允许超载订舱
    vessel = q1("SELECT teu, name FROM vessels WHERE id=?", (v["vessel_id"],))
    loaded = _voyage_loaded_teu(v["vessel_id"], body["voyage_id"])
    over, _ = K.voyage_load_check(loaded + K.boxes_teu(ctype, boxes), vessel["teu"])
    if over:
        raise ApiError(422, "超出船舶 %s 箱位（已载 %.0f/%d TEU）" % (vessel["name"], loaded, vessel["teu"]))
    no = make_no("BK", "booking_no")
    c = execute("INSERT INTO bookings(no,voyage_id,shipper_id,consignee,cargo_desc,boxes,ctype,created_by) VALUES(?,?,?,?,?,?,?,?)",
                (no, body["voyage_id"], body["shipper_id"], body.get("consignee"),
                 body.get("cargo_desc"), boxes, ctype, ctx["user"].get("username") or ""))
    bump_sync("bookings")
    return {"id": c.lastrowid, "no": no}

def h_booking_update(ctx, m, qs, body):
    bid = int(m.group(1))
    r = q1("SELECT * FROM bookings WHERE id=?", (bid,))
    if not r:
        raise ApiError(404, "订舱不存在")
    if r["status"] != "booked":
        raise ApiError(422, "仅已订舱状态可修改")
    sets, params = [], []
    for f in ("consignee", "cargo_desc", "boxes", "ctype"):
        if f in body:
            if f == "ctype" and body[f] not in K.CTYPE_SET:
                raise ApiError(422, "ctype 非法")
            sets.append(f + "=?"); params.append(body[f])
    if sets:
        params.append(bid)
        execute("UPDATE bookings SET " + ",".join(sets) + " WHERE id=?", params)
    bump_sync("bookings")
    return {"ok": True}

BOOKING_ACTIONS = {"to_loaded": "loaded", "to_shipped": "shipped",
                   "to_delivered": "delivered", "to_cancelled": "cancelled"}

def h_booking_transition(ctx, m, qs, body):
    bid = int(m.group(1))
    r = q1("SELECT * FROM bookings WHERE id=?", (bid,))
    if not r:
        raise ApiError(404, "订舱不存在")
    action = body.get("action") or ""
    if action not in BOOKING_ACTIONS:
        raise ApiError(422, "action 须为 to_loaded/to_shipped/to_delivered/to_cancelled")
    nxt = BOOKING_ACTIONS[action]
    if not K.can_transition(K.BOOKING_TRANS, r["status"], nxt):
        raise ApiError(422, "订舱 %s 不允许 %s → %s" % (r["no"], r["status"], nxt))
    # 箱联动：loaded → 箱 in_transit；shipped → 随航次 departed 校验
    v = q1("SELECT status FROM voyages WHERE id=?", (r["voyage_id"],))
    if nxt == "loaded" and v["status"] != "planned":
        raise ApiError(422, "航次已离港，不可装载")
    if nxt == "shipped" and v["status"] in ("planned", "cancelled"):
        raise ApiError(422, "航次未离港，不可开船")
    execute("UPDATE bookings SET status=?, version=version+1 WHERE id=?", (nxt, bid))
    if nxt == "loaded":
        execute("UPDATE containers SET status='in_transit', version=version+1 WHERE booking_id=? AND status='full'", (bid,))
    if nxt == "delivered":
        execute("UPDATE containers SET status='unloaded', unloaded_at=?, version=version+1 WHERE booking_id=? AND status='in_transit'",
                (today_s(), bid))
    bump_sync("bookings"); bump_sync("containers")
    return {"ok": True, "status": nxt}

def h_booking_delete(ctx, m, qs, body):
    bid = int(m.group(1))
    r = q1("SELECT * FROM bookings WHERE id=?", (bid,))
    if not r:
        raise ApiError(404, "订舱不存在")
    if r["status"] not in ("booked", "cancelled"):
        raise ApiError(422, "仅已订舱/已取消可删除")
    if q1("SELECT id FROM bls WHERE booking_id=? LIMIT 1", (bid,)):
        raise ApiError(409, "订舱已有提单，禁止删除")
    if q1("SELECT id FROM containers WHERE booking_id=? LIMIT 1", (bid,)):
        raise ApiError(409, "订舱已挂集装箱，禁止删除")
    execute("DELETE FROM bookings WHERE id=?", (bid,))
    bump_sync("bookings")
    return {"ok": True}

# ---------- 集装箱 ----------

def _rules_get(name, default):
    r = q1("SELECT value FROM oy_rules WHERE name=?", (name,))
    try:
        return int(r["value"])
    except Exception:
        return default

def _container_ex(it):
    free = _rules_get("free_days", 4)
    rate = _rules_get("demurrage_rate_cents", 20000)
    if it["status"] == "unloaded":
        it["demurrage_days"] = K.demurrage_days(it["unloaded_at"], None, free)
        it["demurrage_cents"] = K.demurrage_fee(it["demurrage_days"], rate)
    elif it["status"] == "returned" and it["unloaded_at"]:
        it["demurrage_days"] = K.demurrage_days(it["unloaded_at"], it["returned_at"], free)
        it["demurrage_cents"] = K.demurrage_fee(it["demurrage_days"], rate)
    else:
        it["demurrage_days"] = 0; it["demurrage_cents"] = 0
    return it

def h_container_list(ctx, m, qs, body):
    cond, params = "1=1", []
    for f in ("status",):
        if qs.get(f, [""])[0]:
            cond += " AND %s=?" % f; params.append(qs[f][0])
    if qs.get("voyage_id", [""])[0]:
        cond += " AND voyage_id=?"; params.append(int(qs["voyage_id"][0]))
    if qs.get("ctype", [""])[0]:
        cond += " AND ctype=?"; params.append(qs["ctype"][0])
    kw = qs.get("keyword", [""])[0]
    if kw:
        cond += " AND container_no LIKE ?"; params.append("%" + kw.upper() + "%")
    return listwrap("SELECT * FROM containers WHERE " + cond + " ORDER BY id DESC", params, qs, _container_ex)

def h_container_create(ctx, m, qs, body):
    no = (body.get("container_no") or "").strip().upper()
    if not no:
        raise ApiError(422, "container_no 必填")
    if not K.container_no_valid(no):
        raise ApiError(422, "箱号不符合 ISO 6346（校验位错误）")
    if q1("SELECT id FROM containers WHERE container_no=?", (no,)):
        raise ApiError(409, "箱号已存在")
    ctype = body.get("ctype", "20GP")
    if ctype not in K.CTYPE_SET:
        raise ApiError(422, "ctype 非法")
    voyage_id = body.get("voyage_id")
    booking_id = body.get("booking_id")
    if booking_id:
        b = q1("SELECT * FROM bookings WHERE id=?", (booking_id,))
        if not b:
            raise ApiError(404, "订舱不存在")
        voyage_id = voyage_id or b["voyage_id"]
    if voyage_id and not q1("SELECT id FROM voyages WHERE id=?", (voyage_id,)):
        raise ApiError(404, "航次不存在")
    c = execute("INSERT INTO containers(container_no,ctype,seal_no,voyage_id,booking_id,status) VALUES(?,?,?,?,?,?)",
                (no, ctype, body.get("seal_no"), voyage_id, booking_id, "empty"))
    bump_sync("containers")
    return {"id": c.lastrowid, "container_no": no}

CONTAINER_ACTIONS = {"to_full": "full", "to_in_transit": "in_transit",
                     "to_unloaded": "unloaded", "to_returned": "returned"}

def h_container_transition(ctx, m, qs, body):
    cid = int(m.group(1))
    r = q1("SELECT * FROM containers WHERE id=?", (cid,))
    if not r:
        raise ApiError(404, "集装箱不存在")
    action = body.get("action") or ""
    if action not in CONTAINER_ACTIONS:
        raise ApiError(422, "action 须为 to_full/to_in_transit/to_unloaded/to_returned")
    nxt = CONTAINER_ACTIONS[action]
    if not K.can_transition(K.CONTAINER_TRANS, r["status"], nxt):
        raise ApiError(422, "集装箱 %s 不允许 %s → %s" % (r["container_no"], r["status"], nxt))
    if nxt == "unloaded":
        execute("UPDATE containers SET status='unloaded', unloaded_at=?, version=version+1 WHERE id=?", (today_s(), cid))
    elif nxt == "returned":
        execute("UPDATE containers SET status='returned', returned_at=?, version=version+1 WHERE id=?", (today_s(), cid))
    else:
        execute("UPDATE containers SET status=?, version=version+1 WHERE id=?", (nxt, cid))
    bump_sync("containers")
    return {"ok": True, "status": nxt}

def h_container_update(ctx, m, qs, body):
    cid = int(m.group(1))
    r = q1("SELECT * FROM containers WHERE id=?", (cid,))
    if not r:
        raise ApiError(404, "集装箱不存在")
    if r["status"] in ("in_transit", "unloaded") and "seal_no" in body:
        raise ApiError(422, "在途/卸货后禁止修改封号")
    sets, params = [], []
    for f in ("ctype", "seal_no"):
        if f in body:
            if f == "ctype" and body[f] not in K.CTYPE_SET:
                raise ApiError(422, "ctype 非法")
            sets.append(f + "=?"); params.append(body[f])
    if sets:
        params.append(cid)
        execute("UPDATE containers SET " + ",".join(sets) + " WHERE id=?", params)
    bump_sync("containers")
    return {"ok": True}

def h_container_delete(ctx, m, qs, body):
    cid = int(m.group(1))
    r = q1("SELECT * FROM containers WHERE id=?", (cid,))
    if not r:
        raise ApiError(404, "集装箱不存在")
    if r["status"] not in ("empty", "full"):
        raise ApiError(422, "仅空箱/重箱可删除")
    execute("DELETE FROM containers WHERE id=?", (cid,))
    bump_sync("containers")
    return {"ok": True}

def h_container_demurrage(ctx, m, qs, body):
    cid = int(m.group(1))
    r = q1("SELECT * FROM containers WHERE id=?", (cid,))
    if not r:
        raise ApiError(404, "集装箱不存在")
    free = int(qs.get("free_days", [_rules_get("free_days", 4)])[0] or 4)
    rate = int(qs.get("rate_cents", [_rules_get("demurrage_rate_cents", 20000)])[0] or 20000)
    days = K.demurrage_days(r["unloaded_at"], r["returned_at"] or qs.get("as_of", [None])[0], free)
    return {"container_no": r["container_no"], "status": r["status"], "unloaded_at": r["unloaded_at"],
            "returned_at": r["returned_at"], "free_days": free, "demurrage_days": days,
            "demurrage_cents": K.demurrage_fee(days, rate), "rate_cents_per_day": rate}

# ---------- 提单 ----------

def _bl_ex(it):
    b = q1("SELECT no, status, consignee FROM bookings WHERE id=?", (it["booking_id"],))
    it["booking_no"] = b["no"] if b else None
    return it

def h_bl_list(ctx, m, qs, body):
    cond, params = "1=1", []
    if qs.get("status", [""])[0]:
        cond += " AND status=?"; params.append(qs["status"][0])
    if qs.get("booking_id", [""])[0]:
        cond += " AND booking_id=?"; params.append(int(qs["booking_id"][0]))
    kw = qs.get("keyword", [""])[0]
    if kw:
        cond += " AND (no LIKE ? OR shipper LIKE ? OR consignee LIKE ?)"; params += ["%" + kw + "%"] * 3
    return listwrap("SELECT * FROM bls WHERE " + cond + " ORDER BY id DESC", params, qs, _bl_ex)

def h_bl_create(ctx, m, qs, body):
    if not body.get("booking_id"):
        raise ApiError(422, "booking_id 必填")
    b = q1("SELECT * FROM bookings WHERE id=?", (body["booking_id"],))
    if not b:
        raise ApiError(404, "订舱不存在")
    if b["status"] == "cancelled":
        raise ApiError(422, "已取消订舱不能签发提单")
    no = make_no("BL", "bl_no")
    c = execute("INSERT INTO bls(no,booking_id,shipper,consignee,notify_party,cargo_desc,boxes) VALUES(?,?,?,?,?,?,?)",
                (no, body["booking_id"], body.get("shipper"), body.get("consignee"),
                 body.get("notify_party"), body.get("cargo_desc") or b["cargo_desc"],
                 int(body.get("boxes", b["boxes"]) or 1)))
    bump_sync("bls")
    return {"id": c.lastrowid, "no": no}

def h_bl_update(ctx, m, qs, body):
    blid = int(m.group(1))
    r = q1("SELECT * FROM bls WHERE id=?", (blid,))
    if not r:
        raise ApiError(404, "提单不存在")
    if r["status"] != "draft":
        raise ApiError(422, "仅草稿提单可修改")
    sets, params = [], []
    for f in ("shipper", "consignee", "notify_party", "cargo_desc", "boxes"):
        if f in body:
            sets.append(f + "=?"); params.append(body[f])
    if sets:
        params.append(blid)
        execute("UPDATE bls SET " + ",".join(sets) + " WHERE id=?", params)
    bump_sync("bls")
    return {"ok": True}

BL_ACTIONS = {"to_issued": "issued", "to_surrendered": "surrendered", "to_telex_released": "telex_released"}

def h_bl_transition(ctx, m, qs, body):
    blid = int(m.group(1))
    r = q1("SELECT * FROM bls WHERE id=?", (blid,))
    if not r:
        raise ApiError(404, "提单不存在")
    action = body.get("action") or ""
    if action not in BL_ACTIONS:
        raise ApiError(422, "action 须为 to_issued/to_surrendered/to_telex_released")
    nxt = BL_ACTIONS[action]
    if not K.can_transition(K.BL_TRANS, r["status"], nxt):
        raise ApiError(422, "提单 %s 不允许 %s → %s" % (r["no"], r["status"], nxt))
    execute("UPDATE bls SET status=?, version=version+1 WHERE id=?", (nxt, blid))
    if nxt == "issued":
        execute("UPDATE bls SET issued_at=? WHERE id=?", (now_s(), blid))
    bump_sync("bls")
    return {"ok": True, "status": nxt}

def h_bl_delete(ctx, m, qs, body):
    blid = int(m.group(1))
    r = q1("SELECT * FROM bls WHERE id=?", (blid,))
    if not r:
        raise ApiError(404, "提单不存在")
    if r["status"] != "draft":
        raise ApiError(422, "仅草稿提单可删除")
    execute("DELETE FROM bls WHERE id=?", (blid,))
    bump_sync("bls")
    return {"ok": True}

# ---------- 运价 ----------

def _rate_ex(it):
    it["expired"] = not K.rate_valid(today_s(), it["valid_from"], it["valid_to"])
    it["days_to_expire"] = K.rate_days_to_expire(today_s(), it["valid_to"])
    p1 = q1("SELECT code, name FROM ports WHERE id=?", (it["pol_id"],))
    p2 = q1("SELECT code, name FROM ports WHERE id=?", (it["pod_id"],))
    it["lane"] = "%s-%s" % (p1["code"] if p1 else "?", p2["code"] if p2 else "?")
    return it

def h_rate_list(ctx, m, qs, body):
    cond, params = "1=1", []
    if qs.get("pol_id", [""])[0]:
        cond += " AND pol_id=?"; params.append(int(qs["pol_id"][0]))
    if qs.get("pod_id", [""])[0]:
        cond += " AND pod_id=?"; params.append(int(qs["pod_id"][0]))
    if qs.get("ctype", [""])[0]:
        cond += " AND ctype=?"; params.append(qs["ctype"][0])
    if qs.get("active", [""])[0] == "1":
        cond += " AND valid_from<=? AND valid_to>=?"; params += [today_s(), today_s()]
    return listwrap("SELECT * FROM rates WHERE " + cond + " ORDER BY id DESC", params, qs, _rate_ex)

def h_rate_create(ctx, m, qs, body):
    for f in ("pol_id", "pod_id", "ctype", "valid_from", "valid_to"):
        if not body.get(f):
            raise ApiError(422, "%s 必填" % f)
    if body["pol_id"] == body["pod_id"]:
        raise ApiError(422, "起运港与目的港不能相同")
    if body["ctype"] not in K.CTYPE_SET:
        raise ApiError(422, "ctype 非法")
    if str(body["valid_from"]) > str(body["valid_to"]):
        raise ApiError(422, "valid_from 不得晚于 valid_to")
    base = int(body.get("base_cents", 0) or 0)
    if base <= 0:
        raise ApiError(422, "base_cents 必须为正数")
    c = execute("INSERT INTO rates(pol_id,pod_id,ctype,base_cents,surcharge_cents,valid_from,valid_to,note) VALUES(?,?,?,?,?,?,?,?)",
                (body["pol_id"], body["pod_id"], body["ctype"], base,
                 int(body.get("surcharge_cents", 0) or 0), body["valid_from"], body["valid_to"], body.get("note")))
    bump_sync("rates")
    return {"id": c.lastrowid}

def h_rate_update(ctx, m, qs, body):
    rid = int(m.group(1))
    r = q1("SELECT * FROM rates WHERE id=?", (rid,))
    if not r:
        raise ApiError(404, "运价不存在")
    sets, params = [], []
    for f in ("base_cents", "surcharge_cents", "valid_from", "valid_to", "note", "status"):
        if f in body:
            sets.append(f + "=?"); params.append(body[f])
    if sets:
        params.append(rid)
        execute("UPDATE rates SET " + ",".join(sets) + " WHERE id=?", params)
    bump_sync("rates")
    return {"ok": True}

def h_rate_delete(ctx, m, qs, body):
    rid = int(m.group(1))
    r = q1("SELECT * FROM rates WHERE id=?", (rid,))
    if not r:
        raise ApiError(404, "运价不存在")
    used = q1("""SELECT b.id FROM bookings b JOIN voyages v ON v.id=b.voyage_id
                 WHERE v.pol_id=? AND v.pod_id=? AND b.ctype=? AND b.status NOT IN ('cancelled','delivered') LIMIT 1""",
              (r["pol_id"], r["pod_id"], r["ctype"]))
    if used:
        raise ApiError(409, "运价被活跃订舱引用，禁止删除")
    execute("DELETE FROM rates WHERE id=?", (rid,))
    bump_sync("rates")
    return {"ok": True}

def h_rate_quote(ctx, m, qs, body):
    try:
        pol_id = int(qs.get("pol_id", ["0"])[0]); pod_id = int(qs.get("pod_id", ["0"])[0])
        boxes = max(1, int(qs.get("boxes", ["1"])[0] or 1))
    except ValueError:
        raise ApiError(422, "pol_id/pod_id/boxes 非法")
    ctype = qs.get("ctype", ["20GP"])[0]
    r = q1("SELECT * FROM rates WHERE pol_id=? AND pod_id=? AND ctype=? AND status='active' AND valid_from<=? AND valid_to>=? ORDER BY id DESC",
           (pol_id, pod_id, ctype, today_s(), today_s()))
    if not r:
        raise ApiError(404, "无有效运价（%s → %s %s）" % (pol_id, pod_id, ctype))
    total = K.freight_quote(r["base_cents"], r["surcharge_cents"], ctype, boxes)
    return {"pol_id": pol_id, "pod_id": pod_id, "ctype": ctype, "boxes": boxes,
            "base_cents": r["base_cents"], "surcharge_cents": r["surcharge_cents"],
            "unit_teu": K.teu_of(ctype), "total_cents": total, "rate_id": r["id"], "valid_to": r["valid_to"]}

# ---------- 客户 / 应收应付 ----------

def h_partner_list(ctx, m, qs, body):
    cond, params = "1=1", []
    if qs.get("ptype", [""])[0]:
        cond += " AND ptype=?"; params.append(qs["ptype"][0])
    kw = qs.get("keyword", [""])[0]
    if kw:
        cond += " AND (name LIKE ? OR code LIKE ?)"; params += ["%" + kw + "%"] * 2
    return listwrap("SELECT * FROM partners WHERE " + cond + " ORDER BY id", params, qs)

def h_partner_create(ctx, m, qs, body):
    if not body.get("name"):
        raise ApiError(422, "name 必填")
    ptype = body.get("ptype", "customer")
    if ptype not in ("customer", "agent", "supplier", "both"):
        raise ApiError(422, "ptype 须为 customer/agent/supplier/both")
    code = body.get("code") or (("C" if ptype in ("customer", "agent", "both") else "S") + "%04d" % next_seq("partner_code"))
    if q1("SELECT id FROM partners WHERE code=?", (code,)):
        raise ApiError(409, "编码已存在")
    c = execute("INSERT INTO partners(code, name, ptype, contact, phone, credit_limit_cents) VALUES(?,?,?,?,?,?)",
                (code, body["name"], ptype, body.get("contact"), body.get("phone"),
                 int(body.get("credit_limit_cents", 0) or 0)))
    bump_sync("partners")
    return {"id": c.lastrowid, "code": code}

def h_partner_update(ctx, m, qs, body):
    pid = int(m.group(1))
    if not q1("SELECT id FROM partners WHERE id=?", (pid,)):
        raise ApiError(404, "客户不存在")
    sets, params = [], []
    for f in ("name", "ptype", "contact", "phone", "credit_limit_cents", "status"):
        if f in body:
            sets.append(f + "=?"); params.append(body[f])
    if sets:
        params.append(pid)
        execute("UPDATE partners SET " + ",".join(sets) + " WHERE id=?", params)
    bump_sync("partners")
    return {"ok": True}

def h_partner_delete(ctx, m, qs, body):
    pid = int(m.group(1))
    if q1("SELECT id FROM bookings WHERE shipper_id=? LIMIT 1", (pid,)):
        raise ApiError(409, "客户已有订舱记录，禁止删除")
    if q1("SELECT id FROM bills WHERE partner_id=? LIMIT 1", (pid,)):
        raise ApiError(409, "客户有账单记录，禁止删除")
    execute("DELETE FROM partners WHERE id=?", (pid,))
    bump_sync("partners")
    return {"ok": True}

def h_partner_bills(ctx, m, qs, body):
    pid = int(m.group(1))
    if not q1("SELECT id FROM partners WHERE id=?", (pid,)):
        raise ApiError(404, "客户不存在")
    return listwrap("SELECT * FROM bills WHERE partner_id=? ORDER BY id DESC", (pid,), qs)

def h_bill_list(ctx, m, qs, body):
    cond, params = "1=1", []
    if qs.get("btype", [""])[0]:
        cond += " AND btype=?"; params.append(qs["btype"][0])
    if qs.get("partner_id", [""])[0]:
        cond += " AND partner_id=?"; params.append(int(qs["partner_id"][0]))
    if qs.get("overdue", [""])[0]:
        cond += " AND due_date < ? AND settled_cents < amount_cents"
        params.append(today_s())
    def ex(it):
        d = dict(it)
        d["remaining_cents"] = K.bill_remaining(it)
        d["days_overdue"] = K.days_overdue(it["due_date"]) if d["remaining_cents"] > 0 else 0
        d["aging"] = K.aging_bucket(d["days_overdue"]) if d["days_overdue"] > 0 else None
        d["status"] = "settled" if d["remaining_cents"] <= 0 else ("partial" if it["settled_cents"] > 0 else "open")
        it.update(d)
        return it
    return listwrap("SELECT * FROM bills WHERE " + cond + " ORDER BY id DESC", params, qs, ex)

def h_bill_get(ctx, m, qs, body):
    bid = int(m.group(1))
    r = q1("SELECT * FROM bills WHERE id=?", (bid,))
    if not r:
        raise ApiError(404, "账单不存在")
    d = dict(r)
    d["remaining_cents"] = K.bill_remaining(r)
    d["settlements"] = [dict(x) for x in q("SELECT * FROM bill_settlements WHERE bill_id=? ORDER BY id", (bid,))]
    return d

def h_bill_create(ctx, m, qs, body):
    if not body.get("btype") or not body.get("partner_id"):
        raise ApiError(422, "btype/partner_id 必填")
    if body["btype"] not in ("receivable", "payable", "demurrage"):
        raise ApiError(422, "btype 须为 receivable/payable/demurrage")
    p = q1("SELECT * FROM partners WHERE id=?", (body["partner_id"],))
    if not p:
        raise ApiError(404, "客户不存在")
    amt = int(body.get("amount_cents", 0) or 0)
    if amt <= 0:
        raise ApiError(422, "amount_cents 必须为正数")
    prefix = "AP" if body["btype"] == "payable" else "AR"
    no = make_no(prefix, "bill_no")
    c = execute("INSERT INTO bills(no, btype, partner_id, amount_cents, settled_cents, due_date, ref) VALUES(?,?,?,?,0,?,?)",
                (no, body["btype"], body["partner_id"], amt, body.get("due_date"), body.get("ref")))
    if body["btype"] == "payable":
        execute("UPDATE partners SET payable_cents=payable_cents+? WHERE id=?", (amt, body["partner_id"]))
    else:
        execute("UPDATE partners SET receivable_cents=receivable_cents+? WHERE id=?", (amt, body["partner_id"]))
    if body["btype"] != "payable" and K.over_credit(p["receivable_cents"] + amt, p["credit_limit_cents"]):
        execute("INSERT INTO risks(rtype, ref_id, title, detail, score, grade) VALUES('over_credit',?,?,?,35,'risk')",
                (p["id"], "客户信用超限", "%s 应收合计将超过信用额度 %d 分" % (p["name"], p["credit_limit_cents"])))
    bump_sync("bills"); bump_sync("partners")
    return {"id": c.lastrowid, "no": no}

def h_bill_settle(ctx, m, qs, body):
    bid = int(m.group(1))
    r = q1("SELECT * FROM bills WHERE id=?", (bid,))
    if not r:
        raise ApiError(404, "账单不存在")
    remain = K.bill_remaining(r)
    if remain <= 0:
        raise ApiError(422, "账单已结清")
    pay = K.settle_amount(r, body.get("amount_cents", remain))
    if pay <= 0:
        raise ApiError(422, "amount_cents 必须为正数")
    method = body.get("method", "bank")
    execute("INSERT INTO bill_settlements(bill_id, amount_cents, method, note) VALUES(?,?,?,?)",
            (bid, pay, method, body.get("note")))
    settled = int(r["settled_cents"]) + pay
    status = "settled" if settled >= int(r["amount_cents"]) else "partial"
    execute("UPDATE bills SET settled_cents=?, version=version+1 WHERE id=?", (settled, bid))
    col = "payable_cents" if r["btype"] == "payable" else "receivable_cents"
    execute("UPDATE partners SET %s=MAX(0, %s-?) WHERE id=?" % (col, col), (pay, r["partner_id"]))
    execute("INSERT INTO flows(no, ftype, category, amount_cents, counter_party, partner_id, summary, created_by) VALUES(?,?,?,?,?,?,?,?)",
            (make_no("SR", "flow_no"),
             "income" if r["btype"] != "payable" else "expense",
             "运费" if r["btype"] == "receivable" else ("滞箱费" if r["btype"] == "demurrage" else "应付出账"),
             pay, method, r["partner_id"], "结算 " + r["no"],
             ctx["user"].get("username") or ""))
    bump_sync("bills"); bump_sync("partners"); bump_sync("flows")
    return {"ok": True, "settled_cents": settled, "remaining_cents": int(r["amount_cents"]) - settled, "status": status}

def h_bill_delete(ctx, m, qs, body):
    bid = int(m.group(1))
    r = q1("SELECT * FROM bills WHERE id=?", (bid,))
    if not r:
        raise ApiError(404, "账单不存在")
    if int(r["settled_cents"] or 0) > 0:
        raise ApiError(422, "已有结算记录，禁止删除")
    execute("DELETE FROM bills WHERE id=?", (bid,))
    bump_sync("bills")
    return {"ok": True}

# ---------- 报表 / 跟踪 ----------

def h_report_voyage(ctx, m, qs, body):
    month = qs.get("month", [""])[0] or None
    cond, params = "1=1", []
    if month:
        cond = "substr(etd,1,7)=?"; params = [month]
    rows = [dict(r) for r in q("SELECT * FROM voyages WHERE " + cond, params)]
    items = []
    for r in rows:
        _voyage_ex(r)
        bk = q1("SELECT COUNT(*) c FROM bookings WHERE voyage_id=? AND status NOT IN ('cancelled')", (r["id"],))["c"]
        dlv = q1("SELECT COUNT(*) c FROM bookings WHERE voyage_id=? AND status='delivered'", (r["id"],))["c"]
        items.append({"no": r["no"], "vessel_name": r["vessel_name"], "lane": "%s→%s" % (r["pol"], r["pod"]),
                      "etd": r["etd"], "eta": r["eta"], "status": r["status"],
                      "boxes": r["boxes"], "loaded_teu": r["loaded_teu"], "bookings": bk, "delivered": dlv})
    return {"month": month, "items": items,
            "voyages": len(items),
            "total_teu": sum(i["loaded_teu"] for i in items)}

def h_report_lane(ctx, m, qs, body):
    month = qs.get("month", [""])[0] or None
    cond, params = "1=1", []
    if month:
        cond = "substr(v.etd,1,7)=?"; params = [month]
    rows = q("""SELECT p1.code pol, p2.code pod, b.ctype, COUNT(*) tickets,
                SUM(b.boxes) boxes,
                SUM(CASE WHEN b.ctype LIKE '40%%' OR b.ctype LIKE '45%%' THEN b.boxes*2 ELSE b.boxes END) teu
                FROM bookings b JOIN voyages v ON v.id=b.voyage_id
                JOIN ports p1 ON p1.id=v.pol_id JOIN ports p2 ON p2.id=v.pod_id
                WHERE %s AND b.status NOT IN ('cancelled')
                GROUP BY p1.code, p2.code, b.ctype ORDER BY tickets DESC""" % cond, params)
    return {"month": month, "items": [dict(r) for r in rows]}

def h_track(ctx, m, qs, body):
    no = urllib.parse.unquote(m.group(1)).strip().upper()
    bk = q1("SELECT * FROM bookings WHERE no=?", (no,))
    ct = q1("SELECT * FROM containers WHERE container_no=?", (no,))
    bl = q1("SELECT * FROM bls WHERE no=?", (no,))
    if not bk and not ct and not bl:
        raise ApiError(404, "未找到单证: %s" % no)
    events = []
    booking_id = (bk or ct or bl)["booking_id"] if (ct or bl) else (bk["id"] if bk else None)
    voyage_id = ct["voyage_id"] if ct else None
    if bk:
        events.append({"ts": bk["created_at"], "what": "订舱 %s：托运 %s，%s，%d×%s" % (bk["no"], bk["consignee"] or "", bk["cargo_desc"] or "", bk["boxes"], bk["ctype"])})
        events.append({"ts": bk["created_at"], "what": "订舱状态: " + bk["status"]})
        voyage_id = bk["voyage_id"]
    if bl:
        events.append({"ts": bl["issued_at"] or bl["created_at"], "what": "提单 %s（%s）" % (bl["no"], bl["status"])})
    if ct:
        events.append({"ts": ct["created_at"], "what": "箱 %s 建档（%s，封号 %s）" % (ct["container_no"], ct["ctype"], ct["seal_no"] or "-")})
        if ct["unloaded_at"]:
            events.append({"ts": ct["unloaded_at"], "what": "卸箱（%s）" % ct["container_no"]})
        if ct["returned_at"]:
            events.append({"ts": ct["returned_at"], "what": "还箱（%s）" % ct["container_no"]})
        events.append({"ts": ct["created_at"], "what": "箱状态: " + ct["status"]})
    if booking_id:
        b = q1("SELECT * FROM bookings WHERE id=?", (booking_id,))
        if b:
            voyage_id = b["voyage_id"]
            if not bk:
                events.append({"ts": b["created_at"], "what": "订舱 %s（%s %d×%s）" % (b["no"], b["cargo_desc"] or "", b["boxes"], b["ctype"])})
    if voyage_id:
        v = q1("""SELECT v.*, p1.name poln, p2.name podn FROM voyages v
                  JOIN ports p1 ON p1.id=v.pol_id JOIN ports p2 ON p2.id=v.pod_id WHERE v.id=?""", (voyage_id,))
        if v:
            events.append({"ts": v["atd"] or v["etd"], "what": "航次 %s %s → %s（%s）" % (v["no"], v["poln"], v["podn"], v["status"])})
    events = [e for e in events if e["ts"]]
    events.sort(key=lambda e: e["ts"])
    return {"query": no, "events": events}

# ---------- 风险 ----------

def h_risk_list(ctx, m, qs, body):
    cond, params = "1=1", []
    for f in ("status", "grade", "rtype"):
        if qs.get(f, [""])[0]:
            cond += " AND %s=?" % f; params.append(qs[f][0])
    return listwrap("SELECT * FROM risks WHERE " + cond + " ORDER BY id DESC", params, qs)

def h_risk_scan(ctx, m, qs, body):
    created = 0
    by_type = {}
    today = datetime.date.today()
    def _exists(rtype, ref_id):
        return q1("SELECT id FROM risks WHERE rtype=? AND ref_id=? AND status='open'", (rtype, ref_id))
    # 1 滞箱超免箱期
    free = _rules_get("free_days", 4)
    rate = _rules_get("demurrage_rate_cents", 20000)
    for r in q("SELECT id, container_no, unloaded_at FROM containers WHERE status='unloaded' AND unloaded_at IS NOT NULL"):
        dd = K.demurrage_days(r["unloaded_at"], None, free)
        if dd > 0 and not _exists("demurrage_over", r["id"]):
            fee = K.demurrage_fee(dd, rate)
            execute("INSERT INTO risks(rtype, ref_id, title, detail, score, grade) VALUES('demurrage_over',?,?,?,40,'risk')",
                    (r["id"], "滞箱超期", "%s 卸箱于 %s，超免箱期 %d 天，预计滞箱费 %d 分" % (r["container_no"], r["unloaded_at"], dd, fee)))
            created += 1; by_type["demurrage_over"] = by_type.get("demurrage_over", 0) + 1
    # 2 应收逾期（含账龄）
    for r in q("SELECT b.id, b.no, b.due_date, b.amount_cents, b.settled_cents, p.name FROM bills b JOIN partners p ON p.id=b.partner_id WHERE b.btype IN ('receivable','demurrage') AND b.due_date IS NOT NULL AND b.due_date < ? AND b.settled_cents < b.amount_cents", (today.isoformat(),)):
        if not _exists("bill_overdue", r["id"]):
            dd = K.days_overdue(r["due_date"], today)
            execute("INSERT INTO risks(rtype, ref_id, title, detail, score, grade) VALUES('bill_overdue',?,?,?,40,'risk')",
                    (r["id"], "应收逾期", "%s（%s）逾期 %d 天（账龄 %s），未结 %d 分" %
                     (r["name"], r["no"], dd, K.aging_bucket(dd), r["amount_cents"] - r["settled_cents"])))
            created += 1; by_type["bill_overdue"] = by_type.get("bill_overdue", 0) + 1
    # 3 航次超载
    for r in q("SELECT v.id, v.no, v.vessel_id, vs.teu FROM voyages v JOIN vessels vs ON vs.id=v.vessel_id WHERE v.status NOT IN ('cancelled','closed')"):
        loaded = _voyage_loaded_teu(r["vessel_id"], r["id"])
        over, _ = K.voyage_load_check(loaded, r["teu"])
        if over and not _exists("voyage_overload", r["id"]):
            execute("INSERT INTO risks(rtype, ref_id, title, detail, score, grade) VALUES('voyage_overload',?,?,?,45,'risk')",
                    (r["id"], "航次超载", "%s 装载 %.0f TEU 超过船舶箱位 %d TEU" % (r["no"], loaded, r["teu"])))
            created += 1; by_type["voyage_overload"] = by_type.get("voyage_overload", 0) + 1
    # 4 运价临期/过期（7 天内到期或已过期且仍被活跃订舱引用）
    for r in q("SELECT id, pol_id, pod_id, ctype, valid_to FROM rates WHERE status='active'"):
        if K.rate_days_to_expire(today.isoformat(), r["valid_to"]) > 7:
            continue
        used = q1("""SELECT b.id FROM bookings b JOIN voyages v ON v.id=b.voyage_id
                     WHERE v.pol_id=? AND v.pod_id=? AND b.ctype=? AND b.status NOT IN ('cancelled','delivered') LIMIT 1""",
                  (r["pol_id"], r["pod_id"], r["ctype"]))
        if used and not _exists("rate_expired", r["id"]):
            execute("INSERT INTO risks(rtype, ref_id, title, detail, score, grade) VALUES('rate_expired',?,?,?,25,'warn')",
                    (r["id"], "运价临期", "%s→%s %s 运价将于 %s 到期/已到期，仍有活跃订舱引用" %
                     (r["pol_id"], r["pod_id"], r["ctype"], r["valid_to"])))
            created += 1; by_type["rate_expired"] = by_type.get("rate_expired", 0) + 1
    return {"created": created, "by_type": by_type}

def h_risk_resolve(ctx, m, qs, body):
    rid = int(m.group(1))
    r = q1("SELECT * FROM risks WHERE id=?", (rid,))
    if not r:
        raise ApiError(404, "风险不存在")
    if r["status"] != "open":
        raise ApiError(422, "风险已处理")
    execute("UPDATE risks SET status='resolved', resolved_by=?, note=? WHERE id=?",
            (ctx["user"].get("name") or "", body.get("note"), rid))
    return {"ok": True}

# ---------- 仪表盘 ----------

def h_dashboard(ctx, m, qs, body):
    month = time.strftime("%Y-%m")
    voy_active = q1("SELECT COUNT(*) c FROM voyages WHERE status IN ('planned','departed','arrived')")["c"]
    voy_month = q1("SELECT COUNT(*) c FROM voyages WHERE substr(etd,1,7)=?", (month,))["c"]
    bk_open = q1("SELECT COUNT(*) c FROM bookings WHERE status IN ('booked','loaded','shipped')")["c"]
    boxes_at_sea = q1("SELECT COUNT(*) c FROM containers WHERE status='in_transit'")["c"]
    teu_at_sea = q1("SELECT COALESCE(SUM(CASE WHEN ctype LIKE '40%' OR ctype LIKE '45%' THEN 2 ELSE 1 END),0) c FROM containers WHERE status='in_transit'")["c"]
    bl_draft = q1("SELECT COUNT(*) c FROM bls WHERE status='draft'")["c"]
    ar_open = q1("SELECT COALESCE(SUM(amount_cents-settled_cents),0) s FROM bills WHERE btype IN ('receivable','demurrage') AND settled_cents<amount_cents")["s"]
    ap_open = q1("SELECT COALESCE(SUM(amount_cents-settled_cents),0) s FROM bills WHERE btype='payable' AND settled_cents<amount_cents")["s"]
    demurr = 0
    free = _rules_get("free_days", 4); rate = _rules_get("demurrage_rate_cents", 20000)
    for r in q("SELECT unloaded_at FROM containers WHERE status='unloaded' AND unloaded_at IS NOT NULL"):
        demurr += K.demurrage_fee(K.demurrage_days(r["unloaded_at"], None, free), rate)
    open_risks = q1("SELECT COUNT(*) c FROM risks WHERE status='open'")["c"]
    return {"month": month, "voyages_active": voy_active, "voyages_month": voy_month,
            "bookings_open": bk_open, "containers_at_sea": boxes_at_sea, "teu_at_sea": int(teu_at_sea),
            "bls_draft": bl_draft, "receivable_open_cents": int(ar_open), "payable_open_cents": int(ap_open),
            "demurrage_est_cents": int(demurr), "open_risks": open_risks}

# ---------- 平台域 ----------

def h_notices(ctx, m, qs, body):
    return listwrap("SELECT * FROM notices ORDER BY id DESC", (), qs)

def h_notices_create(ctx, m, qs, body):
    if not body.get("title"):
        raise ApiError(422, "title 必填")
    c = execute("INSERT INTO notices(title,content,level) VALUES(?,?,?)",
                (body["title"], body.get("content", ""), body.get("level", "info")))
    return {"id": c.lastrowid}

def h_notices_delete(ctx, m, qs, body):
    execute("DELETE FROM notices WHERE id=?", (int(m.group(1)),))
    return {"ok": True}

def h_logs(ctx, m, qs, body):
    return listwrap("SELECT * FROM logs ORDER BY id DESC", (), qs)

def h_flows(ctx, m, qs, body):
    cond, params = "1=1", []
    if qs.get("ftype", [""])[0]:
        cond += " AND ftype=?"; params.append(qs["ftype"][0])
    if qs.get("category", [""])[0]:
        cond += " AND category=?"; params.append(qs["category"][0])
    kw = qs.get("keyword", [""])[0]
    if kw:
        cond += " AND (summary LIKE ? OR no LIKE ?)"; params += ["%" + kw + "%"] * 2
    return listwrap("SELECT * FROM flows WHERE " + cond + " ORDER BY id DESC", params, qs)

def h_rules(ctx, m, qs, body):
    return {"items": [dict(r) for r in q("SELECT * FROM oy_rules ORDER BY id")]}

def h_rules_update(ctx, m, qs, body):
    name = body.get("name")
    if not name:
        raise ApiError(422, "name 必填")
    if not q1("SELECT id FROM oy_rules WHERE name=?", (name,)):
        execute("INSERT INTO oy_rules(name,value,updated_at) VALUES(?,?,?)", (name, body.get("value", ""), now_s()))
    else:
        execute("UPDATE oy_rules SET value=?, updated_at=? WHERE name=?", (body.get("value", ""), now_s(), name))
    return {"ok": True}

# ---------- 增量同步 / 导出 ----------

SYNC_ENTITIES = {
    "ports": "SELECT * FROM ports ORDER BY id",
    "vessels": "SELECT * FROM vessels ORDER BY id",
    "voyages": "SELECT * FROM voyages ORDER BY id",
    "bookings": "SELECT * FROM bookings ORDER BY id",
    "containers": "SELECT * FROM containers ORDER BY id",
    "bls": "SELECT * FROM bls ORDER BY id",
    "rates": "SELECT * FROM rates ORDER BY id",
    "partners": "SELECT * FROM partners ORDER BY id",
    "bills": "SELECT * FROM bills ORDER BY id",
    "risks": "SELECT * FROM risks ORDER BY id",
}

def h_sync(ctx, m, qs, body):
    since = int(qs.get("since", ["0"])[0] or 0)
    ents = [e for e in (qs.get("entities", [""])[0] or "").split(",") if e]
    if not ents:
        ents = list(SYNC_ENTITIES.keys())
    changes, maxver = [], 0
    for e in ents:
        if e not in SYNC_ENTITIES:
            raise ApiError(422, "未知同步实体: %s" % e)
        v = get_sync(e)
        maxver = max(maxver, v)
        if v > since:
            rows = [dict(r) for r in q(SYNC_ENTITIES[e])]
            for r in rows:
                changes.append({"entity": e, "op": "upsert", "row": r})
    return {"version": maxver, "since": since, "changes": changes}

EXPORTS = {
    "ports": ("SELECT * FROM ports ORDER BY id", ["code", "name", "country", "status"]),
    "vessels": ("SELECT * FROM vessels ORDER BY id", ["code", "name", "imo", "vtype", "dwt", "teu", "flag", "status"]),
    "voyages": ("SELECT * FROM voyages ORDER BY id", ["no", "vessel_id", "pol_id", "pod_id", "etd", "eta", "status"]),
    "bookings": ("SELECT * FROM bookings ORDER BY id", ["no", "voyage_id", "shipper_id", "cargo_desc", "boxes", "ctype", "status"]),
    "containers": ("SELECT * FROM containers ORDER BY id", ["container_no", "ctype", "seal_no", "status", "unloaded_at", "returned_at"]),
    "bls": ("SELECT * FROM bls ORDER BY id", ["no", "booking_id", "shipper", "consignee", "boxes", "status"]),
    "rates": ("SELECT * FROM rates ORDER BY id", ["pol_id", "pod_id", "ctype", "base_cents", "surcharge_cents", "valid_from", "valid_to"]),
    "bills": ("SELECT * FROM bills ORDER BY id", ["no", "btype", "partner_id", "amount_cents", "settled_cents", "due_date"]),
}

def h_export(ctx, m, qs, body):
    ent = m.group(1)
    if ent not in EXPORTS:
        raise ApiError(404, "未知导出实体")
    sql, cols = EXPORTS[ent]
    return ("csv", csv_export(q(sql), cols))

# ---------- 路由表 ----------

ROUTES = [
    ("GET",  r"^/api/health$", h_health, None),
    ("POST", r"^/api/login$", h_login, None),
    ("POST", r"^/api/logout$", h_logout, "auth"),
    ("GET",  r"^/api/me$", h_me, "auth"),
    ("GET",  r"^/api/users$", h_users, "admin"),
    ("POST", r"^/api/users$", h_users_create, "admin"),
    ("PUT",  r"^/api/users/(\d+)$", h_users_update, "admin"),
    ("DELETE", r"^/api/users/(\d+)$", h_users_delete, "admin"),
    ("GET",  r"^/api/api-keys$", h_keys, "admin"),
    ("POST", r"^/api/api-keys$", h_keys_create, "admin"),
    ("DELETE", r"^/api/api-keys/(\d+)$", h_keys_delete, "admin"),
    ("GET",  r"^/api/ports$", h_port_list, "sea.ports.read"),
    ("POST", r"^/api/ports$", h_port_create, "sea.ports.write"),
    ("PUT",  r"^/api/ports/(\d+)$", h_port_update, "sea.ports.write"),
    ("DELETE", r"^/api/ports/(\d+)$", h_port_delete, "sea.ports.write"),
    ("GET",  r"^/api/vessels$", h_vessel_list, "sea.vessels.read"),
    ("POST", r"^/api/vessels$", h_vessel_create, "sea.vessels.write"),
    ("PUT",  r"^/api/vessels/(\d+)$", h_vessel_update, "sea.vessels.write"),
    ("DELETE", r"^/api/vessels/(\d+)$", h_vessel_delete, "sea.vessels.write"),
    ("GET",  r"^/api/vessels/(\d+)/voyages$", h_vessel_voyages, "sea.vessels.read"),
    ("GET",  r"^/api/voyages$", h_voyage_list, "sea.voyages.read"),
    ("POST", r"^/api/voyages$", h_voyage_create, "sea.voyages.write"),
    ("GET",  r"^/api/voyages/(\d+)$", h_voyage_get, "sea.voyages.read"),
    ("PUT",  r"^/api/voyages/(\d+)$", h_voyage_update, "sea.voyages.write"),
    ("DELETE", r"^/api/voyages/(\d+)$", h_voyage_delete, "sea.voyages.write"),
    ("POST", r"^/api/voyages/(\d+)/transition$", h_voyage_transition, "sea.voyages.write"),
    ("GET",  r"^/api/bookings$", h_booking_list, "sea.bookings.read"),
    ("POST", r"^/api/bookings$", h_booking_create, "sea.bookings.create"),
    ("GET",  r"^/api/bookings/(\d+)$", h_booking_get, "sea.bookings.read"),
    ("PUT",  r"^/api/bookings/(\d+)$", h_booking_update, "sea.bookings.write"),
    ("DELETE", r"^/api/bookings/(\d+)$", h_booking_delete, "sea.bookings.write"),
    ("POST", r"^/api/bookings/(\d+)/transition$", h_booking_transition, "sea.bookings.write"),
    ("GET",  r"^/api/containers$", h_container_list, "sea.containers.read"),
    ("POST", r"^/api/containers$", h_container_create, "sea.containers.write"),
    ("PUT",  r"^/api/containers/(\d+)$", h_container_update, "sea.containers.write"),
    ("DELETE", r"^/api/containers/(\d+)$", h_container_delete, "sea.containers.write"),
    ("POST", r"^/api/containers/(\d+)/transition$", h_container_transition, "sea.containers.write"),
    ("GET",  r"^/api/containers/(\d+)/demurrage$", h_container_demurrage, "sea.containers.read"),
    ("GET",  r"^/api/bls$", h_bl_list, "sea.bls.read"),
    ("POST", r"^/api/bls$", h_bl_create, "sea.bls.write"),
    ("PUT",  r"^/api/bls/(\d+)$", h_bl_update, "sea.bls.write"),
    ("DELETE", r"^/api/bls/(\d+)$", h_bl_delete, "sea.bls.write"),
    ("POST", r"^/api/bls/(\d+)/transition$", h_bl_transition, "sea.bls.write"),
    ("GET",  r"^/api/rates$", h_rate_list, "sea.rates.read"),
    ("POST", r"^/api/rates$", h_rate_create, "sea.rates.write"),
    ("PUT",  r"^/api/rates/(\d+)$", h_rate_update, "sea.rates.write"),
    ("DELETE", r"^/api/rates/(\d+)$", h_rate_delete, "sea.rates.write"),
    ("GET",  r"^/api/rates/quote$", h_rate_quote, "sea.rates.read"),
    ("GET",  r"^/api/partners$", h_partner_list, "sea.partners.read"),
    ("POST", r"^/api/partners$", h_partner_create, "sea.partners.write"),
    ("PUT",  r"^/api/partners/(\d+)$", h_partner_update, "sea.partners.write"),
    ("DELETE", r"^/api/partners/(\d+)$", h_partner_delete, "sea.partners.write"),
    ("GET",  r"^/api/partners/(\d+)/bills$", h_partner_bills, "sea.partners.read"),
    ("GET",  r"^/api/bills$", h_bill_list, "sea.bills.read"),
    ("POST", r"^/api/bills$", h_bill_create, "sea.bills.write"),
    ("GET",  r"^/api/bills/(\d+)$", h_bill_get, "sea.bills.read"),
    ("DELETE", r"^/api/bills/(\d+)$", h_bill_delete, "sea.bills.write"),
    ("POST", r"^/api/bills/(\d+)/settle$", h_bill_settle, "sea.bills.write"),
    ("GET",  r"^/api/flows$", h_flows, "sea.bills.read"),
    ("GET",  r"^/api/reports/voyage-summary$", h_report_voyage, "sea.reports.read"),
    ("GET",  r"^/api/reports/lane-stats$", h_report_lane, "sea.reports.read"),
    ("GET",  r"^/api/track/([^/]+)$", h_track, "sea.track.read"),
    ("GET",  r"^/api/risks$", h_risk_list, "sea.risk.read"),
    ("POST", r"^/api/risks/scan$", h_risk_scan, "sea.risk.write"),
    ("PUT",  r"^/api/risks/(\d+)/resolve$", h_risk_resolve, "sea.risk.write"),
    ("GET",  r"^/api/dashboard$", h_dashboard, "auth"),
    ("GET",  r"^/api/notices$", h_notices, "auth"),
    ("POST", r"^/api/notices$", h_notices_create, "admin"),
    ("DELETE", r"^/api/notices/(\d+)$", h_notices_delete, "admin"),
    ("GET",  r"^/api/logs$", h_logs, "admin"),
    ("GET",  r"^/api/rules$", h_rules, "auth"),
    ("PUT",  r"^/api/rules$", h_rules_update, "admin"),
    ("GET",  r"^/api/sync$", h_sync, "auth"),
    ("GET",  r"^/api/export/([a-z]+)$", h_export, "auth"),
]

_COMPILED = [(mt, re.compile(rx), fn, perm) for mt, rx, fn, perm in ROUTES]

# ---------- HTTP Handler ----------

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "FeiYangOTMS/1.0"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, data, ctype="application/json; charset=utf-8", extra=None):
        body = data if isinstance(data, bytes) else data.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Token, X-Api-Key, Idempotency-Key")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_json(self, code, data):
        if isinstance(data, str):
            self._send(code, jdump({"code": code, "message": data, "data": None}))
        else:
            self._send(code, jdump({"code": code, "message": "ok" if code < 400 else "error", "data": data}))

    def _body(self):
        ln = int(self.headers.get("Content-Length") or 0)
        if ln <= 0:
            return {}
        raw = self.rfile.read(ln)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def _token_from_req(self):
        h = self.headers
        auth = h.get("Authorization") or ""
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        if h.get("X-Token"):
            return h["X-Token"].strip()
        ck = h.get("Cookie")
        if ck:
            try:
                c = http_cookies.SimpleCookie(ck)
                if "feiyang_token" in c:
                    return c["feiyang_token"].value
                if "token" in c:
                    return c["token"].value
            except Exception:
                pass
        if h.get("X-Api-Key"):
            return "key:" + h["X-Api-Key"].strip()
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if "token" in qs:
            return qs["token"][0]
        return None

    def _authenticate(self):
        tok = self._token_from_req()
        if not tok:
            return None, None
        if tok.startswith("key:"):
            u = auth_key(tok[4:])
            return ({"id": None, **u} if u else None), tok
        u = auth_token(tok)
        if u:
            perms = K.ROLE_PERMS.get(u["role"], K.ROLE_PERMS["reader"])
            return {"id": u["user_id"], "username": u["username"], "name": u["name"], "role": u["role"], "perms": perms}, tok
        return None, tok

    def _match_route(self, method, path):
        for mt, rx, fn, perm in _COMPILED:
            if mt != method:
                continue
            m = rx.match(path)
            if m:
                return fn, perm, m
        return None, None, None

    def _handle(self, method):
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            if PREFIX and path.startswith(PREFIX):
                path = path[len(PREFIX):] or "/"
            if method == "OPTIONS":
                return self._send(200, "{}")
            if not path.startswith("/api/"):
                return self._static(path)
            qs = urllib.parse.parse_qs(parsed.query)
            fn, perm, m = self._match_route(method, path)
            if not fn:
                return self._send_json(404, "接口不存在: %s" % path)
            user, tok = self._authenticate()
            ctx = {"user": user or {}, "token": (tok or "").replace("key:", "")}
            if perm is not None and not user:
                return self._send_json(401, "未认证")
            if perm == "admin":
                if not user or user.get("role") != "admin":
                    return self._send_json(403, "需要管理员权限")
            elif perm == "auth":
                if not user:
                    return self._send_json(401, "未认证")
            elif perm:
                perms = user.get("perms") if user else None
                if not user or not K.has_perm(perms or [], perm):
                    return self._send_json(403, "无权限: " + perm)
            body = self._body() if method in ("POST", "PUT", "DELETE") else {}
            idem = self.headers.get("Idempotency-Key")
            if idem and method == "POST":
                row = q1("SELECT response FROM idem_keys WHERE key=?", (idem,))
                if row:
                    return self._send(200, row["response"])
            result = fn(ctx, m, qs, body)
            if isinstance(result, tuple) and result[0] == "csv":
                return self._send(200, result[1], ctype="text/csv; charset=utf-8",
                                  extra={"Content-Disposition": "attachment; filename=export.csv"})
            payload = jdump({"code": 200, "message": "ok", "data": result})
            if idem and method == "POST":
                execute("INSERT OR REPLACE INTO idem_keys(key, user_id, response, created_at) VALUES(?,?,?,?)",
                        (idem, user.get("id") if user else None, payload, now_s()))
            return self._send(200, payload)
        except ApiError as e:
            return self._send_json(e.code, e.message)
        except Exception as e:
            traceback.print_exc()
            return self._send_json(500, "内部错误: %s" % e)

    def _static(self, path):
        if path in ("/", "/index.html", ""):
            path = "/index.html"
        fp = os.path.join(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend"), path.lstrip("/"))
        fp = os.path.normpath(fp)
        if not fp.startswith(os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))):
            return self._send(403, "forbidden", ctype="text/plain")
        if not os.path.isfile(fp):
            return self._send(404, "not found", ctype="text/plain")
        ctype = {"html": "text/html; charset=utf-8", "js": "application/javascript; charset=utf-8",
                 "css": "text/css; charset=utf-8", "svg": "image/svg+xml", "png": "image/png", "ico": "image/x-icon"}.get(fp.rsplit(".", 1)[-1], "application/octet-stream")
        with open(fp, "rb") as f:
            return self._send(200, f.read(), ctype=ctype)

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_DELETE(self):
        self._handle("DELETE")

    def do_OPTIONS(self):
        self._handle("OPTIONS")

def main():
    D.init_db()
    S.run()
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("FeiYang OTMS listening on :%d prefix=%r db=%s" % (PORT, PREFIX, D.DB_PATH))
    srv.serve_forever()

if __name__ == "__main__":
    main()

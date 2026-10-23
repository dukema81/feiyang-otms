# -*- coding: utf-8 -*-
"""飞洋 OTMS 种子数据（仅空库时执行）"""
import os, hashlib
import db as D
import ocean as K

def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def run():
    if D.q1("SELECT id FROM users LIMIT 1"):
        return
    c = D.get_db()
    c.executescript("""
    INSERT INTO seq(name,val) VALUES
      ('voyage_no',3),('booking_no',3),('bl_no',2),('bill_no',2),('flow_no',1),
      ('partner_code',3),('vessel_code',2);
    INSERT INTO sync_state(entity,version) VALUES
      ('ports',1),('vessels',1),('voyages',1),('bookings',1),('containers',1),
      ('bls',1),('rates',1),('partners',1),('bills',1),('flows',1),('risks',1);
    INSERT INTO users(username,password,name,role,phone) VALUES
      ('admin','%s','系统管理员','admin','13800000001'),
      ('zhangk','%s','张可','ops','13800000002'),
      ('liq','%s','李强','finance','13800000003'),
      ('wangw','%s','王雯','doc','13800000004'),
      ('zhaoa','%s','赵安','agent','13800000005'),
      ('reader01','%s','只读用户','reader01',NULL);
    INSERT INTO oy_rules(name,value) VALUES
      ('free_days','4'),('demurrage_rate_cents','20000'),('company','飞洋航运有限公司');
    INSERT INTO notices(title,content,level) VALUES
      ('欢迎使用飞洋海洋运输管理系统','零依赖海运 OTMS：船舶/航次/订舱/提单/箱货/运价全流程。','info');
    """ % tuple([sha("123456")] * 6))

    # 港口
    for code, name, country in [("CNSHA", "上海港", "中国"), ("CNNGB", "宁波港", "中国"),
                                ("SGSIN", "新加坡港", "新加坡"), ("NLRTM", "鹿特丹港", "荷兰"),
                                ("USLAX", "洛杉矶港", "美国")]:
        D.execute("INSERT INTO ports(code,name,country) VALUES(?,?,?)", (code, name, country))
    # 船舶
    for code, name, imo, vtype, dwt, teu, flag in [
            ("V001", "洋海轮", "9074729", "container", 65000, 5000, "中国"),
            ("V002", "远洋轮", "9312345", "container", 42000, 3400, "中国"),
            ("V003", "短驳轮", "9445678", "container", 8000, 100, "巴拿马")]:
        D.execute("INSERT INTO vessels(code,name,imo,vtype,dwt,teu,flag) VALUES(?,?,?,?,?,?,?)",
                  (code, name, imo, vtype, dwt, teu, flag))
    # 航次
    D.execute("INSERT INTO voyages(no,vessel_id,pol_id,pod_id,etd,eta,status,created_by) VALUES(?,?,?,?,?,?,?,?)",
              ("VO20260101-001", 1, 1, 3, "2026-01-03", "2026-01-09", "planned", "admin"))
    D.execute("INSERT INTO voyages(no,vessel_id,pol_id,pod_id,etd,eta,atd,status,created_by) VALUES(?,?,?,?,?,?,?,?,?)",
              ("VO20260101-002", 2, 1, 4, "2026-01-05", "2026-02-02", "2026-01-05", "departed", "admin"))
    D.execute("INSERT INTO voyages(no,vessel_id,pol_id,pod_id,etd,eta,atd,ata,status,created_by) VALUES(?,?,?,?,?,?,?,?,?,?)",
              ("VO20260101-003", 3, 2, 3, "2026-01-08", "2026-01-12", "2026-01-08", "2026-01-12", "arrived", "admin"))
    # 客户/伙伴
    D.execute("INSERT INTO partners(code,name,ptype,contact,phone,credit_limit_cents) VALUES('C0001','蓝湾食品','customer','陈经理','13911112222',500000000)")
    D.execute("INSERT INTO partners(code,name,ptype,contact,phone,credit_limit_cents) VALUES('C0002','华东货运','agent','刘经理','13933334444',200000000)")
    D.execute("INSERT INTO partners(code,name,ptype,contact,phone) VALUES('S0001','联洋船代','supplier','吴经理','13955556666')")
    # 订舱
    D.execute("INSERT INTO bookings(no,voyage_id,shipper_id,consignee,cargo_desc,boxes,ctype,status,created_by) VALUES(?,?,?,?,?,?,?,?,?)",
              ("BK20260101-001", 1, 1, "新加坡果商", "冷柜火龙果", 2, "40RF", "booked", "admin"))
    D.execute("INSERT INTO bookings(no,voyage_id,shipper_id,consignee,cargo_desc,boxes,ctype,status,created_by) VALUES(?,?,?,?,?,?,?,?,?)",
              ("BK20260101-002", 2, 1, "鹿特丹贸易行", "陶瓷餐具", 4, "40HQ", "loaded", "admin"))
    # 超载演示：短驳轮 teu=100，本订舱 60×40HQ=120 TEU → voyage_overload 风险
    D.execute("INSERT INTO bookings(no,voyage_id,shipper_id,consignee,cargo_desc,boxes,ctype,status,created_by) VALUES(?,?,?,?,?,?,?,?,?)",
              ("BK20260101-003", 3, 2, "新加坡五金行", "五金件", 60, "40HQ", "delivered", "admin"))
    # 集装箱（箱号通过 ISO 6346 校验位函数生成）
    def cno(base10):
        return base10 + str(K.container_check_digit(base10 + "0"))
    D.execute("INSERT INTO containers(container_no,ctype,seal_no,voyage_id,booking_id,status) VALUES(?,?,?,?,?,?)",
              (cno("TEMU305438"), "40RF", "SL0001", 1, 1, "full"))
    D.execute("INSERT INTO containers(container_no,ctype,seal_no,voyage_id,booking_id,status) VALUES(?,?,?,?,?,?)",
              (cno("TEMU305439"), "40RF", "SL0002", 1, 1, "empty"))
    D.execute("INSERT INTO containers(container_no,ctype,seal_no,voyage_id,booking_id,status) VALUES(?,?,?,?,?,?)",
              (cno("OOLU123456"), "40HQ", "SL0003", 2, 2, "in_transit"))
    # 滞箱演示：卸货 20 天前未归还 → demurrage_over 风险
    D.execute("INSERT INTO containers(container_no,ctype,seal_no,voyage_id,booking_id,status,unloaded_at) VALUES(?,?,?,?,?,?,?)",
              (cno("MSKU765432"), "40GP", "SL0004", 3, 3, "unloaded", "2026-10-03"))
    # 提单
    D.execute("INSERT INTO bls(no,booking_id,shipper,consignee,notify_party,cargo_desc,boxes,status,issued_at) VALUES(?,?,?,?,?,?,?,?,?)",
              ("BL20260101-001", 2, "蓝湾食品", "鹿特丹贸易行", "鹿特丹海关", "陶瓷餐具", 4, "issued", "2026-01-04"))
    D.execute("INSERT INTO bls(no,booking_id,shipper,consignee,notify_party,cargo_desc,boxes,status) VALUES(?,?,?,?,?,?,?,?)",
              ("BL20260101-002", 1, "蓝湾食品", "新加坡果商", "新加坡海关", "冷柜火龙果", 2, "draft"))
    # 运价
    D.execute("INSERT INTO rates(pol_id,pod_id,ctype,base_cents,surcharge_cents,valid_from,valid_to,note) VALUES(?,?,?,?,?,?,?,?)",
              (1, 3, "40RF", 2000000, 350000, "2026-01-01", "2026-12-31", "上海-新加坡 冷柜"))
    D.execute("INSERT INTO rates(pol_id,pod_id,ctype,base_cents,surcharge_cents,valid_from,valid_to,note) VALUES(?,?,?,?,?,?,?,?)",
              (1, 4, "40HQ", 3500000, 500000, "2026-01-01", "2026-12-31", "上海-鹿特丹 高柜"))
    D.execute("INSERT INTO rates(pol_id,pod_id,ctype,base_cents,surcharge_cents,valid_from,valid_to,note) VALUES(?,?,?,?,?,?,?,?)",
              (2, 3, "20GP", 900000, 100000, "2026-01-01", "2026-06-30", "宁波-新加坡（已到期）"))
    # 应收应付
    D.execute("INSERT INTO bills(no,btype,partner_id,amount_cents,settled_cents,due_date,ref) VALUES(?,?,?,?,?,?,?)",
              ("AR20260101-001", "receivable", 1, 4700000, 0, "2026-09-08", "运费 BK20260101-002"))  # 逾期
    D.execute("INSERT INTO bills(no,btype,partner_id,amount_cents,settled_cents,due_date,ref) VALUES(?,?,?,?,?,?,?)",
              ("AR20260110-002", "receivable", 1, 2350000, 0, "2026-11-30", "运费 BK20260101-001"))
    D.execute("INSERT INTO bills(no,btype,partner_id,amount_cents,settled_cents,due_date,ref) VALUES(?,?,?,?,?,?,?)",
              ("AP20260112-001", "payable", 3, 678000, 0, "2026-11-15", "港口使费 VO20260101-001"))
    D.execute("UPDATE partners SET receivable_cents=7050000, payable_cents=678000 WHERE id IN (1,3)")
    # 结算流水
    D.execute("INSERT INTO flows(no,ftype,category,amount_cents,counter_party,partner_id,summary,created_by) VALUES(?,?,?,?,?,?,?,?)",
              ("SR20260101-001", "income", "运费", 2350000, "bank", 1, "预收 BK20260101-001 部分运费", "admin"))
    D.get_db().commit()
    print("seed done")

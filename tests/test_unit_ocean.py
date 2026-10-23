# -*- coding: utf-8 -*-
"""飞洋内核单测：纯函数 31 例"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
import ocean as K


def test_money_to_cents():
    assert K.money_to_cents("12.345") == 1235
    assert K.money_to_cents(0.1) == 10
    assert K.money_to_cents(-5) == -500


def test_line_amount():
    assert K.line_amount_cents(3, 999) == 2997
    assert K.line_amount_cents(2.5, 100) == 250


def test_container_known_valid():
    assert K.container_no_valid("CSQU3054383")


def test_container_known_invalid():
    assert not K.container_no_valid("CSQU3054380")
    assert not K.container_no_valid("CSQU305438")  # 长度
    assert not K.container_no_valid("123U3054383")  # 前缀须字母


def test_check_digit_deterministic():
    assert K.container_check_digit("TEMU3054380") == 8
    assert K.container_check_digit("OOLU1234560") == 7
    assert K.container_check_digit("BAD") is None


def test_teu_of():
    assert K.teu_of("20GP") == 1.0
    assert K.teu_of("40HQ") == 2.0
    assert K.teu_of("45HC") == 2.0
    assert K.teu_of("20RF") == 1.0


def test_boxes_teu():
    assert K.boxes_teu("40RF", 3) == 6.0
    assert K.boxes_teu("20GP", 5) == 5.0


def test_voyage_load_check():
    over, usage = K.voyage_load_check(120, 100)
    assert over and abs(usage - 1.2) < 1e-9
    over, usage = K.voyage_load_check(80, 100)
    assert not over and abs(usage - 0.8) < 1e-9
    over, _ = K.voyage_load_check(10, 0)
    assert not over


def test_demurrage_days_free():
    # 占用 10 天、免箱 4 → 6 天滞箱
    assert K.demurrage_days("2026-01-01", "2026-01-11", 4) == 6
    assert K.demurrage_days("2026-01-01", "2026-01-05", 4) == 0
    assert K.demurrage_days(None, "2026-01-11", 4) == 0
    assert K.demurrage_days("bad-date", None, 4) == 0


def test_demurrage_fee_tiers():
    # 6 天：前 4 天×1 + 后 2 天×2 = 8×rate
    assert K.demurrage_fee(6, 100) == 4 * 100 + 2 * 200
    assert K.demurrage_fee(0, 100) == 0
    assert K.demurrage_fee(10, 100) == 4 * 100 + 4 * 200 + 2 * 400


def test_freight_quote():
    # (2000000 + 350000) × 2 × 2 = 9400000
    assert K.freight_quote(2000000, 350000, "40RF", 2) == 9400000
    assert K.freight_quote(1000000, 0, "20GP", 3) == 3000000


def test_rate_valid():
    assert K.rate_valid("2026-06-15", "2026-01-01", "2026-12-31")
    assert not K.rate_valid("2027-01-01", "2026-01-01", "2026-12-31")
    assert not K.rate_valid("2026-06-15", None, None)
    assert K.rate_days_to_expire("2026-06-15", "2026-06-20") == 5


def test_voyage_trans():
    assert K.can_transition(K.VOYAGE_TRANS, "planned", "departed")
    assert K.can_transition(K.VOYAGE_TRANS, "planned", "cancelled")
    assert K.can_transition(K.VOYAGE_TRANS, "departed", "arrived")
    assert K.can_transition(K.VOYAGE_TRANS, "arrived", "closed")
    assert not K.can_transition(K.VOYAGE_TRANS, "planned", "closed")
    assert not K.can_transition(K.VOYAGE_TRANS, "closed", "departed")


def test_booking_trans():
    assert K.can_transition(K.BOOKING_TRANS, "booked", "loaded")
    assert K.can_transition(K.BOOKING_TRANS, "loaded", "shipped")
    assert K.can_transition(K.BOOKING_TRANS, "shipped", "delivered")
    assert not K.can_transition(K.BOOKING_TRANS, "delivered", "loaded")
    assert not K.can_transition(K.BOOKING_TRANS, "shipped", "cancelled")


def test_container_trans():
    assert K.can_transition(K.CONTAINER_TRANS, "empty", "full")
    assert K.can_transition(K.CONTAINER_TRANS, "full", "returned")
    assert K.can_transition(K.CONTAINER_TRANS, "in_transit", "unloaded")
    assert not K.can_transition(K.CONTAINER_TRANS, "unloaded", "full")
    assert not K.can_transition(K.CONTAINER_TRANS, "returned", "empty")


def test_bl_trans():
    assert K.can_transition(K.BL_TRANS, "draft", "issued")
    assert K.can_transition(K.BL_TRANS, "issued", "telex_released")
    assert not K.can_transition(K.BL_TRANS, "draft", "surrendered")
    assert not K.can_transition(K.BL_TRANS, "surrendered", "issued")


def test_days_overdue():
    assert K.days_overdue("2026-01-01", __import__("datetime").date(2026, 2, 15)) == 45
    assert K.days_overdue("2099-01-01") == 0
    assert K.days_overdue(None) == 0


def test_aging_bucket():
    assert K.aging_bucket(0) == "0-30"
    assert K.aging_bucket(45) == "31-60"
    assert K.aging_bucket(200) == "180+"
    assert K.aging_bucket(-5) == "0-30"


def test_bill_settle():
    row = {"amount_cents": 1000, "settled_cents": 400}
    assert K.bill_remaining(row) == 600
    assert K.settle_amount(row, 800) == 600
    assert K.settle_amount(row, 100) == 100
    assert K.settle_amount(row, 0) == 0


def test_has_perm_wildcard():
    assert K.has_perm("*", "sea.anything")


def test_has_perm_wildcard_entity():
    assert K.has_perm(["sea.voyages.*"], "sea.voyages.write")
    assert K.has_perm(["sea.voyages.*"], "sea.voyages.read")
    assert not K.has_perm(["sea.voyages.*"], "sea.bills.write")


def test_has_perm_write_implies_read():
    assert K.has_perm(["sea.bills.write"], "sea.bills.read")
    assert not K.has_perm(["sea.bills.read"], "sea.bills.write")


def test_role_perms_defined():
    for role in ("admin", "ops", "finance", "doc", "agent", "reader"):
        assert role in K.ROLE_PERMS


def test_voyage_stats():
    rows = [{"status": "departed", "loaded_teu": 4}, {"status": "planned", "loaded_teu": 2}]
    st = K.voyage_stats(rows)
    assert st["voyages"] == 2 and st["sailed"] == 1 and st["loaded_teu"] == 6.0

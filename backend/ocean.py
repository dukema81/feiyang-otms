# -*- coding: utf-8 -*-
"""飞洋 OTMS 海运内核（纯函数，无 IO 无 DB，可独立单测）"""
from decimal import Decimal, ROUND_HALF_UP
from datetime import date, datetime

# ---------------- 金额 ----------------
def money_to_cents(yuan) -> int:
    return int((Decimal(str(yuan)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

def line_amount_cents(qty, price_cents) -> int:
    return int((Decimal(str(qty)) * Decimal(str(price_cents))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

# ---------------- ISO 6346 箱号 ----------------
# ISO 6346 字母取值：A 起从 10 顺序 +1，跳过 11 的倍数（11/22/33）
_LETTER_VALUES = {}
_v = 10
for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    if _v % 11 == 0:
        _v += 1
    _LETTER_VALUES[ch] = _v
    _v += 1

def container_check_digit(code11):
    """ISO 6346：前 10 位加权(2^0..2^9)求和 mod 11，10 记 0。code11 为 11 位完整箱号"""
    s = (code11 or "").strip().upper()
    if len(s) != 11:
        return None
    total = 0
    for i, ch in enumerate(s[:10]):
        if ch.isdigit():
            val = int(ch)
        elif ch in _LETTER_VALUES:
            val = _LETTER_VALUES[ch]
        else:
            return None
        total += val * (2 ** i)
    chk = total % 11
    return 0 if chk == 10 else chk

def container_no_valid(code11) -> bool:
    s = (code11 or "").strip().upper()
    if len(s) != 11 or not s[:4].isalpha() or not s[4:10].isdigit() or not s[10].isdigit():
        return False
    return container_check_digit(s) == int(s[10])

# ---------------- TEU ----------------
def teu_of(ctype) -> float:
    """20ft=1.0；40/45ft=2.0；未知按 1.0"""
    s = (ctype or "").upper()
    return 2.0 if s.startswith(("40", "45")) else 1.0

def boxes_teu(ctype, boxes) -> float:
    return teu_of(ctype) * int(boxes or 0)

def voyage_load_check(loaded_teu, vessel_teu) -> tuple:
    """返回 (over: bool, usage: float)"""
    vt = float(vessel_teu or 0)
    lt = float(loaded_teu or 0)
    return (vt > 0 and lt > vt), (lt / vt if vt > 0 else 0.0)

# ---------------- 滞箱 ----------------
DEMURRAGE_TIERS = [(1, 4, 1), (5, 8, 2), (9, 999999, 4)]

def demurrage_days(unloaded_date, returned_date, free_days):
    """滞箱天数 = max(0, 实际占用天数 - 免箱期)；未返回按 today 计"""
    if not unloaded_date:
        return 0
    try:
        u = datetime.strptime(str(unloaded_date)[:10], "%Y-%m-%d").date()
    except Exception:
        return 0
    if returned_date:
        try:
            r = datetime.strptime(str(returned_date)[:10], "%Y-%m-%d").date()
        except Exception:
            r = date.today()
    else:
        r = date.today()
    occupied = (r - u).days
    return max(0, occupied - int(free_days or 0))

def demurrage_fee(days, rate_cents_per_day, tiers=None):
    """阶梯滞箱费：每箱费用按天分档乘系数。tiers 默认 DEMURRAGE_TIERS"""
    ts = tiers or DEMURRAGE_TIERS
    total = 0
    for lo, hi, mult in ts:
        if days >= lo:
            covered = min(days, hi) - lo + 1
            total += covered * rate_cents_per_day * mult
    return total

# ---------------- 运价 ----------------
def freight_quote(base_cents, surcharge_cents, ctype, boxes) -> int:
    """报价 = (基础 + 附加) × TEU 系数 × 箱数"""
    unit = int(base_cents or 0) + int(surcharge_cents or 0)
    return int((Decimal(unit) * Decimal(str(teu_of(ctype))) * Decimal(int(boxes or 0))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

def rate_valid(today, valid_from, valid_to) -> bool:
    if not valid_from or not valid_to:
        return False
    try:
        t = datetime.strptime(str(today)[:10], "%Y-%m-%d").date()
        f = datetime.strptime(str(valid_from)[:10], "%Y-%m-%d").date()
        v = datetime.strptime(str(valid_to)[:10], "%Y-%m-%d").date()
    except Exception:
        return False
    return f <= t <= v

def rate_days_to_expire(today, valid_to) -> int:
    try:
        t = datetime.strptime(str(today)[:10], "%Y-%m-%d").date()
        v = datetime.strptime(str(valid_to)[:10], "%Y-%m-%d").date()
    except Exception:
        return 9999
    return (v - t).days

# ---------------- 状态机 ----------------
VOYAGE_TRANS = {
    "planned": {"departed", "cancelled"},
    "departed": {"arrived"},
    "arrived": {"closed"},
    "closed": set(),
    "cancelled": set(),
}

BOOKING_TRANS = {
    "booked": {"loaded", "cancelled"},
    "loaded": {"shipped", "cancelled"},
    "shipped": {"delivered"},
    "delivered": set(),
    "cancelled": set(),
}

CONTAINER_TRANS = {
    "empty": {"full"},
    "full": {"in_transit", "returned"},
    "in_transit": {"unloaded"},
    "unloaded": {"returned"},
    "returned": set(),
}

BL_TRANS = {
    "draft": {"issued"},
    "issued": {"surrendered", "telex_released"},
    "surrendered": set(),
    "telex_released": set(),
}

VESSEL_STATUS = ("active", "laid_up", "retired")
CTYPE_SET = ("20GP", "40GP", "40HQ", "20RF", "40RF", "45HC")
VTYPE_SET = ("container", "bulk", "tanker", "roro")

def can_transition(trans: dict, cur: str, to: str) -> bool:
    return to in trans.get(cur, set())

# ---------------- 账龄 / 结算 ----------------
AGING_BUCKETS = [(0, 30, "0-30"), (31, 60, "31-60"), (61, 90, "61-90"), (91, 180, "91-180"), (181, 99999, "180+")]

def aging_bucket(days_overdue) -> str:
    d = max(0, int(days_overdue or 0))
    for lo, hi, name in AGING_BUCKETS:
        if lo <= d <= hi:
            return name
    return "180+"

def days_overdue(due_date, today=None) -> int:
    if not due_date:
        return 0
    today = today or date.today()
    try:
        due = datetime.strptime(due_date[:10], "%Y-%m-%d").date()
    except Exception:
        return 0
    return max(0, (today - due).days)

def bill_remaining(bill_row) -> int:
    return int(bill_row["amount_cents"] or 0) - int(bill_row["settled_cents"] or 0)

def settle_amount(bill_row, pay_cents) -> int:
    return max(0, min(int(pay_cents or 0), bill_remaining(bill_row)))

# ---------------- 权限 ----------------
ROLE_PERMS = {
    "admin": "*",
    "ops": ["sea.voyages.*", "sea.bookings.*", "sea.containers.*", "sea.vessels.*", "sea.ports.read", "sea.rates.read", "sea.reports.read", "sea.risk.read"],
    "finance": ["sea.bills.*", "sea.partners.*", "sea.rates.read", "sea.reports.read", "sea.voyages.read", "sea.risk.read"],
    "doc": ["sea.bls.*", "sea.bookings.read", "sea.containers.read", "sea.voyages.read", "sea.reports.read"],
    "agent": ["sea.bookings.create", "sea.bookings.read", "sea.bls.read", "sea.voyages.read", "sea.rates.read", "sea.track.read"],
    "reader": ["sea.vessels.read", "sea.voyages.read", "sea.bookings.read", "sea.containers.read", "sea.bls.read", "sea.rates.read", "sea.bills.read", "sea.reports.read"],
}

def has_perm(perms, perm: str) -> bool:
    if perms == "*":
        return True
    if isinstance(perms, (list, tuple)):
        parts = [str(p) for p in perms if p]
    else:
        parts = [p for p in (perms or "").split(",") if p]
    for p in parts:
        if p == perm:
            return True
        if p.endswith(".*") and perm.startswith(p[:-1]):
            return True
        if perm.endswith(".read") and (perm[:-5] + ".*") in parts:
            return True
        if perm.endswith(".read") and (perm[:-5] + ".write") in parts:
            return True
    return False

# ---------------- 统计 ----------------
def voyage_stats(voyage_rows):
    total = len(voyage_rows)
    departed = sum(1 for r in voyage_rows if r.get("status") in ("departed", "arrived", "closed"))
    teu = sum(float(r.get("loaded_teu") or 0) for r in voyage_rows)
    return {"voyages": total, "sailed": departed, "loaded_teu": teu}

def over_credit(receivable_cents, credit_limit_cents) -> bool:
    return credit_limit_cents > 0 and receivable_cents > credit_limit_cents

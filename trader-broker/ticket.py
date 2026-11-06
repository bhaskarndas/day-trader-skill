#!/usr/bin/env python3
"""Order tickets, your yes and PAPER fills for trader-broker (NSE). Standard library only.

This NSE version has no live broker. It never talks to a broker and never
places a real order. Every approved order is filled on PAPER, in your
trader/portfolio.json, with the Indian charges taken off your cash, so you
can run the whole pack on real prices without risking a rupee.

  show      renders each proposed order as a plain-English ticket. A bracket
            order shows its stop-loss, take-profit and the max loss at the
            stop (charges included). An order is READY only if trader-risk
            passed THIS exact order today (matched by fingerprint) and nobody
            has decided on it yet.
  approve   records your explicit yes for ONE order, with your reply word for
            word, and fills it on paper: a market order at --price, else the
            fresh price in trader/prices.json, else the plan's entry; a limit
            order at its limit. It refuses "yes to all", "sure", "ok", a yes
            that names a different stock or amount, and any order that is not
            READY.
  decline   records a no.
  fill      records any other paper fill (the stop or the target of a
            bracket when trader-alerts rings it, or a manual exit).
  flatten   builds a sell ticket that closes a symbol's open position by
            flat_by. It still goes through trader-risk and your yes.
  log       prints today's decisions and paper fills.

    python3 ticket.py show                    # every order, READY or not
    python3 ticket.py show --index 1 --json   # one ticket as JSON
    python3 ticket.py approve --index 1 --reply "yes"
    python3 ticket.py approve --index 1 --reply "yes" --price 1311.40
    python3 ticket.py fill --symbol RELIANCE --side sell --qty 57 --price 1318.50
    python3 ticket.py flatten --symbol RELIANCE
    python3 ticket.py log

A paper fill is not a real fill: a real market order can fill worse, and a
stop can fill past its price in a fast market or a gap.

Charges on every paper fill (intraday, NSE, the defaults; "charges" in
trader/config.json overrides them): brokerage 0.03 % of the order, at most
₹20; STT 0.025 % of a sell; exchange 0.00297 %; SEBI ₹10 a crore; stamp duty
0.003 % of a buy; GST 18 % of brokerage + exchange + SEBI.

Everything is written to trader/state/broker.json (append only). Dates are
IST dates; --now "2026-11-05 10:00" pins the clock.
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import sys

# the order fields a fingerprint covers (same tuple in trader-risk/check.py)
ORDER_FIELDS = ("symbol", "exchange", "side", "qty", "notional", "type", "time_in_force", "product",
                "limit_price", "stop_price", "client_order_id", "order_class", "take_profit_limit_price",
                "stop_loss_stop_price", "stop_loss_limit_price", "advanced_instructions")
STRING_FIELDS = ("qty", "notional", "limit_price", "stop_price", "take_profit_limit_price",
                 "stop_loss_stop_price", "stop_loss_limit_price")
TIF_WORDS = {"day": "good for today", "ioc": "immediate or cancel"}
PRODUCT_WORDS = {"MIS": "intraday (MIS)", "CNC": "delivery (CNC)"}
CHARGES = {  # intraday equity on NSE, same as trader-budget and trader-risk (read 2026-11-06)
    "brokerage_pct": 0.03, "brokerage_max_per_order": 20.0, "stt_sell_pct": 0.025, "exchange_pct": 0.00297,
    "sebi_per_crore": 10.0, "stamp_buy_pct": 0.003, "gst_pct": 18.0,
}
FRESH_MINUTES = 15
YES_WORDS = ("yes", "y")
BATCH_WORDS = {"all", "every", "everything", "rest", "remaining", "them", "both", "batch", "each"}
DOUBT_WORDS = {"no", "not", "dont", "don't", "wait", "cancel", "stop", "but", "maybe", "later",
               "hold", "unless", "if"}


class TicketError(Exception):
    pass


# ---------------------------------------------------------------- time (IST, no tz files)

IST_OFFSET = datetime.timedelta(hours=5, minutes=30)   # India has no daylight saving


def ist_offset(utc=None):
    """Hours from UTC for India: always +5.5 (IST, no daylight saving)."""
    return 5.5


def to_ist(utc):
    return utc.replace(tzinfo=None) + IST_OFFSET


def ist_to_utc(local):
    return local.replace(tzinfo=None) - IST_OFFSET


def parse_now(text):
    """ISO time -> naive UTC. A time without an offset is taken as India time (IST)."""
    if not text:
        return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0, tzinfo=None)
    t = text.strip().replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(t)
    except ValueError:
        raise TicketError("--now wants a time like \"2026-11-05 10:00\" (IST) or ...Z (UTC)")
    if dt.tzinfo is None:
        return ist_to_utc(dt)
    return (dt - dt.utcoffset()).replace(tzinfo=None)


def ist_iso(now_utc):
    """naive UTC -> "2026-11-05T10:00:00+05:30" (IST wall clock with its offset)."""
    return "%s+05:30" % to_ist(now_utc).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------- files

def read_json(path, what, required=True):
    if not path or not os.path.exists(path):
        if required:
            raise TicketError("no %s at %s" % (what, path))
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as e:
        raise TicketError("%s is not valid JSON: %s" % (path, e))


def write_json(path, data):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def rec_day(rec):
    """The trading day a decision belongs to: its "date" (the day it was made under), else the day of "at"."""
    return str(rec.get("date") or str(rec.get("at", ""))[:10])


# ---------------------------------------------------------------- the order

def fingerprint(order):
    """Same function as trader-risk/check.py: identifies the exact order."""
    core = {k: order[k] for k in ORDER_FIELDS if k in order and order[k] is not None}
    blob = json.dumps(core, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _str_num(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        f = float(v)
        return str(int(f)) if f == int(f) else repr(f)
    return str(v)


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def tool_input(order):
    """The order's own fields, numbers as strings ("why" and "plan" are notes, not order fields)."""
    out = {}
    for k in ORDER_FIELDS:
        if k in order and order[k] is not None:
            out[k] = _str_num(order[k]) if k in STRING_FIELDS else order[k]
    return out


def charge_rates(cfg):
    rates = dict(CHARGES)
    for k, v in ((cfg or {}).get("charges") or {}).items():
        if k in rates and _f(v) is not None and _f(v) >= 0:
            rates[k] = _f(v)
    return rates


def leg_charges(side, value, rates):
    """Charges on ONE fill (a buy or a sell), in rupees: a dict of the parts and the total."""
    v = max(float(value), 0.0)
    out = {"brokerage": min(rates["brokerage_max_per_order"], v * rates["brokerage_pct"] / 100.0) if v else 0.0,
           "stt": v * rates["stt_sell_pct"] / 100.0 if side == "sell" else 0.0,
           "exchange": v * rates["exchange_pct"] / 100.0, "sebi": v * rates["sebi_per_crore"] / 1e7,
           "stamp": v * rates["stamp_buy_pct"] / 100.0 if side == "buy" else 0.0}
    out["gst"] = (out["brokerage"] + out["exchange"] + out["sebi"]) * rates["gst_pct"] / 100.0
    out = {k: round(x, 2) for k, x in out.items()}
    out["total"] = round(sum(out.values()), 2)
    return out


def group_in(digits):
    """Indian digit grouping: 1234567 -> 12,34,567 (lakh and crore)."""
    neg = digits.startswith("-")
    s = digits.lstrip("-")
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    return ("-" if neg else "") + s


def inr(x, paise=None):
    """1234567.5 -> "₹12,34,567.50". paise=None drops ".00" on whole rupees."""
    v = round(float(x) + (1e-9 if float(x) >= 0 else -1e-9), 2)
    whole, frac = ("%.2f" % abs(v)).split(".")
    s = group_in(whole)
    if paise or (paise is None and frac != "00"):
        s += "." + frac
    return ("-" if v < 0 else "") + "₹" + s


def _money(v):
    return inr(v)


def _p(v):
    return "%.2f" % float(v)


def is_bracket(order):
    oc = str(order.get("order_class") or "").lower()
    legs = order.get("take_profit_limit_price") is not None or order.get("stop_loss_stop_price") is not None
    return oc == "bracket" or (not oc and legs)


def max_loss(order):
    """(rupees, stop) lost if the stop fills exactly at the stop, charges included when the plan
    carries them (trader-budget writes max_loss with charges), or (None, stop)."""
    stop = _f(order.get("stop_loss_stop_price")) or _f((order.get("plan") or {}).get("stop"))
    q = _f(order.get("qty"))
    if not stop or not q:
        return None, stop
    plan = order.get("plan") or {}
    if str(order.get("type", "market")) == "limit" and _f(order.get("limit_price")):
        entry = _f(order["limit_price"])
    elif _f(plan.get("max_loss")) is not None:
        return round(_f(plan["max_loss"]), 2), stop
    else:
        entry = _f(plan.get("entry"))
    if not entry:
        return None, stop
    risk = abs(entry - stop)
    return round(q * int(round(risk * 100)) / 100.0, 2), stop


def plain_parts(order):
    """The ticket in plain words, one part per line."""
    side = str(order.get("side", "")).upper()
    sym = order.get("symbol", "?")
    typ = str(order.get("type", "market"))
    tif = TIF_WORDS.get(str(order.get("time_in_force", "day")), order.get("time_in_force"))
    if is_bracket(order):
        how = "limit %s" % _p(order["limit_price"]) if typ == "limit" and order.get("limit_price") else typ
        prod = PRODUCT_WORDS.get(str(order.get("product") or "MIS").upper(), order.get("product"))
        parts = ["%s %s %s on NSE, %s, %s, %s" % (side, _str_num(order.get("qty")), sym, how, prod, tif)]
        if order.get("stop_loss_stop_price") is not None:
            leg = "stop-loss %s" % _p(order["stop_loss_stop_price"])
            if order.get("stop_loss_limit_price") is not None:
                leg += " (limit %s)" % _p(order["stop_loss_limit_price"])
            parts.append(leg)
        if order.get("take_profit_limit_price") is not None:
            parts.append("take-profit %s" % _p(order["take_profit_limit_price"]))
        loss, stop = max_loss(order)
        if loss is not None:
            parts.append("max loss about %s if the stop fills at %s (it can fill worse in a fast market)"
                         % (_money(loss), _p(stop)))
        return parts
    if order.get("notional") is not None:
        what = "%s of %s" % (_money(order["notional"]), sym)
    else:
        q = _str_num(order.get("qty"))
        what = "%s share%s of %s" % (q, "" if q == "1" else "s", sym)
    if typ == "limit":
        how = "limit order at %s" % _money(order.get("limit_price"))
    elif typ == "stop":
        how = "stop order at %s" % _money(order.get("stop_price"))
    elif typ == "stop_limit":
        how = "stop %s, limit %s" % (_money(order.get("stop_price")), _money(order.get("limit_price")))
    else:
        how = "%s order" % typ.replace("_", " ")
    prod = PRODUCT_WORDS.get(str(order.get("product") or "MIS").upper(), order.get("product"))
    return ["%s %s on NSE, %s, %s, %s" % (side, what, how, prod, tif)]


def plain(order):
    """BUY 57 RELIANCE on NSE, market, intraday (MIS), good for today / stop-loss 1304.10 /
    take-profit 1318.50 / max loss about ₹483.82 ..."""
    return " / ".join(plain_parts(order))


def amount_numbers(order):
    nums = []
    for k in ("notional", "qty", "limit_price", "stop_loss_stop_price", "take_profit_limit_price",
              "stop_loss_limit_price"):
        if order.get(k) is not None:
            v = _f(order[k])
            if v is not None:
                nums.append(v)
    loss, _ = max_loss(order)
    if loss is not None:
        nums.append(loss)
    return nums


def parse_yes(reply, order, batch_symbols=()):
    """Is this reply an explicit yes for THIS one order? Returns (ok, why)."""
    raw = (reply or "").strip()
    if not raw:
        return False, "the reply is empty"
    if "?" in raw:
        return False, "the reply is a question, not a yes"
    words = re.findall(r"[a-z']+", raw.lower())
    if not words or words[0] not in YES_WORDS:
        return False, "only a reply that starts with \"yes\" counts (not ok, sure, go, do it)"
    if BATCH_WORDS & set(words):
        return False, "a yes covers one order at a time, not a batch"
    if DOUBT_WORDS & set(words[1:]):
        return False, "the reply has a condition or a doubt in it; ask again"
    sym = str(order.get("symbol", "")).upper()
    tokens = set(re.findall(r"[A-Z][A-Z&.\-]{0,19}", raw.upper()))
    others = {s.upper() for s in batch_symbols} - {sym}
    named = tokens & others
    if named:
        return False, "the reply names %s, but this order is for %s" % (", ".join(sorted(named)), sym)
    nums = [float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", raw)]
    if nums:
        want = amount_numbers(order)
        if not any(abs(n - w) < 0.005 for n in nums for w in want):
            return False, "the reply says %s, but this order is %s" % (
                ", ".join(_str_num(n) for n in nums), plain(order))
    return True, "explicit yes for %s" % plain(order)


# ---------------------------------------------------------------- state

def load_state(path):
    return read_json(path, "broker state", required=False) or {"orders": []}


def latest(state, fp, today):
    """The latest decision recorded today for this fingerprint, or None."""
    found = None
    for rec in state.get("orders", []):
        if rec.get("fingerprint") == fp and rec_day(rec) == today:
            found = rec
    return found


def risk_verdict(risk, fp, today):
    if not risk:
        return None, "trader-risk has not checked these orders (run check.py)"
    if risk.get("date") != today:
        return None, "the risk check is from %s, not today; run check.py again" % risk.get("date")
    for r in risk.get("results", []):
        if r.get("fingerprint") == fp:
            return r, None
    return None, "this exact order was not in the last risk check (it changed or is new); run check.py again"


def status_of(order, risk, state, today):
    """(ready, label, risk_result)"""
    fp = fingerprint(order)
    rv, why = risk_verdict(risk, fp, today)
    if rv is None:
        return False, "NOT READY: " + why, None
    if rv.get("verdict") != "PASS":
        return False, "BLOCKED by trader-risk: " + "; ".join(rv.get("reasons", [])), rv
    rec = latest(state, fp, today)
    if rec:
        st = rec.get("status")
        if st == "approved":
            return False, "APPROVED by you at %s, paper fill not recorded yet" % rec.get("at"), rv
        return False, "DONE: %s at %s" % (st, rec.get("at")), rv
    return True, "READY: trader-risk PASS, waiting for your yes", rv


def kind_of(order, rv):
    """entry or exit, as trader-risk saw it (older checks: a buy is an entry)."""
    if rv and rv.get("kind"):
        return rv["kind"]
    return "entry" if str(order.get("side", "")).lower() == "buy" else "exit"


# ---------------------------------------------------------------- rendering

def render(order, idx, total, cfg, risk, state, today):
    ready, label, rv = status_of(order, risk, state, today)
    lines = ["ORDER %d of %d, PAPER account (simulated fills, no broker)" % (idx, total)]
    for part in plain_parts(order):
        lines.append("  " + part)
    if order.get("why"):
        lines.append("  why: " + order["why"])
    lines.append("  " + label)
    for w in (rv or {}).get("warnings", []):
        lines.append("  note: " + w)
    if is_bracket(order):
        lines.append("  On paper the entry fills now; the stop-loss and the take-profit are watched by")
        lines.append("  trader-alerts, and whichever rings first is recorded with ticket.py fill.")
    if ready:
        lines.append("  Reply \"yes\" to fill this one order on paper, or \"no\" to skip it.")
    return "\n".join(lines), ready


def ticket_json(order, idx, cfg, risk, state, today):
    ready, label, rv = status_of(order, risk, state, today)
    loss, stop = max_loss(order)
    return {"index": idx, "ready": ready, "status": label, "plain": plain(order),
            "fingerprint": fingerprint(order), "paper": True, "broker": "paper",
            "order": tool_input(order), "why": order.get("why", ""),
            "bracket": is_bracket(order), "max_loss": loss, "stop": stop}


# ---------------------------------------------------------------- fills -> portfolio

def apply_fill(portfolio_path, cfg, symbol, side, qty, price, date):
    """Record a paper fill in trader/portfolio.json: cash and shares, with a
    cost-basis lot per buy (oldest lots are relieved first on a sell). The
    fill's charges come off the cash; a sell adds its net result to
    "realized_pnl" (proceeds minus cost basis minus the sell's charges; the
    buy's charges are already in the cost basis)."""
    pf = read_json(portfolio_path, "portfolio", required=False)
    if pf is None:
        budget = cfg.get("budget")
        if not budget:
            raise TicketError("no %s yet and no budget in the config to start it from" % portfolio_path)
        pf = {"cash": float(budget), "positions": []}
    symbol = symbol.upper()
    qty, price = float(qty), float(price)
    if qty <= 0 or price <= 0:
        raise TicketError("a fill needs a positive qty and price")
    cost = round(qty * price, 2)
    fees = leg_charges(side, cost, charge_rates(cfg))
    pos = None
    for p in pf.setdefault("positions", []):
        if str(p.get("ticker", "")).upper() == symbol:
            pos = p
    if side == "buy":
        if pos is None:
            pos = {"ticker": symbol, "shares": 0.0, "lots": []}
            pf["positions"].append(pos)
        lots = pos.setdefault("lots", [])
        lots.append({"id": "%s-%d" % (symbol, len(lots) + 1), "date": date, "shares": qty,
                     "cost": round(cost + fees["total"], 2)})
        pos["shares"] = round(float(pos.get("shares", 0)) + qty, 6)
        pf["cash"] = round(float(pf.get("cash", 0)) - cost - fees["total"], 2)
    else:
        if pos is None or float(pos.get("shares", 0)) + 1e-9 < qty:
            raise TicketError("cannot record selling %s %s: the portfolio holds %s"
                              % (_str_num(qty), symbol, pos.get("shares", 0) if pos else 0))
        left = qty
        basis = 0.0
        for lot in sorted(pos.get("lots", []), key=lambda l: l.get("date", "")):
            if left <= 1e-9:
                break
            take = min(left, float(lot["shares"]))
            per = float(lot["cost"]) / float(lot["shares"]) if float(lot["shares"]) else 0
            basis += per * take
            lot["cost"] = round(float(lot["cost"]) - per * take, 2)
            lot["shares"] = round(float(lot["shares"]) - take, 6)
            left -= take
        pos["lots"] = [l for l in pos.get("lots", []) if float(l["shares"]) > 1e-9]
        pos["shares"] = round(float(pos["shares"]) - qty, 6)
        if pos["shares"] <= 1e-9:
            pf["positions"].remove(pos)
        pf["cash"] = round(float(pf.get("cash", 0)) + cost - fees["total"], 2)
        pf["realized_pnl"] = round(float(pf.get("realized_pnl", 0)) + cost - fees["total"] - basis, 2)
    pf["charges_paid"] = round(float(pf.get("charges_paid", 0)) + fees["total"], 2)
    pf["last_fill"] = {"symbol": symbol, "side": side, "qty": qty, "price": price, "date": date,
                       "charges": fees}
    write_json(portfolio_path, pf)
    return pf


def log_fill(state_path, now, today, symbol, side, qty, price):
    """A paper fill in the log."""
    state = load_state(state_path)
    state.setdefault("orders", []).append({
        "at": ist_iso(now), "date": today, "status": "filled", "symbol": symbol.upper(), "side": side,
        "qty": _str_num(float(qty)), "price": float(price),
        "plain": "%s %s %s at %s" % (side.upper(), _str_num(float(qty)), symbol.upper(), _p(price))})
    write_json(state_path, state)


# ---------------------------------------------------------------- commands

def _clock(a):
    now = parse_now(getattr(a, "now", None))
    today = getattr(a, "today", None) or to_ist(now).date().isoformat()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", today):
        raise TicketError("--today wants a date like 2026-11-05")
    return now, today


def _load(a):
    doc = read_json(a.orders, "orders file (run trader-budget, or ticket.py flatten, first)")
    orders = doc.get("orders", doc) if isinstance(doc, dict) else doc
    if not isinstance(orders, list) or not orders:
        raise TicketError("no orders in %s" % a.orders)
    cfg = read_json(a.config, "config", required=False) or {}
    risk = read_json(a.risk, "risk check", required=False)
    state = load_state(a.state)
    now, today = _clock(a)
    return orders, cfg, risk, state, today, now


def _pick(orders, index):
    if index is None:
        raise TicketError("say which order: --index N")
    if not 1 <= index <= len(orders):
        raise TicketError("there is no order %d (there are %d)" % (index, len(orders)))
    return orders[index - 1]


def cmd_show(a):
    orders, cfg, risk, state, today, now = _load(a)
    picks = [(a.index, _pick(orders, a.index))] if a.index else list(enumerate(orders, 1))
    if a.json:
        out = [ticket_json(o, i, cfg, risk, state, today) for i, o in picks]
        print(json.dumps(out[0] if a.index else out, indent=2))
        return 0 if any(t["ready"] for t in out) else 1
    blocks, any_ready = [], False
    for i, o in picks:
        text, ready = render(o, i, len(orders), cfg, risk, state, today)
        blocks.append(text)
        any_ready = any_ready or ready
    print("\n\n".join(blocks))
    print("\nOne order at a time: a yes covers one ticket, never the batch. Education and tooling, "
          "not financial advice.")
    return 0 if any_ready else 1


def cmd_approve(a):
    orders, cfg, risk, state, today, now = _load(a)
    order = _pick(orders, a.index)
    ready, label, rv = status_of(order, risk, state, today)
    if not ready:
        raise TicketError("order %d is not ready: %s" % (a.index, label))
    ok, why = parse_yes(a.reply, order, [o.get("symbol", "") for o in orders])
    if not ok:
        print("Not recorded: %s. Ask the user again with the ticket for order %d." % (why, a.index))
        return 1
    price, how = paper_price(order, a, now)
    qty = _f(order.get("qty"))
    if not qty or qty <= 0:
        raise TicketError("order %d has no whole-share qty to fill" % a.index)
    loss, stop = max_loss(order)
    sym = str(order.get("symbol", "")).upper()
    base = {"date": today, "index": a.index, "fingerprint": fingerprint(order), "symbol": sym,
            "side": order.get("side"), "qty": order.get("qty"), "kind": kind_of(order, rv), "max_loss": loss,
            "stop": stop, "plain": plain(order), "paper": True, "broker": "paper"}
    state.setdefault("orders", []).append(dict(base, at=ist_iso(now), status="approved", reply=a.reply))
    placed = dict(base, at=ist_iso(now), status="placed", fill_price=price, fill_from=how)
    if is_bracket(order):
        placed["legs"] = {"stop_loss": _f(order.get("stop_loss_stop_price")),
                          "take_profit": _f(order.get("take_profit_limit_price"))}
    state["orders"].append(placed)
    write_json(a.state, state)
    pf = apply_fill(a.portfolio, cfg, sym, str(order.get("side")).lower(), qty, price, today)
    log_fill(a.state, now, today, sym, str(order.get("side")).lower(), qty, price)
    fees = pf["last_fill"]["charges"]
    print("Recorded your yes for order %d: %s." % (a.index, plain(order)))
    print("PAPER fill: %s %s %s at %s (%s). Charges %s. Cash now %s."
          % (str(order.get("side")).upper(), _str_num(qty), sym, _p(price), how, _money(fees["total"]),
             _money(pf["cash"])))
    if is_bracket(order):
        print("Watch the legs: trader-alerts (alerts.py add --from-plan) rings the stop-loss %s, the take-profit "
              "%s and the flat-by time. Record whichever happens with ticket.py fill --side sell."
              % (_p(order["stop_loss_stop_price"]), _p(order["take_profit_limit_price"])))
    print("A paper fill is not a real fill: a real order can fill worse.")
    return 0


def paper_price(order, a, now):
    """(price, where it came from) for a paper fill."""
    if getattr(a, "price", None) is not None:
        p = _f(a.price)
        if not p or p <= 0:
            raise TicketError("--price wants a positive price")
        return round(p, 2), "your --price"
    typ = str(order.get("type", "market")).lower()
    if typ in ("limit", "stop_limit") and _f(order.get("limit_price")):
        return round(_f(order["limit_price"]), 2), "the limit price"
    sym = str(order.get("symbol", "")).upper()
    doc = read_json(getattr(a, "prices", "trader/prices.json"), "prices", required=False) or {}
    p = _f((doc.get("prices") or {}).get(sym))
    det = ((doc.get("detail") or {}).get(sym) or {})
    when = det.get("time") or det.get("fetched") or doc.get("as_of")
    if p and when:
        try:
            t = datetime.datetime.fromisoformat(str(when).replace("Z", "+00:00"))
            t = (t - t.utcoffset()).replace(tzinfo=None) if t.tzinfo else t
            if -60 <= (now - t).total_seconds() <= FRESH_MINUTES * 60:
                return round(p, 2), "the latest price in trader/prices.json"
        except ValueError:
            pass
    pe = _f((order.get("plan") or {}).get("entry"))
    if pe:
        return round(pe, 2), "the plan's entry (no fresh price: pass --price for a truer fill)"
    raise TicketError("no price to fill %s on paper: pass --price, or fetch one (alerts.py quote %s --write)"
                      % (sym, sym))


def cmd_decline(a):
    orders, cfg, risk, state, today, now = _load(a)
    order = _pick(orders, a.index)
    rec = {"at": ist_iso(now), "date": today, "index": a.index, "fingerprint": fingerprint(order),
           "symbol": str(order.get("symbol", "")).upper(), "side": order.get("side"),
           "plain": plain(order), "status": "declined", "reply": a.reply or "no"}
    state.setdefault("orders", []).append(rec)
    write_json(a.state, state)
    print("Recorded: you said no to order %d (%s). Nothing was sent." % (a.index, plain(order)))
    return 0


def cmd_fill(a):
    cfg = read_json(a.config, "config", required=False) or {}
    now = parse_now(a.now)
    date = a.date or to_ist(now).date().isoformat()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        raise TicketError("--date wants a date like 2026-11-05")
    pf = apply_fill(a.portfolio, cfg, a.symbol, a.side, a.qty, a.price, date)
    log_fill(a.state, now, date, a.symbol, a.side, a.qty, a.price)
    fees = pf["last_fill"]["charges"]
    print("PAPER fill: %s %s %s at %s on %s in %s. Charges %s. Cash now %s.%s"
          % (a.side, a.qty, a.symbol.upper(), _money(a.price), date, a.portfolio, _money(fees["total"]),
             _money(pf["cash"]), (" Realized P&L so far %s." % _money(pf["realized_pnl"]))
             if a.side == "sell" else ""))
    return 0


def cmd_flatten(a):
    cfg = read_json(a.config, "config", required=False) or {}
    sym = a.symbol.strip().upper()
    now, today = _clock(a)
    source = "--qty"
    if a.qty is not None:
        qty = _f(a.qty)
        if qty is None or qty <= 0:
            raise TicketError("--qty wants the number of shares you hold, like --qty 8")
    else:
        pf = read_json(a.portfolio, "portfolio", required=False) or {}
        qty = sum(_f(p.get("shares", p.get("qty"))) or 0 for p in pf.get("positions", [])
                  if str(p.get("ticker") or p.get("symbol") or "").upper() == sym)
        source = a.portfolio
        if qty <= 1e-9:
            raise TicketError("nothing to flatten: no %s shares in %s (the paper portfolio)" % (sym, a.portfolio))
    plan = read_json(a.plan, "plan", required=False) or {}
    flat_by = (plan.get("flat_by") if str(plan.get("symbol", "")).upper() == sym else None) \
        or cfg.get("flat_by") or "15:10"
    order = {"symbol": sym, "exchange": "NSE", "side": "sell", "qty": _str_num(qty), "type": "market",
             "time_in_force": "day", "product": str(cfg.get("product") or "MIS").upper(),
             "why": "flat by %s IST: closes the %s day trade before the MIS square-off (qty from %s)"
             % (flat_by, sym, source)}
    old = read_json(a.orders, "orders", required=False)
    replaced = len(old.get("orders", [])) if isinstance(old, dict) else 0
    doc = {"created_by": "trader-broker", "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "status": "proposed",
           "paper": bool(cfg.get("paper", True)),
           "note": "Flatten ticket. Nothing is placed until trader-risk passes it and you say yes in the chat.",
           "source": "ticket.py flatten %s on %s" % (sym, today), "orders": [order]}
    write_json(a.orders, doc)
    print("Flatten %s: %s (flat by %s IST)." % (sym, plain(order), flat_by))
    print("Wrote it to %s%s." % (a.orders, (" (it replaced %d earlier proposal%s)"
                                             % (replaced, "" if replaced == 1 else "s")) if replaced else ""))
    print("Next:")
    print("  1. trader-risk: check.py. A sell that only closes what you hold is never blocked by the daily")
    print("     limits or the entry window.")
    print("  2. ticket.py show, then the user's yes for this one order: approve fills it on paper and the")
    print("     open stop-loss and take-profit of the day's bracket are done with.")
    return 0


def cmd_log(a):
    state = load_state(a.state)
    now, today = _clock(a)
    rows = [r for r in state.get("orders", []) if a.all or rec_day(r) == today]
    if not rows:
        print("No decisions recorded%s." % ("" if a.all else " today"))
        return 1
    for r in rows:
        extra = (" id " + r["broker_order_id"]) if r.get("broker_order_id") else ""
        reply = (' reply "%s"' % r["reply"]) if r.get("reply") and r["status"] in ("approved", "declined") else ""
        loss = (" max loss %s" % _money(r["max_loss"])) if r.get("max_loss") is not None and r["status"] == "placed" else ""
        idx = ("#%s" % r["index"]) if r.get("index") is not None else "  "
        print("%s  %s %-9s %s%s%s%s" % (r.get("at"), idx, r.get("status"), r.get("plain"), reply, loss, extra))
    placed = sum(1 for r in rows if r.get("status") == "placed")
    print("%d placed%s." % (placed, "" if a.all else " today"))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Order tickets, your yes and paper fills (trader-broker, NSE). "
                                             "Never places a real order.")
    sub = ap.add_subparsers(dest="cmd")

    def clock(p):
        p.add_argument("--now", help="pretend it is this India time (IST), e.g. \"2026-11-05 10:00\"")
        p.add_argument("--today", help="YYYY-MM-DD (default: today in IST)")

    def common(p):
        p.add_argument("--orders", default="trader/orders.json")
        p.add_argument("--config", default="trader/config.json")
        p.add_argument("--risk", default="trader/state/risk.json")
        p.add_argument("--state", default="trader/state/broker.json")
        clock(p)

    p = sub.add_parser("show", help="render the tickets")
    common(p)
    p.add_argument("--index", type=int)
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("approve", help="record the user's explicit yes for one order")
    common(p)
    p.add_argument("--index", type=int, required=True)
    p.add_argument("--reply", required=True, help="the user's reply, word for word")
    p.add_argument("--price", help="the paper fill price (default: a fresh trader/prices.json price, else the plan's entry)")
    p.add_argument("--prices", default="trader/prices.json")
    p.add_argument("--portfolio", default="trader/portfolio.json")
    p = sub.add_parser("decline", help="record a no")
    common(p)
    p.add_argument("--index", type=int, required=True)
    p.add_argument("--reply")
    p = sub.add_parser("fill", help="record a paper fill in trader/portfolio.json")
    p.add_argument("--symbol", required=True)
    p.add_argument("--side", required=True, choices=["buy", "sell"])
    p.add_argument("--qty", required=True)
    p.add_argument("--price", required=True)
    p.add_argument("--date", help="YYYY-MM-DD (default: today in IST)")
    p.add_argument("--now")
    p.add_argument("--portfolio", default="trader/portfolio.json")
    p.add_argument("--config", default="trader/config.json")
    p.add_argument("--state", default="trader/state/broker.json")
    p = sub.add_parser("flatten", help="a sell ticket that closes a symbol's position by flat_by")
    p.add_argument("--symbol", required=True)
    p.add_argument("--qty", help="shares to close (default: what trader/portfolio.json holds)")
    p.add_argument("--orders", default="trader/orders.json", help="where the ticket is written")
    p.add_argument("--portfolio", default="trader/portfolio.json")
    p.add_argument("--plan", default="trader/plan.json")
    p.add_argument("--config", default="trader/config.json")
    clock(p)
    p = sub.add_parser("log", help="today's decisions")
    p.add_argument("--state", default="trader/state/broker.json")
    clock(p)
    p.add_argument("--all", action="store_true")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    try:
        return {"show": cmd_show, "approve": cmd_approve, "decline": cmd_decline,
                "fill": cmd_fill, "flatten": cmd_flatten, "log": cmd_log}[a.cmd](a)
    except TicketError as e:
        print("ticket.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

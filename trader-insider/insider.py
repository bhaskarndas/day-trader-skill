#!/usr/bin/env python3
"""Insider tracker for trader-insider (NSE). Standard library only.

India's version of watching what insiders do with their own money. Two
public sources, both on NSE:

  SEBI PIT disclosures   under SEBI's Prohibition of Insider Trading rules
                         (regulation 7(2)), promoters, the promoter group,
                         directors and designated persons must tell their
                         company within two trading days when they trade
                         more than ₹10 lakh of its shares in a quarter, and
                         the company tells the exchange within two more.
  Bulk and block deals   any trade of more than 0.5 % of a company's shares
                         in a day (bulk), and big trades in the block window
                         (block), with the buyer's or seller's name.

    python3 insider.py pit RELIANCE                   # the last 30 days of insider filings
    python3 insider.py pit RELIANCE --days 90 --all   # every kind, not only market trades
    python3 insider.py deals                          # today's bulk and block deals
    python3 insider.py deals --tickers RELIANCE TCS   # only these symbols
    python3 insider.py new                            # new since the last check, for your watchlist
    python3 insider.py new --tickers RELIANCE INFY --json

What it shows by default (pit): open-market buys and sells (acqMode "Market
Purchase" / "Market Sale") by promoters, the promoter group, directors and
key managerial personnel: the trades where an insider put their own money
on the line at the market price. --all adds off-market transfers, gifts,
ESOP allotments, pledges, revocations and the designated employees. A
filing whose intimation to the company came more than 2 trading days after
the trade is flagged LATE.

Sources (NSE's site wants a browser-like visit first, made once per run):
  https://www.nseindia.com/api/corporates-pit?index=equities&symbol=<SYMBOL>&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY
  https://www.nseindia.com/api/snapshot-capital-market-largedeal
State: trader/state/insider.json remembers what you have seen. Your symbols,
when --tickers is not given: trader/watchlist.json, trader/plan.json and
trader/portfolio.json. Offline: --offline DIR reads nse-pit-<SYMBOL>.json
and nse-largedeal.json.

An insider buying is a lead, not a signal: they can be early, wrong, or
buying for reasons that have nothing to do with the price. Not financial
advice, and nothing here places an order: trader-broker asks you yes or no.
"""

import argparse
import datetime as _dt
import gzip
import hashlib
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

NSE_HOME = "https://www.nseindia.com/"
PIT_URL = "https://www.nseindia.com/api/corporates-pit?index=equities&symbol=%s&from_date=%s&to_date=%s"
DEALS_URL = "https://www.nseindia.com/api/snapshot-capital-market-largedeal"
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
IST = _dt.timedelta(hours=5, minutes=30)
INSIDERS = ("promoter", "director", "key managerial", "kmp", "immediate relative")
MARKET_MODES = ("market purchase", "market sale")
LATE_TRADING_DAYS = 2
KEEP_DAYS = 120
MONTHS = {m: i for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT",
                                      "NOV", "DEC"), 1)}
NSE_HOLIDAYS = {"2026-01-15", "2026-01-26", "2026-03-03", "2026-03-26", "2026-03-31", "2026-04-03",
                "2026-04-14", "2026-05-01", "2026-05-28", "2026-06-26", "2026-09-14", "2026-10-02",
                "2026-10-20", "2026-11-10", "2026-11-24", "2026-12-25"}


class InsiderError(Exception):
    pass


# ---------------------------------------------------------------- fetching

class Fetcher(object):
    def __init__(self, offline=None, pause=0.3):
        self.offline = offline
        self.pause = pause
        self._last = 0.0
        self._opener = None

    def json(self, url, name):
        if self.offline:
            for cand in (name, name + ".gz"):
                path = os.path.join(self.offline, cand)
                if os.path.isfile(path):
                    opener = gzip.open if cand.endswith(".gz") else open
                    with opener(path, "rt", encoding="utf-8") as fh:
                        return json.load(fh)
            raise InsiderError("offline: no file %s" % os.path.join(self.offline, name))
        headers = {"User-Agent": BROWSER_UA, "Accept-Encoding": "gzip", "Accept-Language": "en-IN,en;q=0.9"}
        if self._opener is None:
            self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            try:
                self._opener.open(urllib.request.Request(NSE_HOME, headers=dict(headers, Accept="text/html")),
                                  timeout=30).read()
            except (urllib.error.URLError, OSError):
                pass
        gap = time.time() - self._last
        if gap < self.pause:
            time.sleep(self.pause - gap)
        self._last = time.time()
        req = urllib.request.Request(url, headers=dict(headers, Accept="application/json", Referer=NSE_HOME))
        try:
            with self._opener.open(req, timeout=30) as resp:
                data = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
        except urllib.error.HTTPError as exc:
            raise InsiderError("NSE answered HTTP %s for %s" % (exc.code, url.split("?")[0]))
        except urllib.error.URLError as exc:
            raise InsiderError("could not reach nseindia.com: %s" % exc.reason)
        try:
            return json.loads(data.decode("utf-8", "replace"))
        except ValueError:
            raise InsiderError("NSE sent something that is not JSON for %s (it may have refused the request)"
                               % url.split("?")[0])


# ---------------------------------------------------------------- dates

def nse_date(s):
    """"13-Feb-2026" or "18-Feb-2026 19:06" -> date, or None."""
    m = re.match(r"^\s*(\d{1,2})-([A-Za-z]{3})-(\d{4})", str(s or ""))
    if not m or m.group(2).upper() not in MONTHS:
        return None
    try:
        return _dt.date(int(m.group(3)), MONTHS[m.group(2).upper()], int(m.group(1)))
    except ValueError:
        return None


def trading_days_between(a, b):
    """Trading days after a, up to and including b (weekends and NSE holidays skipped)."""
    if not a or not b or b <= a:
        return 0
    n, d = 0, a
    while d < b:
        d += _dt.timedelta(days=1)
        if d.weekday() < 5 and d.isoformat() not in NSE_HOLIDAYS:
            n += 1
    return n


def today_ist(now=None):
    now = now or _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)
    return (now + IST).date()


def parse_now(text):
    """"2026-11-06 11:30" (IST) or ...Z -> naive UTC."""
    if not text:
        return _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None).replace(microsecond=0)
    t = text.strip().replace("Z", "+00:00")
    try:
        d = _dt.datetime.fromisoformat(t)
    except ValueError:
        raise InsiderError("--now wants a time like \"2026-11-06 11:30\" (IST)")
    if d.tzinfo is None:
        return d - IST
    return (d - d.utcoffset()).replace(tzinfo=None)


# ---------------------------------------------------------------- PIT disclosures

def _num(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse_pit(doc, symbol=None):
    """corporates-pit JSON -> trades, newest filing first."""
    rows = doc.get("data") if isinstance(doc, dict) else doc
    if not isinstance(rows, list):
        raise InsiderError("the insider-trading answer is not the shape this tool knows")
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        sym = str(r.get("symbol") or symbol or "").upper()
        if symbol and sym and sym != symbol.upper():
            continue
        kind = str(r.get("tdpTransactionType") or "").strip() or "-"
        mode = str(r.get("acqMode") or "").strip() or "-"
        cat = str(r.get("personCategory") or "").strip() or "-"
        qty = _num(r.get("secAcq"))
        value = _num(r.get("secVal"))
        traded = nse_date(r.get("acqtoDt")) or nse_date(r.get("acqfromDt"))
        told = nse_date(r.get("intimDt"))
        filed = nse_date(r.get("date"))
        lag = trading_days_between(traded, told or filed)
        out.append({
            "id": "pit:%s" % (r.get("did") or r.get("pid") or hashlib.sha1(json.dumps(r, sort_keys=True).encode()).hexdigest()[:12]),
            "symbol": sym, "company": r.get("company") or sym, "name": " ".join(str(r.get("acqName") or "").split()),
            "category": cat, "type": kind, "mode": mode, "security": r.get("secType") or "",
            "qty": qty, "value": value, "price": round(value / qty, 2) if value and qty else None,
            "before_pct": _num(r.get("befAcqSharesPer")), "after_pct": _num(r.get("afterAcqSharesPer")),
            "traded": traded.isoformat() if traded else None, "told": told.isoformat() if told else None,
            "filed": (r.get("date") or "").strip() or None, "filed_date": filed.isoformat() if filed else None,
            "lag_trading_days": lag, "late": lag > LATE_TRADING_DAYS,
            "insider": any(k in cat.lower() for k in INSIDERS),
            "market": mode.lower() in MARKET_MODES, "link": r.get("xbrl") or None,
        })
    out.sort(key=lambda x: (x["filed_date"] or "", x["traded"] or ""), reverse=True)
    return out


def interesting(t):
    """The default filter: an insider's open-market buy or sell."""
    return t["insider"] and t["market"] and t["type"].lower() in ("buy", "sell")


def rupees(v):
    if v is None:
        return "-"
    if abs(v) >= 1e7:
        return "₹%.2f cr" % (v / 1e7)
    if abs(v) >= 1e5:
        return "₹%.2f lakh" % (v / 1e5)
    return "₹{:,.0f}".format(v)


def describe(t):
    verb = {"buy": "BOUGHT", "sell": "SOLD"}.get(t["type"].lower(), t["type"].upper())
    qty = "{:,.0f}".format(t["qty"]) if t["qty"] is not None else "?"
    price = (" at about ₹%.2f" % t["price"]) if t["price"] else ""
    hold = ""
    if t["before_pct"] is not None and t["after_pct"] is not None and (t["before_pct"] or t["after_pct"]):
        hold = ", holding %.2f%% -> %.2f%%" % (t["before_pct"], t["after_pct"])
    late = "  LATE (%d trading days after the trade)" % t["lag_trading_days"] if t["late"] else ""
    return ("%s  %-12s %-28s %-18s %s %s shares%s (%s, %s)%s, traded %s, filed %s%s"
            % ("!" if interesting(t) else " ", t["symbol"], t["name"][:28], t["category"][:18], verb, qty, price,
               rupees(t["value"]), t["mode"], hold, t["traded"] or "?", t["filed"] or "?", late))


def fetch_pit(fetcher, symbol, days, now):
    end = today_ist(now)
    start = end - _dt.timedelta(days=days)
    url = PIT_URL % (urllib.parse.quote(symbol, safe=""), start.strftime("%d-%m-%Y"), end.strftime("%d-%m-%Y"))
    trades = parse_pit(fetcher.json(url, "nse-pit-%s.json" % symbol), symbol)
    return [t for t in trades if not t["filed_date"] or start.isoformat() <= t["filed_date"] <= end.isoformat()]


# ---------------------------------------------------------------- bulk and block deals

def parse_deals(doc):
    """snapshot-capital-market-largedeal JSON -> deals (bulk, block)."""
    if not isinstance(doc, dict):
        raise InsiderError("the bulk and block deals answer is not the shape this tool knows")
    out = []
    for kind, key in (("bulk", "BULK_DEALS_DATA"), ("block", "BLOCK_DEALS_DATA")):
        for r in doc.get(key) or []:
            if not isinstance(r, dict):
                continue
            qty, price = _num(r.get("qty")), _num(r.get("watp"))
            d = nse_date(r.get("date"))
            out.append({"id": "deal:%s:%s:%s:%s:%s" % (kind, r.get("symbol"), r.get("date"), r.get("clientName"),
                                                       r.get("qty")),
                        "kind": kind, "symbol": str(r.get("symbol") or "").upper(), "company": r.get("name") or "",
                        "client": " ".join(str(r.get("clientName") or "").split()),
                        "side": str(r.get("buySell") or "").upper(), "qty": qty, "price": price,
                        "value": round(qty * price, 2) if qty and price else None,
                        "date": d.isoformat() if d else None})
    return out, doc.get("as_on_date")


def describe_deal(d):
    qty = "{:,.0f}".format(d["qty"]) if d["qty"] is not None else "?"
    return ("  %-5s %-12s %-4s %s shares at ₹%s (%s)  %s  %s"
            % (d["kind"], d["symbol"], d["side"], qty, "%.2f" % d["price"] if d["price"] else "?",
               rupees(d["value"]), d["client"], d["date"] or ""))


# ---------------------------------------------------------------- your symbols and the state

def load_json(path):
    if path and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except ValueError:
            return None
    return None


def watch_from(args):
    if args.tickers:
        return sorted({t.upper().replace(".NS", "") for t in args.tickers})
    syms = set()
    wl = load_json(args.watchlist) or {}
    for h in (wl.get("hits") or []) if isinstance(wl, dict) else []:
        if isinstance(h, dict) and h.get("symbol"):
            syms.add(str(h["symbol"]).upper())
    plan = load_json(args.plan) or {}
    if isinstance(plan, dict) and plan.get("symbol"):
        syms.add(str(plan["symbol"]).upper())
    pf = load_json(args.portfolio) or {}
    for p in (pf.get("positions") or []) if isinstance(pf, dict) else []:
        s = p.get("ticker") or p.get("symbol")
        if s:
            syms.add(str(s).upper())
    return sorted(syms)


def save_state(path, state):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


# ---------------------------------------------------------------- commands

def cmd_pit(args, fetcher, now):
    syms = [s.upper().replace(".NS", "") for s in args.symbols] or watch_from(args)
    if not syms:
        raise InsiderError("which symbols? insider.py pit RELIANCE, or run /trader-scanner first")
    rows, errors = [], []
    for s in syms:
        try:
            rows += fetch_pit(fetcher, s, args.days, now)
        except InsiderError as e:
            errors.append("%s: %s" % (s, e))
    shown = rows if args.all else [t for t in rows if interesting(t)]
    if args.json:
        print(json.dumps({"trades": shown, "hidden": len(rows) - len(shown), "errors": errors}, indent=2))
        return 0 if shown else 1
    print("SEBI insider-trading (PIT) disclosures on NSE, last %d days: %s." % (args.days, ", ".join(syms)))
    if not shown:
        print("No %s." % ("filings" if args.all else "open-market buys or sells by promoters, directors or KMP"))
    for t in shown:
        print(describe(t))
    if len(rows) > len(shown):
        print("(%d more filings: off-market transfers, pledges, ESOPs, designated employees. --all shows them.)"
              % (len(rows) - len(shown)))
    for e in errors:
        print("note: " + e)
    print("An insider trade is a lead, not a signal. Not financial advice.")
    return 0 if shown else 1


def cmd_deals(args, fetcher, now):
    deals, as_on = parse_deals(fetcher.json(DEALS_URL, "nse-largedeal.json"))
    syms = set(s.upper().replace(".NS", "") for s in (args.tickers or []))
    if syms:
        deals = [d for d in deals if d["symbol"] in syms]
    if args.json:
        print(json.dumps({"as_on": as_on, "deals": deals}, indent=2))
        return 0 if deals else 1
    print("NSE bulk and block deals%s%s: %d." % ((" as on %s" % as_on) if as_on else "",
                                                 (" for " + ", ".join(sorted(syms))) if syms else "", len(deals)))
    for d in sorted(deals, key=lambda d: -(d["value"] or 0))[:args.show]:
        print(describe_deal(d))
    if len(deals) > args.show:
        print("  ... and %d more (--show N)." % (len(deals) - args.show))
    print("A bulk deal names who traded, not why. Not financial advice.")
    return 0 if deals else 1


def cmd_new(args, fetcher, now):
    syms = watch_from(args)
    if not syms:
        raise InsiderError("no symbols: pass --tickers, or run /trader-scanner first (trader/watchlist.json)")
    state = load_json(args.state) or {}
    seen = state.setdefault("seen", {})
    first = not seen
    items, errors = [], []
    for s in syms:
        try:
            for t in fetch_pit(fetcher, s, args.days, now):
                if args.all or interesting(t):
                    items.append(("pit", t))
        except InsiderError as e:
            errors.append("%s: %s" % (s, e))
    try:
        deals, _ = parse_deals(fetcher.json(DEALS_URL, "nse-largedeal.json"))
        items += [("deal", d) for d in deals if d["symbol"] in syms]
    except InsiderError as e:
        errors.append("bulk and block deals: %s" % e)
    new = [(k, x) for k, x in items if x["id"] not in seen]
    stamp = (now + IST).strftime("%Y-%m-%d %H:%M")
    if not args.dry_run:
        for _, x in items:
            seen.setdefault(x["id"], stamp)
        cutoff = ((now + IST) - _dt.timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d %H:%M")
        state["seen"] = {k: v for k, v in seen.items() if v >= cutoff}
        state["last_check"] = stamp
        save_state(args.state, state)
    if args.json:
        print(json.dumps({"checked": stamp, "first_run": first, "new": [dict(x, source=k) for k, x in new],
                          "errors": errors}, indent=2))
        return 0 if new else 1
    print("Insider check, %s IST, for %s%s." % (stamp, ", ".join(syms),
                                                " (first run: everything in the window counts as new)" if first else ""))
    if not new:
        print("Nothing new.")
    for k, x in new:
        print(describe(x) if k == "pit" else describe_deal(x))
    for e in errors:
        print("note: " + e)
    print("An insider trade is a lead, not a signal. Not financial advice.")
    return 0 if new else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="Insider tracker (trader-insider): SEBI PIT disclosures and NSE "
                                             "bulk/block deals.")
    sub = ap.add_subparsers(dest="cmd")

    def common(p):
        p.add_argument("--offline", metavar="DIR")
        p.add_argument("--now", help="pretend it is this IST time, e.g. \"2026-11-06 11:30\"")
        p.add_argument("--json", action="store_true")
        p.add_argument("--watchlist", default="trader/watchlist.json")
        p.add_argument("--plan", default="trader/plan.json")
        p.add_argument("--portfolio", default="trader/portfolio.json")

    p = sub.add_parser("pit", help="insider-trading disclosures for symbols")
    p.add_argument("symbols", nargs="*")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--all", action="store_true", help="every filing, not only insiders' market trades")
    p.add_argument("--tickers", nargs="*", help=argparse.SUPPRESS)
    common(p)
    p = sub.add_parser("deals", help="today's bulk and block deals")
    p.add_argument("--tickers", nargs="*")
    p.add_argument("--show", type=int, default=40)
    common(p)
    p = sub.add_parser("new", help="what is new since the last check, for your symbols")
    p.add_argument("--tickers", nargs="*")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--all", action="store_true")
    p.add_argument("--state", default="trader/state/insider.json")
    p.add_argument("--dry-run", action="store_true")
    common(p)
    args = ap.parse_args(argv)
    if not args.cmd:
        ap.print_help()
        return 2
    try:
        now = parse_now(args.now)
        fetcher = Fetcher(offline=args.offline)
        return {"pit": cmd_pit, "deals": cmd_deals, "new": cmd_new}[args.cmd](args, fetcher, now)
    except InsiderError as e:
        print("insider.py: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

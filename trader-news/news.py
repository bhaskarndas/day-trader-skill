#!/usr/bin/env python3
"""News monitor for trader-news (NSE). Standard library only.

Watches headlines and NSE corporate announcements (the filings listed
companies must make to the exchange) for the stocks you watch or hold and
prints only what is new since the last check, newest first, with how far each
stock has moved today and a flag on anything that touches your symbols.

    python3 news.py                                  # watchlist + plan + portfolio symbols
    python3 news.py --tickers RELIANCE TCS INFY
    python3 news.py --tickers RELIANCE --all --hours 72   # everything in 3 days, seen or not
    python3 news.py --no-nse                         # headlines only
    python3 news.py --no-moves                       # skip the price line per symbol

Your symbols, when --tickers is not given: every hit in trader/watchlist.json
(trader-scanner), the symbol in trader/plan.json (trader-exit) and the
positions in trader/portfolio.json.

Sources, one request each per symbol:
  - NSE corporate announcements (board meeting outcomes, results, credit
    ratings, acquisitions, director changes, analyst meets ...):
    https://www.nseindia.com/api/corporate-announcements?index=equities&symbol=<SYMBOL>
    NSE's site wants a browser-like visit first (it sets cookies on
    https://www.nseindia.com/), which the tool does once per run. If NSE
    refuses anyway, the tool says so and headlines still run.
    Announcements that usually move a stock are marked "!" (results, board
    meeting outcomes, deals, credit ratings, resignations, defaults,
    insolvency, fraud, pledges, buybacks and the like).
  - Yahoo Finance headline RSS (often thin for NSE stocks):
    https://feeds.finance.yahoo.com/rss/2.0/headline?s=<SYMBOL>.NS&region=IN&lang=en-IN
  - The move: Yahoo Finance's chart endpoint (unofficial, can lag), the last
    price against yesterday's close:
    https://query2.finance.yahoo.com/v8/finance/chart/<SYMBOL>.NS?range=1d&interval=5m

Times print in IST. State: trader/state/news.json remembers what you have
seen (30 days), so an item shows once. Offline: --offline DIR reads
yahoo-<SYMBOL>.xml, chart-<SYMBOL>.json and nse-ann-<SYMBOL>.json from DIR.
The tests use it.

Headlines are leads, not facts: open the story or the filing before acting,
and treat nothing here as advice.
"""

import argparse
import datetime as _dt
import email.utils
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
import xml.etree.ElementTree as ET

YAHOO = "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%s&region=IN&lang=en-IN"
CHART = "https://%s.finance.yahoo.com/v8/finance/chart/%s?range=1d&interval=5m"
NSE_HOME = "https://www.nseindia.com/"
NSE_ANN = "https://www.nseindia.com/api/corporate-announcements?index=equities&symbol=%s"
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
KEEP_DAYS = 30
MOVE_PCT = 3.0  # a stock this far from yesterday's close is flagged as moving

# NSE announcement subjects ("desc") that usually move a stock
IMPORTANT = re.compile(
    r"financial results?|outcome of board meeting|acquisition|amalgamation|merger|scheme of arrangement|"
    r"credit rating|resignation|cessation|change in (?:director|management|auditor|key managerial)|"
    r"fraud|default|insolvency|cirp|liquidation|suspension|delisting|buy ?back|bonus|split|"
    r"pledge|encumbrance|restructuring|order|contract|award|litigation|dispute|search|raid", re.I)
EARNINGS = re.compile(r"financial results?|outcome of board meeting", re.I)
KEYWORDS = [
    ("earnings", r"\bearnings\b|\bresults?\b|\bEPS\b|\bguidance\b|\bprofit\b|\bQ[1-4]\b|\bPAT\b|\bEBITDA\b"),
    ("analyst", r"\bupgrade[sd]?\b|\bdowngrade[sd]?\b|price target|target price|\boutperform\b|"
                r"\bunderperform\b|\banalysts?\b|\binvestor meet\b"),
    ("legal", r"\blawsuit\b|\bprobe\b|\binvestigation\b|\bpenalty\b|\bSEBI order\b|\bNCLT\b|\bcourt\b|"
              r"\blitigation\b|\braid\b|\bsearch\b"),
    ("deal", r"\bacqui(?:re|res|red|sition)\b|\bmerger\b|\bbuyout\b|\btakeover\b|\bdeal\b"),
    ("capital", r"\bdividend\b|\bbuy ?back\b|\bbonus\b|\bsplit\b|\bQIP\b|\brights issue\b|\bOFS\b|\bblock deal\b"),
    ("people", r"\bCEO\b|\bCFO\b|\bMD\b|\bresign|\bsteps down\b|\bappoint|\bcessation\b"),
    ("risk", r"\bdefault\b|\binsolvency\b|\bpledge|\bfraud\b|\bdelist|\bhack|\bbreach\b|\boutage\b|\bdowngrade\b"),
    ("halt", r"\bcircuit\b|\bsuspen|\btrading halt|\bASM\b|\bGSM\b"),
    ("regulatory", r"\bSEBI\b|\bRBI\b|\bCCI\b|\bUSFDA\b|\bapproval\b|\blicen[cs]e\b"),
    ("macro", r"\bRBI\b|\brepo rate\b|\bMPC\b|\bCPI\b|\binflation\b|\bGDP\b|\bBudget\b|\btariffs?\b|"
              r"\bFIIs?\b|\bFPIs?\b|\bGIFT Nifty\b|\bcrude\b"),
]


class NewsError(Exception):
    pass


# ---------------------------------------------------------------- time

IST_OFFSET = _dt.timedelta(hours=5, minutes=30)   # India has no daylight saving


def ist_offset(utc=None):
    """Hours from UTC for India: always +5.5 (IST, no daylight saving)."""
    return 5.5


def to_ist(utc):
    return utc.replace(tzinfo=None) + IST_OFFSET


def ist_to_utc(local):
    return local.replace(tzinfo=None) - IST_OFFSET


def load_json(path):
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return None


def watch_from_files(portfolio="trader/portfolio.json", watchlist="trader/watchlist.json",
                     plan="trader/plan.json"):
    """{ticker: name or None}: the scanner's hits, the planned trade and your holdings."""
    out = {}
    wl = load_json(watchlist) or {}
    for h in wl.get("hits", []):
        sym = h.get("symbol") or h.get("ticker")
        if sym:
            out[sym.upper()] = h.get("name")
    pl = load_json(plan) or {}
    if pl.get("symbol"):
        out.setdefault(pl["symbol"].upper(), pl.get("name"))
    pf = load_json(portfolio) or {}
    for p in pf.get("positions", []):
        sym = p.get("ticker") or p.get("symbol")
        if sym:
            out[sym.upper()] = p.get("name") or out.get(sym.upper())
    return out


# ---------------------------------------------------------------- fetching

class Fetcher(object):
    """Network or offline files. NSE's API is read in one cookie session that first
    visits https://www.nseindia.com/ the way a browser does."""

    def __init__(self, offline=None, pause=0.15):
        self.offline = offline
        self.pause = pause
        self._last = 0.0
        self._nse = None

    def _wait(self):
        gap = time.time() - self._last
        if gap < self.pause:
            time.sleep(self.pause - gap)
        self._last = time.time()

    def get(self, url, name, nse=False):
        if self.offline:
            path = os.path.join(self.offline, name)
            if not os.path.isfile(path):
                raise NewsError("offline: no file %s" % path)
            with open(path, "rb") as fh:
                return fh.read()
        self._wait()
        headers = {"User-Agent": BROWSER_UA, "Accept-Encoding": "gzip", "Accept-Language": "en-IN,en;q=0.9"}
        opener = urllib.request.build_opener()
        if nse:
            if self._nse is None:
                self._nse = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
                try:
                    self._nse.open(urllib.request.Request(NSE_HOME, headers=dict(headers, Accept="text/html")),
                                   timeout=30).read()
                except (urllib.error.URLError, OSError):
                    pass   # the API call below says what went wrong
                self._wait()
            opener = self._nse
            headers.update({"Accept": "application/json", "Referer": NSE_HOME})
        req = urllib.request.Request(url, headers=headers)
        try:
            with opener.open(req, timeout=30) as resp:
                data = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                return data
        except urllib.error.HTTPError as exc:
            raise NewsError("HTTP %s for %s" % (exc.code, url.split("?")[0]))
        except urllib.error.URLError as exc:
            raise NewsError("could not reach %s: %s" % (url.split("/")[2], exc.reason))


def yahoo_symbol(ticker):
    """NSE symbol -> Yahoo's: RELIANCE -> RELIANCE.NS (an index ^NSEI or a .NS/.BO symbol stays)."""
    s = ticker.strip().upper()
    s = s if s.startswith("^") or s.endswith((".NS", ".BO")) else s + ".NS"
    return urllib.parse.quote(s, safe="^.")


# ---------------------------------------------------------------- parsing

def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _text(el, name):
    for c in el.iter():
        if _local(c.tag) == name:
            return (c.text or "").strip()
    return ""


def parse_time(value):
    """RFC 822 (RSS) or ISO 8601 (Atom) -> aware UTC datetime, or None."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        d = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        d = None
    if d is None:
        try:
            d = _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=_dt.timezone.utc)
    return d.astimezone(_dt.timezone.utc)


def parse_rss(data, ticker):
    """Yahoo headline RSS -> items."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise NewsError("RSS for %s is not valid XML: %s" % (ticker, exc))
    out = []
    for it in root.iter("item"):
        title = _text(it, "title")
        link = _text(it, "link")
        guid = _text(it, "guid") or link
        out.append({"id": "rss:" + guid, "source": "Yahoo Finance", "kind": "headline",
                    "ticker": ticker, "title": title, "summary": _text(it, "description"),
                    "link": link, "time": parse_time(_text(it, "pubDate"))})
    return out


def parse_ist(value):
    """NSE's "04-Nov-2026 20:47:14" (IST) -> aware UTC datetime, or None."""
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M"):
        try:
            local = _dt.datetime.strptime(str(value or "").strip(), fmt)
            return (local - IST_OFFSET).replace(tzinfo=_dt.timezone.utc)
        except ValueError:
            continue
    return None


def parse_nse_announcements(data, ticker):
    """NSE corporate-announcements JSON (a list) -> items."""
    try:
        rows = json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
    except ValueError:
        raise NewsError("NSE announcements for %s are not JSON (NSE may have refused the request)" % ticker)
    if isinstance(rows, dict):
        rows = rows.get("data") or []
    if not isinstance(rows, list):
        raise NewsError("NSE announcements for %s are not the shape this tool knows" % ticker)
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        desc = " ".join(str(r.get("desc") or "").split())
        text = " ".join(str(r.get("attchmntText") or "").split())
        company = r.get("sm_name") or ticker
        title = "%s: %s" % (company, desc or "announcement")
        out.append({"id": "nse:%s" % (r.get("seq_id") or r.get("an_dt") or title), "source": "NSE filing",
                    "kind": "filing", "form": desc, "ticker": str(r.get("symbol") or ticker).upper(),
                    "title": title, "summary": text, "important": bool(IMPORTANT.search(desc)),
                    "earnings": bool(EARNINGS.search(desc)),
                    "link": r.get("attchmntFile") or "https://www.nseindia.com/companies-listing/"
                            "corporate-filings-announcements",
                    "time": parse_ist(r.get("an_dt") or r.get("exchdisstime"))})
    return out


def parse_chart(data, ticker):
    """Yahoo chart JSON -> {"ticker", "price", "prev_close", "pct", "time"} or raise."""
    try:
        doc = json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
        meta = doc["chart"]["result"][0]["meta"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise NewsError("chart for %s is not usable" % ticker)
    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    if not price or not prev:
        raise NewsError("chart for %s has no price" % ticker)
    when = meta.get("regularMarketTime")
    return {"ticker": ticker, "price": round(float(price), 2), "prev_close": round(float(prev), 2),
            "pct": round((float(price) / float(prev) - 1) * 100, 2),
            "time": _dt.datetime.fromtimestamp(when, _dt.timezone.utc) if when else None}


def collect_moves(fetcher, watch, errors=None):
    errors = [] if errors is None else errors
    out = []
    for t in sorted(watch):
        name = "chart-%s.json" % t
        try:
            try:
                data = fetcher.get(CHART % ("query2", yahoo_symbol(t)), name)
            except NewsError as exc:
                if fetcher.offline or not re.search(r"HTTP (429|5\d\d)", str(exc)):
                    raise
                data = fetcher.get(CHART % ("query1", yahoo_symbol(t)), name)
            out.append(parse_chart(data, t))
        except NewsError as exc:
            if not (fetcher.offline and "no file" in str(exc)):
                errors.append("price for %s: %s" % (t, exc))
    return out


def mention_patterns(watch):
    pats = {}
    for t, name in watch.items():
        alts = [r"\(%s\)" % re.escape(t), r"\b(?:NSE|BSE)\s*:\s*%s\b" % re.escape(t)]
        if name and len(name) >= 4:
            alts.append(r"\b%s\b" % re.escape(name).replace(r"\ ", r"[\s-]"))
        pats[t] = re.compile("|".join(alts))
    return pats


def tag(items, watch):
    """Which of your tickers each item touches, and why it matters."""
    pats = mention_patterns(watch)
    for it in items:
        hay = "%s %s" % (it["title"], it.get("summary") or "")
        touches = {it["ticker"]} if it["ticker"] in watch else set()
        for t, rx in pats.items():
            if rx.search(hay):
                touches.add(t)
        it["touches"] = sorted(touches)
        it["tags"] = [label for label, rx in KEYWORDS if re.search(rx, hay, re.I)]
        if it["kind"] == "filing" and it.get("earnings") and "earnings" not in it["tags"]:
            it["tags"].insert(0, "earnings")
    return items


def dedupe(items):
    """One item per story: same id, or same link, or same title the same day."""
    seen, out = {}, []
    for it in items:
        keys = [it["id"], it["link"],
                "%s|%s" % (re.sub(r"\W+", " ", it["title"].lower()).strip(),
                           it["time"].date() if it["time"] else "")]
        hit = next((seen[k] for k in keys if k and k in seen), None)
        if hit is not None:
            for t in it.get("touches", []):
                if t not in hit["touches"]:
                    hit["touches"].append(t)
            hit["touches"].sort()
            continue
        for k in keys:
            if k:
                seen[k] = it
        out.append(it)
    return out


def fingerprint(it):
    return hashlib.sha1(it["id"].encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- the check

def collect(fetcher, watch, state, nse=True, errors=None):
    errors = [] if errors is None else errors
    items = []
    for t in sorted(watch):
        try:
            items += parse_rss(fetcher.get(YAHOO % yahoo_symbol(t), "yahoo-%s.xml" % t), t)
        except NewsError as exc:
            if not (fetcher.offline and "no file" in str(exc)):
                errors.append("headlines for %s: %s" % (t, exc))
    if nse:
        for t in sorted(watch):
            try:
                data = fetcher.get(NSE_ANN % urllib.parse.quote(t, safe=""), "nse-ann-%s.json" % t, nse=True)
                items += parse_nse_announcements(data, t)
            except NewsError as exc:
                errors.append("NSE announcements for %s: %s" % (t, exc))
    return items


def select(items, state, now, hours=48, show_all=False):
    """Items within the window; only unseen ones unless show_all."""
    seen = state.setdefault("seen", {})
    cutoff = now - _dt.timedelta(hours=hours)
    ahead = now + _dt.timedelta(minutes=10)  # a pinned --now: nothing from after it
    out = []
    for it in items:
        if it["time"] is not None and (it["time"] < cutoff or it["time"] > ahead):
            continue
        fp = fingerprint(it)
        it["new"] = fp not in seen
        if it["new"] or show_all:
            out.append(it)
    out.sort(key=lambda i: (i["time"] or now), reverse=True)
    return out


def remember(items, state, now):
    seen = state.setdefault("seen", {})
    stamp = now.isoformat()
    for it in items:
        seen.setdefault(fingerprint(it), stamp)
    cutoff = (now - _dt.timedelta(days=KEEP_DAYS)).isoformat()
    state["seen"] = {k: v for k, v in seen.items() if v >= cutoff}
    state["last_check"] = stamp


def render_moves(moves, move_pct=MOVE_PCT):
    out = []
    for m in moves:
        flag = "MOVING" if abs(m["pct"]) >= move_pct else ""
        when = (" at %s IST" % to_ist(m["time"]).strftime("%H:%M")) if m.get("time") else ""
        out.append("%-12s ₹%s %+.2f%% vs yesterday's close ₹%s%s  %s" % (
            m["ticker"], "{:,.2f}".format(m["price"]), m["pct"], "{:,.2f}".format(m["prev_close"]),
            when, flag))
    return out


def render(items, errors, now, moves=None, move_pct=MOVE_PCT):
    out = render_moves(moves or [], move_pct)
    if out:
        out.append("")
    if not items:
        out.append("Nothing new.")
    for it in items:
        when = to_ist(it["time"]).strftime("%Y-%m-%d %H:%M IST") if it["time"] else "time unknown"
        mark = "!" if it.get("important") else " "
        who = ",".join(it["touches"]) or it["ticker"]
        out.append("%s %s  %-12s %-13s %s" % (mark, when, who, it["source"], it["title"]))
        if it.get("summary") and it["kind"] == "filing":
            out.append("      " + it["summary"][:200])
        extra = []
        if it["tags"]:
            extra.append("tags: " + ", ".join(it["tags"]))
        extra.append(it["link"])
        out.append("      " + "  ".join(extra))
    for e in errors:
        out.append("note: %s" % e)
    out.append("Checked %s. Headlines are leads, not facts; open the story or the filing before acting. "
               "Not financial advice." % to_ist(now).strftime("%Y-%m-%d %H:%M IST"))
    return "\n".join(out) + "\n"


def _json_ready(items):
    out = []
    for it in items:
        d = dict(it)
        d["time"] = it["time"].isoformat() if it["time"] else None
        out.append(d)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tickers", nargs="*", help="NSE symbols; default: watchlist + plan + portfolio")
    ap.add_argument("--portfolio", default="trader/portfolio.json")
    ap.add_argument("--watchlist", default="trader/watchlist.json")
    ap.add_argument("--plan", default="trader/plan.json")
    ap.add_argument("--state", default="trader/state/news.json")
    ap.add_argument("--hours", type=float, default=48, help="ignore items older than this")
    ap.add_argument("--all", action="store_true", help="show seen items too")
    ap.add_argument("--no-nse", action="store_true", help="headlines only, no NSE announcements")
    ap.add_argument("--no-moves", action="store_true", help="skip the price line per ticker")
    ap.add_argument("--move-pct", type=float, default=MOVE_PCT, help="flag a move this big (percent)")
    ap.add_argument("--offline", metavar="DIR")
    ap.add_argument("--now", help="ISO time, for reproducible runs")
    ap.add_argument("--dry-run", action="store_true", help="do not update the state file")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.tickers:
        watch = {t.upper(): None for t in args.tickers}
        known = watch_from_files(args.portfolio, args.watchlist, args.plan)
        watch.update({t: known[t] for t in watch if known.get(t)})
    else:
        watch = watch_from_files(args.portfolio, args.watchlist, args.plan)
    if not watch:
        print("news: no symbols. Pass --tickers, or run /trader-scanner first (it writes "
              "trader/watchlist.json).", file=sys.stderr)
        return 2
    now = parse_time(args.now) if args.now else _dt.datetime.now(_dt.timezone.utc)
    state = load_json(args.state) or {}
    errors = []
    fetcher = Fetcher(offline=args.offline)
    items = collect(fetcher, watch, state, nse=not args.no_nse, errors=errors)
    items = dedupe(tag(items, watch))
    shown = select(items, state, now, hours=args.hours, show_all=args.all)
    moves = [] if args.no_moves else collect_moves(fetcher, watch, errors)
    if args.json:
        mv = [dict(m, time=m["time"].isoformat() if m.get("time") else None,
                   moving=abs(m["pct"]) >= args.move_pct) for m in moves]
        print(json.dumps({"checked": now.isoformat(), "moves": mv, "items": _json_ready(shown),
                          "notes": errors}, indent=2))
    else:
        sys.stdout.write(render(shown, errors, now, moves, args.move_pct))
    if not args.dry_run:
        remember(items, state, now)
        folder = os.path.dirname(args.state)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(args.state, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
            fh.write("\n")
    return 0 if any(i["new"] for i in shown) else 1


if __name__ == "__main__":
    sys.exit(main())

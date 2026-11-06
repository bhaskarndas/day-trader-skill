#!/usr/bin/env python3
"""Earnings reader for trader-analyst (NSE). Standard library only.

Reads a listed company's quarterly results from the XBRL files it files with
NSE and lays out what changed, quarter by quarter: revenue from operations,
EBITDA and net margins, net profit (and the owners' share of it), basic EPS,
and growth against the same quarter a year earlier and the quarter before.

    python3 facts.py RELIANCE
    python3 facts.py RELIANCE TCS --quarters 6
    python3 facts.py HDFCBANK --standalone
    python3 facts.py RELIANCE --json
    python3 facts.py RELIANCE TCS INFY ITC --metrics trader/metrics.json

Sources (NSE; the site wants a browser-like visit first, which the tool makes
once per run):
  https://www.nseindia.com/api/integrated-filing-results?index=equities&symbol=<SYMBOL>
      "Integrated Filing - Financials", the results filings since SEBI's
      integrated filing (early 2025): one row per filing with its XBRL link
  https://www.nseindia.com/api/corporates-financial-results?index=equities&symbol=<SYMBOL>&period=Quarterly
      the older results filings, used only for quarters the first list lacks
  https://nsearchives.nseindia.com/corporate/xbrl/<file>.xml
      the filing itself (SEBI's in-capmkt taxonomy; tags read by name)

How the quarters are built:
  - Consolidated results by default (the group, which is what moves the
    stock); --standalone for the listed company alone. A quarter with only
    the other basis falls back to it and says so.
  - A filing covers its own quarter (and the year to date); the comparisons
    come from the filings of the earlier quarters. When a quarter was filed
    more than once (a revision), the latest filing wins.
  - The quarter's numbers are the facts whose context is a ~3-month period
    ending on the report date with no segment (the "OneD" context).
  - EBITDA is worked out, not filed: profit before tax + finance costs +
    depreciation - other income. Banks report interest income differently;
    their revenue falls back to total income and EBITDA is left blank.
  - Rupee amounts print in crore (1 crore = 1,00,00,000).

--metrics FILE merges one row per symbol into a JSON file (TTM revenue, net
profit and EPS, margins, growth). Offline: --offline DIR reads
nse-results-<SYMBOL>.json, nse-results-legacy-<SYMBOL>.json (optional) and
the XBRL files by their own names from DIR.

Numbers only: this tool never says whether a stock is a buy.
"""

import argparse
import datetime as _dt
import gzip
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

NSE_HOME = "https://www.nseindia.com/"
LIST_URL = "https://www.nseindia.com/api/integrated-filing-results?index=equities&symbol=%s"
LEGACY_URL = "https://www.nseindia.com/api/corporates-financial-results?index=equities&symbol=%s&period=Quarterly"
XBRL_BASE = "https://nsearchives.nseindia.com/corporate/xbrl/"
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
CRORE = 1e7
# metric: the tags tried in order (SEBI in-capmkt and the older in-bse-fin names)
CONCEPTS = {
    "revenue": ("RevenueFromOperations",),
    "other_income": ("OtherIncome",),
    "total_income": ("Income", "TotalIncome"),
    "expenses": ("Expenses", "TotalExpenses"),
    "finance_costs": ("FinanceCosts",),
    "depreciation": ("DepreciationDepletionAndAmortisationExpense", "DepreciationAndAmortisationExpense"),
    "pbt": ("ProfitBeforeTax", "ProfitLossBeforeTax", "ProfitLossBeforeTaxFromContinuingOperations"),
    "net_profit": ("ProfitLossForPeriod", "ProfitLossForThePeriod"),
    "owners_profit": ("ProfitOrLossAttributableToOwnersOfParent", "ProfitLossAttributableToOwnersOfParent"),
    "eps_basic": ("BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
                  "BasicEarningsLossPerShareFromContinuingOperations", "BasicEarningsPerShareAfterExtraordinaryItems"),
    "eps_diluted": ("DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
                    "DilutedEarningsLossPerShareFromContinuingOperations"),
}
MONTHS = {m: i for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT",
                                      "NOV", "DEC"), 1)}


class FactsError(Exception):
    pass


# ---------------------------------------------------------------- fetching

class Fetcher(object):
    """Network or offline files. NSE's API is read in one cookie session that first
    visits https://www.nseindia.com/ the way a browser does."""

    def __init__(self, offline=None, pause=0.3):
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
            for cand in (name, name + ".gz"):
                path = os.path.join(self.offline, cand)
                if os.path.isfile(path):
                    opener = gzip.open if cand.endswith(".gz") else open
                    with opener(path, "rb") as fh:
                        return fh.read()
            raise FactsError("offline: no file %s" % os.path.join(self.offline, name))
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
                    pass
                self._wait()
            opener = self._nse
            headers.update({"Accept": "application/json", "Referer": NSE_HOME})
        try:
            with opener.open(urllib.request.Request(url, headers=headers), timeout=45) as resp:
                data = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                return data
        except urllib.error.HTTPError as exc:
            raise FactsError("HTTP %s for %s" % (exc.code, url.split("?")[0]))
        except urllib.error.URLError as exc:
            raise FactsError("could not reach %s: %s" % (url.split("/")[2], exc.reason))

    def json(self, url, name, nse=True):
        data = self.get(url, name, nse=nse)
        try:
            return json.loads(data.decode("utf-8", "replace"))
        except ValueError:
            raise FactsError("%s is not JSON (NSE may have refused the request)" % url.split("?")[0])


# ---------------------------------------------------------------- the filings list

def nse_date(s):
    """"30-SEP-2026", "31-Dec-2024", "30-Oct-2026 21:32:55" -> date, or None."""
    m = re.match(r"^\s*(\d{1,2})-([A-Za-z]{3})-(\d{4})", str(s or ""))
    if not m or m.group(2).upper() not in MONTHS:
        return None
    try:
        return _dt.date(int(m.group(3)), MONTHS[m.group(2).upper()], int(m.group(1)))
    except ValueError:
        return None


def nse_stamp(s):
    """"30-Oct-2026 21:32:55" -> "2026-10-30 21:32:55" (sortable), or ""."""
    d = nse_date(s)
    if not d:
        return ""
    m = re.search(r"(\d{2}:\d{2}(?::\d{2})?)", str(s))
    return "%s %s" % (d.isoformat(), m.group(1) if m else "00:00")


def xbrl_url(link):
    link = str(link or "").strip()
    if not link or link == "-":
        return None
    if link.startswith("http"):
        return link
    return XBRL_BASE + link.split("/")[-1]


def filings_from(rows, source):
    """NSE list rows (integrated or legacy) -> [{end, basis, filed, xbrl, audited, revised, source}]."""
    if isinstance(rows, dict):
        rows = rows.get("data") or []
    out = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        if source == "integrated":
            if r.get("type") and "financial" not in str(r["type"]).lower():
                continue
            end = nse_date(r.get("qe_Date"))
            filed = nse_stamp(r.get("broadcast_Date") or r.get("creation_Date"))
            revised = str(r.get("type_Sub") or "").lower().startswith("revis") or bool(r.get("revised_Date"))
        else:
            if str(r.get("period") or "Quarterly").lower() != "quarterly":
                continue
            end = nse_date(r.get("toDate"))
            start = nse_date(r.get("fromDate"))
            if start and end and not 80 <= (end - start).days <= 100:
                continue
            filed = nse_stamp(r.get("filingDate") or r.get("broadCastDate"))
            revised = False
        url = xbrl_url(r.get("xbrl"))
        if not end or not url:
            continue
        cons = str(r.get("consolidated") or "").lower()
        basis = "standalone" if ("non" in cons or "standalone" in cons) else "consolidated"
        out.append({"end": end.isoformat(), "basis": basis, "filed": filed, "xbrl": url,
                    "audited": r.get("audited"), "revised": revised, "source": source})
    return out


def pick(filings, basis="consolidated", quarters=4):
    """The filing to read for each quarter end, latest quarters first: the wanted basis,
    the latest filing of a quarter (a revision wins), the other basis only as a fallback.
    Also returns the year-ago and previous quarter ends the comparisons need."""
    best = {}
    for f in filings:
        cur = best.get(f["end"])
        rank = (f["basis"] == basis, f["filed"])
        if cur is None or rank > (cur["basis"] == basis, cur["filed"]):
            best[f["end"]] = f
    ends = sorted(best, reverse=True)
    show = ends[:quarters]
    need = set(show)
    for e in show:
        d = _dt.date.fromisoformat(e)
        for other in ends:
            od = _dt.date.fromisoformat(other)
            if 350 <= (d - od).days <= 380 or 80 <= (d - od).days <= 100:
                need.add(other)
    return show, [best[e] for e in sorted(need, reverse=True)]


# ---------------------------------------------------------------- XBRL

def _local(tag):
    return tag.rsplit("}", 1)[-1]


def parse_xbrl(data):
    """An NSE results XBRL instance -> {"end", "start", "basis", "name", "symbol", "quarter",
    "values": {metric: number}}. Raises FactsError when there is no quarter in it."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise FactsError("the XBRL file is not valid XML: %s" % exc)
    ctx = {}
    for c in root.iter():
        if _local(c.tag) != "context":
            continue
        start = end = None
        seg = False
        for e in c.iter():
            n = _local(e.tag)
            if n == "startDate":
                start = (e.text or "").strip()
            elif n in ("endDate", "instant"):
                end = (e.text or "").strip()
            elif n in ("segment", "explicitMember", "typedMember"):
                seg = True
        ctx[c.get("id")] = (start, end, seg)
    facts = {}
    for el in root:
        name = _local(el.tag)
        if el.get("contextRef") is None:
            continue
        facts.setdefault(name, []).append((el.get("contextRef"), (el.text or "").strip()))

    def text(name):
        for _, v in facts.get(name, []):
            if v:
                return v
        return None
    end = text("DateOfEndOfReportingPeriod")
    if not end:
        durs = [c for c in ctx.values() if c[0] and c[1] and not c[2]]
        if not durs:
            raise FactsError("no reporting period in the XBRL file")
        end = max(c[1] for c in durs)

    def quarter_ctx(cid):
        c = ctx.get(cid)
        if not c or c[2] or not c[0] or c[1] != end:
            return False
        try:
            days = (_dt.date.fromisoformat(c[1]) - _dt.date.fromisoformat(c[0])).days
        except ValueError:
            return False
        return 80 <= days <= 100
    qids = [cid for cid in ctx if quarter_ctx(cid)]
    if not qids:
        raise FactsError("no three-month period ending %s in the XBRL file" % end)
    qids.sort(key=lambda cid: (cid != "OneD", cid))
    values = {}
    for metric, tags in CONCEPTS.items():
        for tag in tags:
            got = None
            for cid in qids:
                for ref, v in facts.get(tag, []):
                    if ref == cid and v not in ("", None):
                        try:
                            got = float(v)
                        except ValueError:
                            continue
                        break
                if got is not None:
                    break
            if got is not None:
                values[metric] = got
                break
    if "revenue" not in values and "net_profit" not in values:
        raise FactsError("no revenue or net profit for the quarter ending %s in the XBRL file" % end)
    nature = (text("NatureOfReportStandaloneConsolidated") or "").lower()
    return {"end": end, "start": ctx[qids[0]][0], "basis": "standalone" if "standalone" in nature else
            ("consolidated" if "consolidated" in nature else None),
            "name": text("NameOfTheCompany") or text("NameOfCompany"), "symbol": text("Symbol"),
            "quarter": text("ReportingQuarter"), "values": values}


# ---------------------------------------------------------------- analysis

def pct(a, b):
    if a is None or b is None or b == 0:
        return None
    return round(100.0 * (a - b) / abs(b), 1)


def margin(part, whole):
    if part is None or not whole:
        return None
    return round(100.0 * part / whole, 1)


def ebitda(v):
    need = ("pbt", "finance_costs", "depreciation")
    if any(v.get(k) is None for k in need) or v.get("revenue") is None:
        return None
    return v["pbt"] + v["finance_costs"] + v["depreciation"] - (v.get("other_income") or 0.0)


def _match(quarters, end, lo, hi):
    d = _dt.date.fromisoformat(end)
    for e, q in quarters.items():
        if lo <= (d - _dt.date.fromisoformat(e)).days <= hi:
            return q
    return None


def analyse(quarters, show, name=None, basis="consolidated"):
    """{end: parsed XBRL} + the ends to show -> every number in the report."""
    rows = []
    for end in show:
        q = quarters.get(end)
        if not q:
            continue
        v = q["values"]
        rev = v.get("revenue")
        if rev is None:
            rev = v.get("total_income")
        eb = ebitda(v)
        yoy = _match(quarters, end, 350, 380)
        qoq = _match(quarters, end, 80, 100)

        def prior(qq, key):
            if not qq:
                return None
            pv = qq["values"]
            if key == "revenue":
                return pv.get("revenue", pv.get("total_income"))
            return pv.get(key)
        np_ = v.get("net_profit")
        eps = v.get("eps_basic")
        rows.append({
            "end": end, "start": q.get("start"), "quarter": q.get("quarter"),
            "basis": q.get("basis") or q.get("_basis"), "fallback": (q.get("basis") or q.get("_basis")) != basis,
            "revenue": rev, "ebitda": eb, "pbt": v.get("pbt"), "net_profit": np_,
            "owners_profit": v.get("owners_profit"), "eps_basic": round(eps, 2) if eps is not None else None,
            "eps_diluted": round(v["eps_diluted"], 2) if v.get("eps_diluted") is not None else None,
            "ebitda_margin": margin(eb, rev), "net_margin": margin(np_, rev),
            "revenue_yoy": pct(rev, prior(yoy, "revenue")), "net_profit_yoy": pct(np_, prior(yoy, "net_profit")),
            "eps_yoy": pct(eps, prior(yoy, "eps_basic")), "revenue_qoq": pct(rev, prior(qoq, "revenue")),
            "net_profit_qoq": pct(np_, prior(qoq, "net_profit")),
            "filed": q.get("_filed"), "xbrl": q.get("_xbrl"),
        })
    ttm = {}
    ends = sorted(quarters, reverse=True)[:4]
    if len(ends) == 4 and (_dt.date.fromisoformat(ends[0]) - _dt.date.fromisoformat(ends[-1])).days < 300:
        for key, vk in (("revenue", "revenue"), ("net_profit", "net_profit"), ("eps_basic", "eps_basic")):
            vals = [quarters[e]["values"].get(vk) for e in ends]
            if key == "revenue":
                vals = [quarters[e]["values"].get("revenue", quarters[e]["values"].get("total_income")) for e in ends]
            if all(x is not None for x in vals):
                ttm[key] = round(sum(vals), 2)
    first = quarters.get(show[0]) if show else None
    return {"entity": name or (first or {}).get("name"), "basis": basis, "rows": rows, "ttm": ttm}


def cr(v):
    """Rupees -> "12,826.0 cr"-style crore figure (one decimal)."""
    if v is None:
        return "-"
    c = v / CRORE
    s = "%.1f" % abs(c)
    whole, frac = s.split(".")
    from_right = whole[-3:]
    rest = whole[:-3]
    parts = []
    while len(rest) > 2:
        parts.insert(0, rest[-2:])
        rest = rest[:-2]
    if rest:
        parts.insert(0, rest)
    return ("-" if c < 0 else "") + ",".join(parts + [from_right]) + "." + frac


def changes(result):
    """Plain sentences: what changed in the latest quarter."""
    rows = result["rows"]
    if not rows:
        return []
    cur = rows[0]
    prev = rows[1] if len(rows) > 1 else None
    out = []
    line = "Quarter ending %s (%s%s): revenue ₹%s cr" % (
        cur["end"], cur["basis"] or "basis not stated", ", the other basis was not filed" if cur["fallback"] else "",
        cr(cur["revenue"]))
    if cur["revenue_yoy"] is not None:
        line += " (%+.1f%% vs a year earlier)" % cur["revenue_yoy"]
    line += ", net profit ₹%s cr" % cr(cur["net_profit"])
    if cur["net_profit_yoy"] is not None:
        line += " (%+.1f%%)" % cur["net_profit_yoy"]
    if cur["eps_basic"] is not None:
        line += ", basic EPS ₹%.2f" % cur["eps_basic"]
        if cur["eps_yoy"] is not None:
            line += " (%+.1f%%)" % cur["eps_yoy"]
    out.append(line + ".")
    for key, label in (("ebitda_margin", "EBITDA margin"), ("net_margin", "Net margin")):
        if cur[key] is None:
            continue
        s = "%s %.1f%%" % (label, cur[key])
        if prev and prev[key] is not None:
            s += " (%+.1f points vs the quarter before)" % (cur[key] - prev[key])
        out.append(s + ".")
    if cur["owners_profit"] is not None and cur["net_profit"] and cur["basis"] == "consolidated":
        share = 100.0 * cur["owners_profit"] / cur["net_profit"]
        if share < 95:
            out.append("Owners of the company keep %.0f%% of the net profit (₹%s cr); the rest belongs to "
                       "minority shareholders of subsidiaries." % (share, cr(cur["owners_profit"])))
    if cur["revenue_qoq"] is not None:
        out.append("Revenue %+.1f%% vs the quarter before (many businesses are seasonal: compare with a year "
                   "earlier first)." % cur["revenue_qoq"])
    return out


# ---------------------------------------------------------------- output

def _p(v):
    return "-" if v is None else "%+.1f%%" % v


def _pm(v):
    return "-" if v is None else "%.1f%%" % v


def render(symbol, result):
    out = ["%s (NSE: %s), %s results. ₹ crore except EPS. Source: NSE results filings (XBRL)." % (
        result["entity"] or symbol, symbol, result["basis"]), ""]
    out.append("%-11s %-6s %11s %8s %7s %7s %11s %8s %8s %8s" % (
        "quarter end", "basis", "revenue", "rev yoy", "EBITDA", "net", "net profit", "NP yoy", "EPS", "EPS yoy"))
    for r in result["rows"]:
        out.append("%-11s %-6s %11s %8s %7s %7s %11s %8s %8s %8s" % (
            r["end"], (r["basis"] or "?")[:6], cr(r["revenue"]), _p(r["revenue_yoy"]), _pm(r["ebitda_margin"]),
            _pm(r["net_margin"]), cr(r["net_profit"]), _p(r["net_profit_yoy"]),
            "-" if r["eps_basic"] is None else "%.2f" % r["eps_basic"], _p(r["eps_yoy"])))
    t = result["ttm"]
    if t:
        out.append("")
        out.append("Last 4 quarters: revenue ₹%s cr, net profit ₹%s cr, basic EPS %s." % (
            cr(t.get("revenue")), cr(t.get("net_profit")),
            "₹%.2f" % t["eps_basic"] if t.get("eps_basic") is not None else "-"))
    out.append("")
    out.append("What changed:")
    for line in changes(result):
        out.append("  - " + line)
    if result["rows"] and result["rows"][0].get("xbrl"):
        r = result["rows"][0]
        out.append("")
        out.append("Latest filing: quarter ending %s, filed %s  %s" % (r["end"], r["filed"] or "?", r["xbrl"]))
    out.append("EBITDA is worked out (profit before tax + finance costs + depreciation - other income), "
               "not a filed number.")
    return "\n".join(out) + "\n"


def metrics_row(symbol, result):
    rows = result["rows"]
    cur = rows[0] if rows else {}
    t = result["ttm"]
    return {"ticker": symbol, "name": result["entity"], "exchange": "NSE", "basis": result["basis"],
            "period_end": cur.get("end"), "revenue_ttm": t.get("revenue"), "net_profit_ttm": t.get("net_profit"),
            "eps_ttm": t.get("eps_basic"), "revenue_growth_yoy": cur.get("revenue_yoy"),
            "eps_growth_yoy": cur.get("eps_yoy"), "net_profit_growth_yoy": cur.get("net_profit_yoy"),
            "ebitda_margin": cur.get("ebitda_margin"), "net_margin": cur.get("net_margin"),
            "currency": "INR", "source": "NSE results filings (XBRL)"}


def report_for(fetcher, symbol, quarters=4, basis="consolidated"):
    q = urllib.parse.quote(symbol, safe="")
    filings = filings_from(fetcher.json(LIST_URL % q, "nse-results-%s.json" % symbol), "integrated")
    try:
        legacy = filings_from(fetcher.json(LEGACY_URL % q, "nse-results-legacy-%s.json" % symbol), "legacy")
    except FactsError:
        legacy = []
    have = {(f["end"], f["basis"]) for f in filings}
    filings += [f for f in legacy if (f["end"], f["basis"]) not in have]
    if not filings:
        raise FactsError("NSE lists no quarterly results with XBRL for %s (check the symbol)" % symbol)
    show, read = pick(filings, basis, quarters)
    parsed, notes = {}, []
    for f in read:
        try:
            doc = parse_xbrl(fetcher.get(f["xbrl"], f["xbrl"].split("/")[-1]))
        except FactsError as exc:
            notes.append("quarter ending %s: %s" % (f["end"], exc))
            continue
        doc["_basis"], doc["_filed"], doc["_xbrl"] = f["basis"], f["filed"], f["xbrl"]
        parsed[doc["end"]] = doc
    if not parsed:
        raise FactsError("none of the XBRL filings could be read: %s" % "; ".join(notes))
    result = analyse(parsed, [e for e in show if e in parsed], basis=basis)
    result["notes"] = notes
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("tickers", nargs="*", help="NSE symbols, e.g. RELIANCE TCS")
    ap.add_argument("--quarters", type=int, default=4)
    ap.add_argument("--standalone", action="store_true", help="the listed company alone, not the group")
    ap.add_argument("--metrics", metavar="FILE", help="merge a row per symbol into this JSON")
    ap.add_argument("--offline", metavar="DIR")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if not args.tickers:
        ap.print_help()
        return 2
    basis = "standalone" if args.standalone else "consolidated"
    fetcher = Fetcher(offline=args.offline)
    results, rows, failed = [], [], 0
    for t in args.tickers:
        sym = t.strip().upper()
        if sym.endswith(".NS"):
            sym = sym[:-3]
        try:
            result = report_for(fetcher, sym, args.quarters, basis)
        except FactsError as exc:
            print("facts: %s: %s" % (sym, exc), file=sys.stderr)
            failed += 1
            continue
        results.append({"ticker": sym, "result": result, "changes": changes(result)})
        rows.append(metrics_row(sym, result))
        if not args.json:
            sys.stdout.write(render(sym, result))
            for n in result.get("notes") or []:
                sys.stdout.write("note: %s\n" % n)
            sys.stdout.write("\n")
    if args.json:
        print(json.dumps(results, indent=2))
    if args.metrics and rows:
        existing = {}
        if os.path.isfile(args.metrics):
            with open(args.metrics, encoding="utf-8") as fh:
                existing = {r["ticker"]: r for r in json.load(fh).get("companies", [])}
        for r in rows:
            existing[r["ticker"]] = r
        folder = os.path.dirname(args.metrics)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(args.metrics, "w", encoding="utf-8") as fh:
            json.dump({"as_of": _dt.date.today().isoformat(),
                       "companies": sorted(existing.values(), key=lambda r: r["ticker"])}, fh, indent=2)
            fh.write("\n")
        if not args.json:
            print("wrote %s (%d companies)" % (args.metrics, len(existing)))
    return 0 if results and not failed else (1 if results else 2)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Builds the NSE test fixtures. Standard library only, deterministic.

    python3 tests/fixtures/make_nse_fixtures.py

The tests run offline, so they cannot fetch live NSE data. These fixtures are
SYNTHETIC: price paths drawn from a seeded random walk with an intraday
U-shaped volatility, laid on the real NSE calendar (IST timestamps, 75
five-minute bars from 9:15 to 15:30, the 2026 holidays skipped) and written in
the exact shape Yahoo's v8 chart / spark endpoints return for SYMBOL.NS (the
shape was checked against live RELIANCE.NS answers on 2026-11-06). The numbers
are not real prices. The NSE announcement, insider-trading (PIT), deal and
results fixtures keep the field names of the live NSE JSON and XBRL (checked
on 2026-11-06) but describe a FICTIONAL company, SAMPLECO ("Sample Industries
Limited"), and fictional people: no real company's results and no real
person's trades are made up here.

Re-running this script rewrites the files byte for byte the same.
"""

import datetime
import gzip
import json
import math
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))
IST = datetime.timedelta(hours=5, minutes=30)
EPOCH = datetime.datetime(1970, 1, 1)
BARS = 75
HOLIDAYS = {"2026-01-15", "2026-01-26", "2026-03-03", "2026-03-26", "2026-03-31", "2026-04-03", "2026-04-14",
            "2026-05-01", "2026-05-28", "2026-06-26", "2026-09-14", "2026-10-02", "2026-10-20", "2026-11-10",
            "2026-11-24", "2026-12-25"}

# symbol: (seed, price around, daily volume, long name)
STOCKS = {
    "RELIANCE": (11, 990.0, 9000000, "Reliance Industries Limited"),
    "TCS": (12, 3050.0, 2500000, "Tata Consultancy Services Limited"),
    "INFY": (13, 1480.0, 6000000, "Infosys Limited"),
    "HDFCBANK": (14, 990.0, 14000000, "HDFC Bank Limited"),
    "SBIN": (15, 812.0, 11000000, "State Bank of India"),
    "TATAMOTORS": (16, 690.0, 12000000, "Tata Motors Limited"),
    "ITC": (17, 412.0, 15000000, "ITC Limited"),
    "M&M": (18, 3240.0, 2200000, "Mahindra & Mahindra Limited"),
    "BAJAJ-AUTO": (19, 8750.0, 400000, "Bajaj Auto Limited"),
    "IDEA": (20, 9.8, 400000000, "Vodafone Idea Limited"),
}


def tick_size(p):
    if p < 250:
        return 0.01
    for top, tick in ((1000, 0.05), (5000, 0.10), (10000, 0.50), (20000, 1.00)):
        if p <= top:
            return tick
    return 5.00


def on_tick(p):
    t = tick_size(p)
    return round(round(p / t) * t, 2)


def trading_days(end, n):
    """The n NSE trading days up to and including end, oldest first."""
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5 and d.isoformat() not in HOLIDAYS:
            out.append(d)
        d -= datetime.timedelta(days=1)
    return out[::-1]


def bar_ts(day, i):
    """UTC epoch seconds of bar i's start on an IST trading day (bar 0 = 9:15 IST)."""
    start = datetime.datetime.combine(day, datetime.time(9, 15)) - IST + datetime.timedelta(minutes=5 * i)
    return int((start - EPOCH).total_seconds())


def session(rng, prev_close, vol_day):
    """75 bars of (o, h, l, c, v) from a seeded walk with a U-shaped intraday volatility."""
    rows = []
    p = prev_close * (1 + rng.gauss(0, 0.004))
    for i in range(BARS):
        x = i / (BARS - 1.0)
        sigma = 0.0011 * (1.0 + 1.6 * math.exp(-x * 9) + 0.5 * math.exp((x - 1) * 12))
        o = p
        c = o * (1 + rng.gauss(0, sigma))
        h = max(o, c) * (1 + abs(rng.gauss(0, sigma * 0.6)))
        lo = min(o, c) * (1 - abs(rng.gauss(0, sigma * 0.6)))
        shape = 1.0 + 2.2 * math.exp(-x * 7) + 1.2 * math.exp((x - 1) * 9)
        v = int(vol_day / BARS * shape / 1.55 * math.exp(rng.gauss(0, 0.35)))
        rows.append([on_tick(o), on_tick(h), on_tick(lo), on_tick(c), v])
        p = c
    for r in rows:
        r[1] = max(r[1], r[0], r[3])
        r[2] = min(r[2], r[0], r[3])
    return rows


def orb_day(rows, entry_bar=7, push=0.0015):
    """Make the session an opening-range breakout: bars 3..entry_bar-1 stay inside the
    15-minute range, and bar entry_bar is the first 5-minute close above its high."""
    oh = max(r[1] for r in rows[:3])
    ol = min(r[2] for r in rows[:3])
    mid = (oh + ol) / 2
    for i in range(3, entry_bar):
        o = rows[i - 1][3]
        c = on_tick(mid + (oh - mid) * (0.2 + 0.1 * (i % 3)))
        rows[i] = [o, on_tick(max(o, c) + tick_size(c)), on_tick(min(o, c) - tick_size(c)), c, rows[i][4]]
        rows[i][1] = min(rows[i][1], on_tick(oh - tick_size(oh)))
        rows[i][1] = max(rows[i][1], rows[i][0], rows[i][3])
    o = rows[entry_bar - 1][3]
    c = on_tick(oh * (1 + push))
    rows[entry_bar] = [o, on_tick(c * 1.0006), on_tick(o - tick_size(o)), c, int(rows[entry_bar][4] * 1.8)]
    # carry the rest of the day from the breakout close
    shift = c / rows[entry_bar + 1][0]
    for i in range(entry_bar + 1, BARS):
        rows[i] = [on_tick(x * shift) for x in rows[i][:4]] + [rows[i][4]]
        rows[i][1] = max(rows[i][1], rows[i][0], rows[i][3])
        rows[i][2] = min(rows[i][2], rows[i][0], rows[i][3])
    return oh, ol


def history(sym, end, n=61, orb_on=None):
    """{date: rows} for the n trading days up to end. orb_on: a date made into an ORB day."""
    seed, base, vol, _ = STOCKS[sym]
    rng = random.Random(seed)
    out, prev = {}, base
    for d in trading_days(end, n):
        rows = session(rng, prev, vol)
        if orb_on and d == orb_on:
            orb_day(rows)
        out[d] = rows
        prev = rows[-1][3]
    return out


def chart_doc(sym, days, now_utc, rng_label, live_tick=True):
    """Yahoo v8 chart JSON for SYMBOL.NS: every bar that has started by now_utc, plus
    (live_tick) the in-progress tick off the 5-minute grid, as Yahoo sends it."""
    seed, base, vol, name = STOCKS[sym]
    ts, cols = [], [[], [], [], [], []]
    last = None
    for d in sorted(days):
        for i, r in enumerate(days[d]):
            t = bar_ts(d, i)
            if EPOCH + datetime.timedelta(seconds=t) > now_utc:
                break
            ts.append(t)
            for k in range(5):
                cols[k].append(r[k])
            last = (d, i, r)
    now_s = int((now_utc - EPOCH).total_seconds())
    d, i, r = last
    open_bar = EPOCH + datetime.timedelta(seconds=bar_ts(d, i)) + datetime.timedelta(minutes=5) > now_utc
    if live_tick and open_bar and now_s % 300:
        ts.append(now_s)
        for k, v in enumerate([r[3], r[3], r[3], r[3], 0]):
            cols[k].append(v)
    day_rows = days[max(days)]
    prev_close = days[sorted(days)[-2]][-1][3] if len(days) > 1 else base
    upto = [x for j, x in enumerate(day_rows) if EPOCH + datetime.timedelta(seconds=bar_ts(max(days), j)) <= now_utc]
    meta = {
        "currency": "INR", "symbol": sym + ".NS", "exchangeName": "NSI", "fullExchangeName": "NSE",
        "instrumentType": "EQUITY", "regularMarketTime": now_s if open_bar else bar_ts(d, i) + 300,
        "hasPrePostMarketData": False, "gmtoffset": 19800, "timezone": "IST",
        "exchangeTimezoneName": "Asia/Kolkata", "regularMarketPrice": r[3],
        "regularMarketDayHigh": max(x[1] for x in upto) if upto else r[1],
        "regularMarketDayLow": min(x[2] for x in upto) if upto else r[2],
        "regularMarketVolume": sum(x[4] for x in upto), "longName": name, "shortName": name,
        "chartPreviousClose": prev_close, "previousClose": prev_close, "priceHint": 2,
        "dataGranularity": "5m", "range": rng_label,
    }
    return {"chart": {"result": [{"meta": meta, "timestamp": ts,
                                  "indicators": {"quote": [{"open": cols[0], "high": cols[1], "low": cols[2],
                                                            "close": cols[3], "volume": cols[4]}]}}],
                      "error": None}}


def write(rel, doc, gz=False):
    path = os.path.join(HERE, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    text = json.dumps(doc, separators=(",", ":"), sort_keys=False)
    if gz:
        with open(path, "wb") as fh:
            with gzip.GzipFile(fileobj=fh, mode="wb", mtime=0, filename="") as g:
                g.write(text.encode("utf-8"))
    else:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    return path


def utc(local):
    return local - IST


PLAN_DAY = datetime.date(2026, 11, 5)          # a Thursday
NOW_PLAN = utc(datetime.datetime(2026, 11, 5, 10, 29, 45))   # 10:29:45 IST, the live tick


def main():
    rel = history("RELIANCE", PLAN_DAY, n=61, orb_on=PLAN_DAY)
    # one gap day in the pool: a session with missing bars is left out of the pool
    gap = trading_days(PLAN_DAY, 30)[0]
    rel_gap = dict(rel)
    rel_gap[gap] = rel[gap][:60]
    write("trader-timemachine/RELIANCE-60d5m.json.gz",
          chart_doc("RELIANCE", {d: r for d, r in rel_gap.items() if d != min(rel_gap)}, NOW_PLAN, "60d"), gz=True)
    write("trader-entry/RELIANCE-2026-11-05-5m.json", chart_doc("RELIANCE", {PLAN_DAY: rel[PLAN_DAY]}, NOW_PLAN, "1d"))
    # the whole day, after the close, for the exit planner's ATR and for alerts
    write("trader-entry/RELIANCE-2026-11-05-5m-close.json",
          chart_doc("RELIANCE", {PLAN_DAY: rel[PLAN_DAY]}, utc(datetime.datetime(2026, 11, 5, 15, 45)), "1d",
                    live_tick=False))
    oh = max(r[1] for r in rel[PLAN_DAY][:3])
    ol = min(r[2] for r in rel[PLAN_DAY][:3])
    print("RELIANCE %s opening range %.2f-%.2f, bar 7 close %.2f" % (PLAN_DAY, oh, ol, rel[PLAN_DAY][7][3]))


# ---------------------------------------------------------------- news, results, insider (fictional SAMPLECO)

SAMPLE = "SAMPLECO"
SAMPLE_NAME = "Sample Industries Limited"


def announcements():
    """corporate-announcements JSON, the live field names, a fictional company."""
    rows = [
        ("05-Nov-2026 19:42:10", "Outcome of Board Meeting", "Sample Industries Limited has informed the Exchange "
         "about the outcome of the Board meeting held on November 05, 2026: approved the financial results for the "
         "quarter ended September 30, 2026", "106900001"),
        ("05-Nov-2026 11:05:33", "Credit Rating", "Sample Industries Limited has informed the Exchange about Credit "
         "Rating", "106900002"),
        ("04-Nov-2026 18:20:00", "Analysts/Institutional Investor Meet/Con. Call Updates", "Sample Industries "
         "Limited has informed the Exchange about the schedule of an analyst meet", "106900003"),
        ("02-Nov-2026 09:12:45", "Acquisition", "Sample Industries Limited has informed the Exchange about the "
         "acquisition of a 51% stake in Example Logistics Private Limited", "106900004"),
        ("20-Oct-2026 16:00:00", "Trading Window-xbrl", "Sample Industries Limited has informed the Exchange about "
         "the closure of the trading window", "106900005"),
    ]
    return [{"an_dt": a, "attFileSize": "120.00 KB",
             "attchmntFile": "https://nsearchives.nseindia.com/corporate/SAMPLECO_%s.pdf" % s,
             "attchmntText": txt, "bflag": None, "csvName": None, "desc": d, "difference": "00:00:01",
             "dt": a.replace("-", "").replace(":", "").replace(" ", ""), "exchdisstime": a, "fileSize": "120.00 KB",
             "hasXbrl": True, "old_new": None, "orgid": None, "seq_id": s, "smIndustry": "Diversified",
             "sm_isin": "INE000S01010", "sm_name": SAMPLE_NAME, "sort_date": a, "symbol": SAMPLE}
            for a, d, txt, s in rows]


def rss():
    items = [
        ("Sample Industries Q2 profit rises 12% on retail and energy (SAMPLECO)", "Thu, 05 Nov 2026 14:30:00 +0000",
         "https://example.com/news/sampleco-q2"),
        ("Brokerages raise target price on Sample Industries after results", "Thu, 05 Nov 2026 16:10:00 +0000",
         "https://example.com/news/sampleco-target"),
        ("RBI keeps repo rate unchanged; GIFT Nifty flat", "Wed, 04 Nov 2026 06:00:00 +0000",
         "https://example.com/news/rbi-policy"),
    ]
    body = "".join("<item><title>%s</title><link>%s</link><guid>%s</guid><pubDate>%s</pubDate>"
                   "<description>%s</description></item>" % (ti, li, li, pd, ti) for ti, pd, li in items)
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><rss version="2.0"><channel>'
            "<title>Yahoo! Finance: SAMPLECO.NS News</title>%s</channel></rss>" % body)


QUARTERS = [  # end, revenue, other income, finance, depreciation, PBT, net profit, owners, EPS (₹ crore / ₹)
    ("2024-09-30", 61200, 1450, 3020, 4110, 10950, 8120, 7310, 10.80),
    ("2024-12-31", 64800, 1510, 3100, 4180, 11800, 8790, 7900, 11.67),
    ("2025-03-31", 66100, 1620, 3150, 4260, 12340, 9150, 8240, 12.17),
    ("2025-06-30", 63900, 1380, 3210, 4300, 11410, 8480, 7640, 11.28),
    ("2025-09-30", 65700, 1490, 3260, 4390, 11920, 8860, 7980, 11.79),
    ("2025-12-31", 69400, 1530, 3300, 4450, 12780, 9520, 8570, 12.66),
    ("2026-03-31", 70900, 1700, 3330, 4520, 13440, 9990, 9010, 13.31),
    ("2026-06-30", 68300, 1460, 3370, 4580, 12350, 9180, 8270, 12.21),
    ("2026-09-30", 72600, 1580, 3410, 4650, 13660, 9930, 8940, 13.21),
]


def quarter_start(d):
    """The first day of the quarter that ends on d (a month end)."""
    m = d.month - 2
    return datetime.date(d.year if m > 0 else d.year - 1, m if m > 0 else m + 12, 1)


def xbrl(end, rev, oi, fin, dep, pbt, npf, own, eps, basis="Consolidated", scale=1.0):
    d = datetime.date.fromisoformat(end)
    start = quarter_start(d)
    fy_start = datetime.date(d.year if d.month > 3 else d.year - 1, 4, 1)
    cr = 1e7
    expenses = (rev + oi - pbt)
    facts = [
        ("Symbol", SAMPLE, None), ("NameOfTheCompany", SAMPLE_NAME, None),
        ("ReportingQuarter", {3: "Fourth quarter", 6: "First quarter", 9: "Second quarter", 12: "Third quarter"}[d.month], None),
        ("DateOfStartOfReportingPeriod", start.isoformat(), None), ("DateOfEndOfReportingPeriod", end, None),
        ("NatureOfReportStandaloneConsolidated", basis, None),
        ("RevenueFromOperations", rev * scale, "INR"), ("OtherIncome", oi * scale, "INR"),
        ("Income", (rev + oi) * scale, "INR"), ("FinanceCosts", fin * scale, "INR"),
        ("DepreciationDepletionAndAmortisationExpense", dep * scale, "INR"), ("Expenses", expenses * scale, "INR"),
        ("ProfitBeforeTax", pbt * scale, "INR"), ("ProfitLossForPeriod", npf * scale, "INR"),
        ("ProfitOrLossAttributableToOwnersOfParent", own * scale, "INR"),
        ("BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations", round(eps * scale, 2), "EPS"),
        ("DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations", round(eps * scale, 2), "EPS"),
    ]
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" '
           'xmlns:xbrldi="http://xbrl.org/2006/xbrldi" xmlns:iso4217="http://www.xbrl.org/2003/iso4217" '
           'xmlns:in-capmkt="http://www.sebi.gov.in/xbrl/2026-01-31/in-capmkt">',
           '<xbrli:context id="OneD"><xbrli:entity><xbrli:identifier scheme="http://www.nseindia.com">%s'
           '</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:startDate>%s</xbrli:startDate><xbrli:endDate>%s'
           '</xbrli:endDate></xbrli:period></xbrli:context>' % (SAMPLE, start.isoformat(), end),
           '<xbrli:context id="FourD"><xbrli:entity><xbrli:identifier scheme="http://www.nseindia.com">%s'
           '</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:startDate>%s</xbrli:startDate><xbrli:endDate>%s'
           '</xbrli:endDate></xbrli:period></xbrli:context>' % (SAMPLE, fy_start.isoformat(), end),
           '<xbrli:context id="OneOtherExpensesD"><xbrli:entity><xbrli:identifier scheme="http://www.nseindia.com">'
           '%s</xbrli:identifier><xbrli:segment><xbrldi:explicitMember dimension="in-capmkt:OtherExpensesAxis">'
           'in-capmkt:OtherExpenses1Member</xbrldi:explicitMember></xbrli:segment></xbrli:entity><xbrli:period>'
           '<xbrli:startDate>%s</xbrli:startDate><xbrli:endDate>%s</xbrli:endDate></xbrli:period></xbrli:context>'
           % (SAMPLE, start.isoformat(), end),
           '<xbrli:unit id="INR"><xbrli:measure>iso4217:INR</xbrli:measure></xbrli:unit>',
           '<xbrli:unit id="EPS"><xbrli:divide><xbrli:unitNumerator><xbrli:measure>iso4217:INR</xbrli:measure>'
           '</xbrli:unitNumerator><xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure>'
           '</xbrli:unitDenominator></xbrli:divide></xbrli:unit>']
    for name, val, unit in facts:
        if unit == "INR":
            out.append('<in-capmkt:%s contextRef="OneD" unitRef="INR" decimals="-5">%d</in-capmkt:%s>'
                       % (name, round(val * cr), name))
            # the year to date, in the FourD context, a bigger number the reader must ignore
            out.append('<in-capmkt:%s contextRef="FourD" unitRef="INR" decimals="-5">%d</in-capmkt:%s>'
                       % (name, round(val * cr * 2.02), name))
        elif unit == "EPS":
            out.append('<in-capmkt:%s contextRef="OneD" unitRef="EPS" decimals="2">%.2f</in-capmkt:%s>'
                       % (name, val, name))
        else:
            out.append('<in-capmkt:%s contextRef="OneD">%s</in-capmkt:%s>' % (name, val, name))
    out.append('<in-capmkt:OtherExpenses contextRef="OneOtherExpensesD" unitRef="INR" decimals="-5">%d'
               '</in-capmkt:OtherExpenses>' % round(999 * cr))
    out.append("</xbrli:xbrl>")
    return "\n".join(out)


def results():
    """integrated-filing-results (since 2025) and the legacy list (2024), with their XBRL files."""
    integrated, legacy, files = [], [], {}
    for i, q in enumerate(QUARTERS):
        end = datetime.date.fromisoformat(q[0])
        filed = end + datetime.timedelta(days=36)
        stamp = filed.strftime("%d-%b-%Y") + " 19:30:00"
        name = "INTEGRATED_FILING_INDAS_9%05d_%s_WEB.xml" % (i, filed.strftime("%d%m%Y"))
        if end.year < 2025:
            name = "INDAS_8%05d_%s.xml" % (i, filed.strftime("%d%m%Y"))
            legacy.append({"audited": "Un-Audited", "bank": "N", "broadCastDate": stamp, "companyName": SAMPLE_NAME,
                           "consolidated": "Consolidated", "cumulative": "Non-cumulative", "filingDate": stamp[:17],
                           "fromDate": quarter_start(end).strftime("%d-%b-%Y"), "toDate": end.strftime("%d-%b-%Y"), "period": "Quarterly",
                           "relatingTo": "-", "symbol": SAMPLE,
                           "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/" + name})
        else:
            integrated.append({"attFileSize": "0 Bytes", "audited": "Un-Audited", "broadcast_Date": stamp,
                               "cmName": SAMPLE_NAME, "consolidated": "Consolidated", "creation_Date": stamp,
                               "diff": "00:00:00", "ixbrl": name.replace(".xml", "_iXBRL.html"),
                               "pdf_attach": None, "qe_Date": end.strftime("%d-%b-%Y").upper(), "revised_Date": None,
                               "revision_Remark": None, "seq_Id": str(207000 + i), "smName": SAMPLE_NAME,
                               "symbol": SAMPLE, "type": "Integrated Filing- Financials", "type_Sub": "Original",
                               "xbrl": "/xbrl/" + name, "xbrlFileSize": "100.00 KB"})
        files[name] = xbrl(*q)
    # a standalone filing of the latest quarter: the default reads the consolidated one
    end = QUARTERS[-1][0]
    sname = "INTEGRATED_FILING_INDAS_STANDALONE_%s_WEB.xml" % end.replace("-", "")
    files[sname] = xbrl(*QUARTERS[-1], basis="Standalone", scale=0.6)
    integrated.append(dict(integrated[-1], consolidated="Standalone", seq_Id="207999", xbrl="/xbrl/" + sname))
    # a revision of 2026-06-30, filed later: it wins over the original
    rq = list(QUARTERS[-2])
    rq[6], rq[7], rq[8] = 9240, 8320, 12.29
    rname = "INTEGRATED_FILING_INDAS_REVISED_20260630_WEB.xml"
    files[rname] = xbrl(*rq)
    integrated.append(dict([r for r in integrated if r["qe_Date"] == "30-JUN-2026"][0], seq_Id="207998",
                           type_Sub="Revised", revised_Date="20-Aug-2026 18:00:00",
                           broadcast_Date="20-Aug-2026 18:00:00", xbrl="/xbrl/" + rname))
    integrated.sort(key=lambda r: r["broadcast_Date"], reverse=True)
    return {"data": integrated, "size": 20, "page": 1, "totalCount": len(integrated)}, legacy, files


def pit():
    """corporates-pit JSON, the live field names, fictional people."""
    def row(did, name, cat, kind, mode, qty, val, traded, told, filed, before, after):
        return {"acqMode": mode, "acqName": name, "acqfromDt": traded, "acqtoDt": traded,
                "afterAcqSharesNo": "0", "afterAcqSharesPer": after, "anex": "7(2)", "befAcqSharesNo": "0",
                "befAcqSharesPer": before, "buyQuantity": qty if kind == "Buy" else "0",
                "buyValue": val if kind == "Buy" else "0", "company": SAMPLE_NAME, "date": filed,
                "derivativeType": "-", "did": did, "exchange": "NSE", "intimDt": told, "personCategory": cat,
                "pid": str(int(did) + 500000), "remarks": "-", "secAcq": qty, "secType": "Equity Shares",
                "secVal": val, "securitiesTypePost": "Equity Shares", "sellValue": val if kind == "Sell" else "0",
                "sellquantity": qty if kind == "Sell" else "0", "symbol": SAMPLE, "tdpDerivativeContractType": "-",
                "tdpTransactionType": kind, "tkdAcqm": None,
                "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/IT_%s_WEB.xml" % did, "xbrlFileSize": None}
    data = [
        row("600001", "ASHA EXAMPLE", "Promoter Group", "Buy", "Market Purchase", "150000", "198750000",
            "02-Nov-2026", "03-Nov-2026", "03-Nov-2026 18:10", "0.85", "0.87"),
        row("600002", "RAVI SAMPLE", "Director", "Sell", "Market Sale", "20000", "26900000",
            "21-Oct-2026", "28-Oct-2026", "28-Oct-2026 20:02", "0.05", "0.03"),
        row("600003", "TEST HOLDINGS PRIVATE LIMITED", "Promoters", "Pledge Creation", "Off Market", "500000",
            "0", "15-Oct-2026", "16-Oct-2026", "16-Oct-2026 17:45", "12.40", "12.40"),
        row("600004", "MEERA PLACEHOLDER", "Designated Employees", "Buy", "ESOP", "4000", "5200000",
            "10-Oct-2026", "12-Oct-2026", "12-Oct-2026 12:00", "0", "0"),
        row("600005", "KARAN DEMO", "Key Managerial Personnel", "Buy", "Market Purchase", "8000", "10480000",
            "15-Sep-2026", "16-Sep-2026", "16-Sep-2026 19:30", "0.01", "0.01"),
    ]
    return {"acqNameList": sorted({r["acqName"] for r in data}), "data": data}


def largedeal():
    def d(side, client, date, name, qty, sym, price):
        return {"buySell": side, "clientName": client, "date": date, "name": name, "qty": qty, "remarks": "-",
                "symbol": sym, "watp": price}
    return {"as_on_date": "05-Nov-2026",
            "BULK_DEALS_DATA": [d("BUY", "EXAMPLE CAPITAL FUND", "05-Nov-2026", SAMPLE_NAME, "2500000", SAMPLE,
                                  "1342.5"),
                                d("SELL", "PLACEHOLDER TRADING LLP", "05-Nov-2026", "Other Example Ltd", "900000",
                                  "OTHEREX", "212.4")],
            "BULK_DEALS": "2", "SHORT_DEALS_DATA": [], "SHORT_DEALS": "0",
            "BLOCK_DEALS_DATA": [d("BUY", "DEMO MUTUAL FUND", "05-Nov-2026", SAMPLE_NAME, "1000000", SAMPLE,
                                   "1339.0")],
            "BLOCK_DEALS": "1"}


def write_text(rel, text):
    path = os.path.join(HERE, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def main_data():
    write("trader-news/nse-ann-%s.json" % SAMPLE, announcements())
    write_text("trader-news/yahoo-%s.xml" % SAMPLE, rss())
    STOCKS[SAMPLE] = (21, 1180.0, 3000000, SAMPLE_NAME)
    s = history(SAMPLE, PLAN_DAY, n=2)
    write("trader-news/chart-%s.json" % SAMPLE, chart_doc(SAMPLE, {PLAN_DAY: s[PLAN_DAY], min(s): s[min(s)]},
                                                          utc(datetime.datetime(2026, 11, 5, 15, 45)), "1d",
                                                          live_tick=False))
    integ, legacy, files = results()
    write("trader-analyst/nse-results-%s.json" % SAMPLE, integ)
    write("trader-analyst/nse-results-legacy-%s.json" % SAMPLE, legacy)
    for name, text in files.items():
        write_text("trader-analyst/" + name, text)
    write("trader-insider/nse-pit-%s.json" % SAMPLE, pit())
    write("trader-insider/nse-largedeal.json", largedeal())


# ---------------------------------------------------------------- scanner, alerts, entry (synthetic prices)

EQUITY_L = """SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE
3MINDIA,3M India Limited,EQ,13-AUG-2004,10,1,INE470A01017,10
BAJAJ-AUTO,Bajaj Auto Limited,EQ,26-MAY-2008,10,1,INE917I01010,10
HDFCBANK,HDFC Bank Limited,EQ,08-NOV-1995,1,1,INE040A01034,1
IDEA,Vodafone Idea Limited,EQ,09-MAR-2007,10,1,INE669E01016,10
INFY,Infosys Limited,EQ,08-FEB-1995,5,1,INE009A01021,5
ITC,ITC Limited,EQ,23-AUG-1995,1,1,INE154A01025,1
M&M,Mahindra & Mahindra Limited,EQ,17-NOV-1995,5,1,INE101A01026,5
RELIANCE,Reliance Industries Limited,EQ,29-NOV-1995,10,1,INE002A01018,10
SBIN,State Bank of India,EQ,01-MAR-1995,1,1,INE062A01020,1
TATAMOTORS,Tata Motors Limited,EQ,22-JUL-1998,2,1,INE155A01022,2
TCS,Tata Consultancy Services Limited,EQ,25-AUG-2004,1,1,INE467B01029,1
EXAMPLEBE,Example Trade For Trade Limited,BE,01-JAN-2010,10,1,INE000E01011,10
EXAMPLEBZ,Example Restricted Limited,BZ,01-JAN-2011,10,1,INE000E01029,10
EXAMPLESME,Example SME Limited,SM,01-JAN-2020,10,1,INE000E01037,10
bad sym,Not A Symbol Limited,EQ,01-JAN-2020,10,1,INE000E01045,10
"""
NIFTY500 = """Company Name,Industry,Symbol,Series,ISIN Code
HDFC Bank Ltd.,Financial Services,HDFCBANK,EQ,INE040A01034
Infosys Ltd.,Information Technology,INFY,EQ,INE009A01021
Reliance Industries Ltd.,Oil Gas & Consumable Fuels,RELIANCE,EQ,INE002A01018
Tata Consultancy Services Ltd.,Information Technology,TCS,EQ,INE467B01029
"""
SCAN = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "SBIN", "TATAMOTORS", "ITC", "M&M", "BAJAJ-AUTO", "IDEA"]


def daily_series(sym, end, n=63, shape=None):
    """Daily closes as a spark response: n trading days up to end; shape bends the last days."""
    seed, base, vol, name = STOCKS[sym]
    rng = random.Random(seed * 7)
    days = trading_days(end, n)
    closes, p = [], base
    for i, d in enumerate(days):
        p = p * (1 + rng.gauss(0, 0.012))
        closes.append(p)
    if shape == "breakout":
        top = max(closes[-21:-1])
        closes[-1] = top * 1.02
    elif shape == "oversold":
        for i in range(15):
            closes[-15 + i] = closes[-16] * (1 - 0.012 * (i + 1))
    elif shape == "bounce":
        for i in range(15):
            closes[-16 + i] = closes[-17] * (1 - 0.013 * (i + 1))
        closes[-1] = closes[-2] * 1.01
    elif shape == "flag":
        start = closes[-16]
        for i in range(10):
            closes[-15 + i] = start * (1 + 0.013 * (i + 1))
        for i in range(5):
            closes[-5 + i] = closes[-6] * (1 + (0.004 if i % 2 else -0.004))
    closes = [on_tick(c) for c in closes]
    ts = [bar_ts(d, 0) for d in days]   # Yahoo stamps a daily bar at the session's open
    meta = {"currency": "INR", "symbol": sym + ".NS", "exchangeName": "NSI", "regularMarketPrice": closes[-1],
            "regularMarketVolume": vol, "chartPreviousClose": closes[-2], "dataGranularity": "1d", "range": "3mo",
            "gmtoffset": 19800, "exchangeTimezoneName": "Asia/Kolkata"}
    return {"symbol": sym + ".NS", "response": [{"meta": meta, "timestamp": ts,
                                                  "indicators": {"quote": [{"close": closes}]}}]}


def main_scan():
    write_text("trader-scanner/nse/EQUITY_L.csv", EQUITY_L)
    write_text("trader-scanner/nse/ind_nifty500list.csv", NIFTY500)
    shapes = {"RELIANCE": "breakout", "TCS": "oversold", "INFY": "bounce", "HDFCBANK": "flag", "IDEA": "breakout"}
    write("trader-scanner/daily-spark-2026-11-04.json",
          {"spark": {"result": [daily_series(s, datetime.date(2026, 11, 4), shape=shapes.get(s)) for s in SCAN],
                     "error": None}})
    # the 5-minute wall for 2026-11-05: RELIANCE and SBIN break out, TATAMOTORS has a halt
    # (two missing bars, so its chart is not usable), the rest stay under their range high
    wall, live = {}, utc(datetime.datetime(2026, 11, 5, 10, 29, 45))
    for s in SCAN:
        full = history(s, PLAN_DAY, n=61, orb_on=PLAN_DAY if s in ("RELIANCE", "SBIN") else None)
        days = {d: full[d] for d in sorted(full)[-2:]}
        if s not in ("RELIANCE", "SBIN"):
            day = days[PLAN_DAY]
            oh = max(r[1] for r in day[:3])
            for i in range(3, BARS):
                if day[i][3] >= oh:
                    f = (oh * 0.997) / day[i][3]
                    day[i] = [on_tick(x * f) for x in day[i][:4]] + [day[i][4]]
                    day[i][1] = max(day[i][1], day[i][0], day[i][3])
                    day[i][2] = min(day[i][2], day[i][0], day[i][3])
        doc = chart_doc(s, days, live, "5d")
        if s == "TATAMOTORS":
            r0 = doc["chart"]["result"][0]
            q = r0["indicators"]["quote"][0]
            drop = {bar_ts(PLAN_DAY, 5), bar_ts(PLAN_DAY, 6)}
            idx = [i for i, x in enumerate(r0["timestamp"]) if x not in drop]
            r0["timestamp"] = [r0["timestamp"][i] for i in idx]
            for k in q:
                q[k] = [q[k][i] for i in idx]
        wall[s] = doc
    write("trader-scanner/wall5m-2026-11-05.json.gz", wall, gz=True)


def quote_doc(sym, price, prev, t_utc):
    seed, base, vol, name = STOCKS[sym]
    ts = int((t_utc - EPOCH).total_seconds())
    return {"chart": {"result": [{"meta": {"currency": "INR", "symbol": sym + ".NS", "exchangeName": "NSI",
                                           "regularMarketPrice": price, "regularMarketTime": ts,
                                           "regularMarketDayHigh": on_tick(price * 1.004),
                                           "regularMarketDayLow": on_tick(price * 0.991),
                                           "chartPreviousClose": prev, "previousClose": prev,
                                           "gmtoffset": 19800, "exchangeTimezoneName": "Asia/Kolkata",
                                           "dataGranularity": "1d", "range": "1d"},
                                  "timestamp": [bar_ts(PLAN_DAY, 0)],
                                  "indicators": {"quote": [{"open": [on_tick(prev * 1.001)], "high": [price],
                                                            "low": [price], "close": [price],
                                                            "volume": [vol]}]}}], "error": None}}


def main_alerts():
    t = utc(datetime.datetime(2026, 11, 5, 11, 40))
    for sym, price, prev in (("RELIANCE", 1318.60, 1296.40), ("TCS", 2981.20, 3050.10), ("ITC", 426.85, 412.30),
                             ("M&M", 3251.00, 3240.00)):
        write("trader-alerts/yahoo-%s.json" % sym, quote_doc(sym, price, prev, t))
    write("trader-alerts/yahoo-ZZZZ.json", {"chart": {"result": None, "error": {
        "code": "Not Found", "description": "No data found, symbol may be delisted"}}})
    plan = {"created_by": "trader-exit", "symbol": "RELIANCE", "side": "buy", "date": "2026-11-05", "setup": "orb",
            "entry": 1311.3, "entry_time": "9:55 AM", "entry_bar": 7, "interval": "5m",
            "opening_range": {"high": 1309.3, "low": 1298.9, "minutes": 15}, "stop": 1304.1, "stop_rule": "or_mid",
            "stop_label": "opening-range midpoint", "target": 1318.5, "target_r": 1.0,
            "target_label": "1R (one times the risk)", "risk_per_share": 7.2, "reward_risk": 1.0, "flat_by": "15:10",
            "stop_detail": "(₹1,309.30 + ₹1,298.90) / 2 = ₹1304.1", "created_at": "2026-11-05T04:30:00Z",
            "note": "A stop is a plan, not a guarantee: a gap or a fast market can fill past it."}
    write("trader-budget/plan-reliance.json", plan)
    write("trader-budget/nifty-top5.json", {"source": "an example split, not a recommendation",
                                            "weights": [{"ticker": "RELIANCE", "weight": 25},
                                                        {"ticker": "HDFCBANK", "weight": 20},
                                                        {"ticker": "TCS", "weight": 20},
                                                        {"ticker": "INFY", "weight": 20},
                                                        {"ticker": "ITC", "weight": 15}]})


def main_entry_1m():
    """A one-minute demo day (IST) for the 1m path: a breakout at 9:31 on the 1-minute grid."""
    day = PLAN_DAY
    rows, p = [], 500.0
    rng = random.Random(5)
    for i in range(30):
        o = p
        c = o * (1 + rng.gauss(0, 0.0008))
        rows.append([round(o, 2), round(max(o, c) + 0.05, 2), round(min(o, c) - 0.05, 2), round(c, 2), 10000])
        p = c
    oh = max(r[1] for r in rows[:15])
    rows[16][3] = round(oh + 0.30, 2)
    rows[16][1] = max(rows[16][1], rows[16][3])
    start = datetime.datetime.combine(day, datetime.time(9, 15)) - IST
    ts = [int((start + datetime.timedelta(minutes=i) - EPOCH).total_seconds()) for i in range(len(rows))]
    now = start + datetime.timedelta(minutes=len(rows))
    doc = {"chart": {"result": [{"meta": {"currency": "INR", "symbol": "DEMO.NS", "exchangeName": "NSI",
                                          "regularMarketTime": int((now - EPOCH).total_seconds()),
                                          "regularMarketPrice": rows[-1][3], "gmtoffset": 19800,
                                          "exchangeTimezoneName": "Asia/Kolkata", "dataGranularity": "1m",
                                          "range": "1d", "chartPreviousClose": 499.0},
                                 "timestamp": ts,
                                 "indicators": {"quote": [{"open": [r[0] for r in rows], "high": [r[1] for r in rows],
                                                           "low": [r[2] for r in rows], "close": [r[3] for r in rows],
                                                           "volume": [r[4] for r in rows]}]}}], "error": None}}
    write("trader-entry/DEMO-1m-synthetic.json", doc)


if __name__ == "__main__":
    main()
    main_data()
    main_scan()
    main_alerts()
    main_entry_1m()

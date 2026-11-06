"""trader-scanner tests, NSE edition. Fixtures (synthetic prices, see make_nse_fixtures.py):
a trimmed EQUITY_L.csv and Nifty 500 list, a daily spark answer of 2026-11-04 for ten NSE
symbols, and a 5-minute wall of v8 charts for 2026-11-05 (RELIANCE and SBIN break out,
TATAMOTORS has two missing bars, IDEA is under the ₹50 floor)."""

import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, FIX

scan = load("trader-scanner", "scan")

SDIR = os.path.join(FIX, "trader-scanner")
NSE = os.path.join(SDIR, "nse")
DAILY = os.path.join(SDIR, "daily-spark-2026-11-04.json")
WALL = os.path.join(SDIR, "wall5m-2026-11-05.json.gz")


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = scan.main(argv)
    return code, out.getvalue(), err.getvalue()


def text(name):
    with open(os.path.join(NSE, name), encoding="utf-8") as fh:
        return fh.read()


class Universe(unittest.TestCase):
    def test_eq_series_only(self):
        kept, counts, _ = scan.build_universe({"EQUITY_L.csv": text("EQUITY_L.csv")})
        syms = [s for s, _ in kept]
        self.assertEqual(syms, ["3MINDIA", "BAJAJ-AUTO", "HDFCBANK", "IDEA", "INFY", "ITC", "M&M", "RELIANCE",
                                "SBIN", "TATAMOTORS", "TCS"])
        self.assertEqual(counts["rows"], 15)
        self.assertEqual(counts["series BE (no intraday)"], 1)
        self.assertEqual(counts["series SM (no intraday)"], 1)
        self.assertEqual(counts["not a plain NSE symbol"], 1)
        self.assertEqual(dict(kept)["M&M"], "Mahindra & Mahindra Limited")

    def test_padded_headers_are_read(self):
        rows = scan.parse_nse_csv(text("EQUITY_L.csv"))
        self.assertIn("SERIES", rows[0])
        self.assertEqual(rows[0]["SERIES"], "EQ")

    def test_the_nifty_500_list(self):
        kept, _, _ = scan.build_universe({"ind_nifty500list.csv": text("ind_nifty500list.csv")}, "nifty500")
        self.assertEqual([s for s, _ in kept], ["HDFCBANK", "INFY", "RELIANCE", "TCS"])

    def test_not_an_nse_list(self):
        with self.assertRaises(scan.ScanError):
            scan.parse_nse_csv("Symbol|Security Name\nAAPL|Apple\n")

    def test_cli_universe(self):
        d = tempfile.mkdtemp()
        try:
            out = os.path.join(d, "universe.txt")
            code, text_, _ = run(["universe", "--offline", NSE, "--out", out])
            self.assertEqual(code, 0)
            self.assertIn("Kept 11 EQ-series symbols", text_)
            with open(out) as fh:
                self.assertIn("M&M|Mahindra & Mahindra Limited", fh.read().splitlines())
        finally:
            shutil.rmtree(d)


class YahooSymbols(unittest.TestCase):
    def test_to_and_from_yahoo(self):
        self.assertEqual(scan.to_yahoo("RELIANCE"), "RELIANCE.NS")
        self.assertEqual(scan.from_yahoo("BAJAJ-AUTO.NS"), "BAJAJ-AUTO")
        self.assertEqual(scan.from_yahoo("M&M.NS"), "M&M")

    def test_spark_and_chart_paths(self):
        p = scan.spark_path(["RELIANCE", "M&M", "BAJAJ-AUTO"], "1d", "5m")
        self.assertEqual(p, "/v7/finance/spark?symbols=RELIANCE.NS,M%26M.NS,BAJAJ-AUTO.NS&range=1d&interval=5m")
        self.assertEqual(scan.chart_path("M&M", "5d", "5m"), "/v8/finance/chart/M%26M.NS?range=5d&interval=5m")

    def test_spark_answers_map_back_to_nse_symbols(self):
        data, errors = scan.load_offline(DAILY)
        self.assertIn("M&M", data)
        self.assertIn("BAJAJ-AUTO", data)
        self.assertNotIn("RELIANCE.NS", data)
        self.assertEqual(errors, {})


class Daily(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data, _ = scan.load_offline(DAILY)
        cls.hits, cls.counts, cls.last = scan.scan_daily(data, sorted(data), scan.parse_now("2026-11-05 08:30"),
                                                         50.0, 500000)

    def by(self, sym):
        return [h for h in self.hits if h["symbol"] == sym][0]

    def test_the_closes_run_through_the_day_before(self):
        self.assertEqual(self.last.isoformat(), "2026-11-04")

    def test_the_setups(self):
        self.assertIn("breakout_20d", self.by("RELIANCE")["setups"])
        self.assertIn("oversold", self.by("TCS")["setups"])
        self.assertIn("oversold_bounce", self.by("INFY")["setups"])
        self.assertIn("bull_flag", self.by("HDFCBANK")["setups"])

    def test_the_rupee_floor_drops_a_penny_stock(self):
        self.assertNotIn("IDEA", [h["symbol"] for h in self.hits])     # ₹9.80, under ₹50
        self.assertEqual(self.counts["illiquid"], 2)

    def test_todays_bar_is_dropped_during_the_session(self):
        data, _ = scan.load_offline(DAILY)
        closes = scan.daily_closes(data["RELIANCE"], scan.parse_now("2026-11-04 11:00"))
        full = scan.daily_closes(data["RELIANCE"], scan.parse_now("2026-11-04 16:00"))
        self.assertEqual(len(full) - len(closes), 1)


class Orb(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, _ = scan.load_offline(WALL)

    def scan_at(self, hhmm, **kw):
        day, cutoff = scan.orb_window(scan.parse_now("2026-11-05 %s" % hhmm), None, 15,
                                      scan.datetime.time(14, 45), None)
        return scan.scan_orb(self.data, sorted(self.data), day, cutoff, 15, kw.get("min_price", 50.0), 0)

    def test_the_breakouts_at_1000(self):
        hits, counts, failed = self.scan_at("10:00")
        self.assertEqual([h["symbol"] for h in hits], ["RELIANCE", "SBIN"])
        rel = hits[0]
        self.assertEqual((rel["at"], rel["price"], rel["or_high"], rel["or_low"]), ("9:55 AM", 1311.3, 1309.3, 1298.9))

    def test_a_halted_chart_is_not_usable(self):
        hits, counts, failed = self.scan_at("10:00")
        self.assertEqual((counts["unusable"], counts["illiquid"], counts["scanned"]), (1, 1, 8))
        self.assertNotIn("TATAMOTORS", [h["symbol"] for h in hits])

    def test_nothing_before_the_breakout_bar_closes(self):
        hits, _, _ = self.scan_at("09:52")
        self.assertEqual(hits, [])

    def test_the_window_is_ist(self):
        with self.assertRaises(scan.ScanError) as cm:
            scan.orb_window(scan.parse_now("2026-11-05 09:25"), None, 15, scan.datetime.time(14, 45), None)
        self.assertIn("9:15", str(cm.exception))
        with self.assertRaises(scan.ScanError):
            scan.orb_window(scan.parse_now("2026-11-10 10:00"), None, 15, scan.datetime.time(14, 45), None)

    def test_cli_orb(self):
        code, out, err = run(["orb", "--offline", WALL, "--now", "2026-11-05 10:00", "--no-write"])
        self.assertEqual(code, 0, err)
        self.assertIn("15-minute range (9:15 to 9:30 AM)", out)
        self.assertIn("9:55 AM  RELIANCE  ₹1,311.30", out)

    def test_cli_orb_writes_the_watchlist(self):
        d = tempfile.mkdtemp()
        try:
            out = os.path.join(d, "watchlist.json")
            code, _, _ = run(["orb", "--offline", WALL, "--now", "2026-11-05 10:00", "--out", out])
            self.assertEqual(code, 0)
            with open(out) as fh:
                doc = json.load(fh)
            self.assertEqual([h["symbol"] for h in doc["hits"]], ["RELIANCE", "SBIN"])
            self.assertEqual(doc["as_of"], "2026-11-05 10:00 IST")
        finally:
            shutil.rmtree(d)


class DailyCli(unittest.TestCase):
    def test_cli_daily(self):
        code, out, err = run(["daily", "--offline", DAILY, "--now", "2026-11-05 08:30", "--no-write"])
        self.assertEqual(code, 0, err)
        self.assertIn("(₹50+ and 500,000+ shares)", out)
        self.assertIn("RELIANCE", out)


if __name__ == "__main__":
    unittest.main()

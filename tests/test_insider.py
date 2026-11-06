"""trader-insider tests. Fixtures: SEBI PIT disclosures and NSE bulk/block deals in NSE's own
JSON shape, for a fictional company and fictional people (see make_nse_fixtures.py)."""

import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, FIX

ins = load("trader-insider", "insider")

DIR = os.path.join(FIX, "trader-insider")
NOW = "2026-11-06 11:30"


def read(name):
    with open(os.path.join(DIR, name), encoding="utf-8") as fh:
        return json.load(fh)


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = ins.main(argv)
    return code, out.getvalue(), err.getvalue()


class Pit(unittest.TestCase):
    def setUp(self):
        self.trades = ins.parse_pit(read("nse-pit-SAMPLECO.json"), "SAMPLECO")

    def test_parse(self):
        self.assertEqual(len(self.trades), 5)
        t = self.trades[0]
        self.assertEqual((t["name"], t["category"], t["type"], t["mode"]),
                         ("ASHA EXAMPLE", "Promoter Group", "Buy", "Market Purchase"))
        self.assertEqual((t["qty"], t["value"], t["price"]), (150000.0, 198750000.0, 1325.0))
        self.assertEqual((t["traded"], t["told"]), ("2026-11-02", "2026-11-03"))

    def test_the_default_filter(self):
        shown = [t["name"] for t in self.trades if ins.interesting(t)]
        self.assertEqual(shown, ["ASHA EXAMPLE", "RAVI SAMPLE", "KARAN DEMO"])   # no pledge, no ESOP, no employee

    def test_late_filings(self):
        late = {t["name"]: (t["late"], t["lag_trading_days"]) for t in self.trades}
        self.assertEqual(late["ASHA EXAMPLE"], (False, 1))
        self.assertEqual(late["RAVI SAMPLE"], (True, 5))

    def test_trading_days_skip_holidays(self):
        d = ins._dt.date
        self.assertEqual(ins.trading_days_between(d(2026, 11, 9), d(2026, 11, 11)), 1)    # 10th is Diwali
        self.assertEqual(ins.trading_days_between(d(2026, 11, 6), d(2026, 11, 9)), 1)     # a weekend

    def test_describe(self):
        line = ins.describe(self.trades[1])
        self.assertIn("SOLD 20,000 shares at about ₹1345.00 (₹2.69 cr, Market Sale)", line)
        self.assertIn("LATE (5 trading days after the trade)", line)

    def test_rupees(self):
        self.assertEqual(ins.rupees(198750000), "₹19.88 cr")
        self.assertEqual(ins.rupees(520000), "₹5.20 lakh")
        self.assertEqual(ins.rupees(9000), "₹9,000")


class Deals(unittest.TestCase):
    def test_parse(self):
        deals, as_on = ins.parse_deals(read("nse-largedeal.json"))
        self.assertEqual(as_on, "05-Nov-2026")
        self.assertEqual([d["kind"] for d in deals], ["bulk", "bulk", "block"])
        self.assertEqual(deals[0]["value"], 2500000 * 1342.5)


class Cli(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.state = os.path.join(self.dir, "insider.json")

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_pit(self):
        code, out, err = run(["pit", "SAMPLECO", "--offline", DIR, "--now", NOW, "--days", "90"])
        self.assertEqual(code, 0, err)
        self.assertIn("ASHA EXAMPLE", out)
        self.assertNotIn("TEST HOLDINGS", out)
        self.assertIn("(2 more filings", out)
        self.assertIn("Not financial advice", out)

    def test_pit_window(self):
        code, out, _ = run(["pit", "SAMPLECO", "--offline", DIR, "--now", NOW, "--days", "30"])
        self.assertNotIn("KARAN DEMO", out)                             # filed 2026-09-16, outside 30 days

    def test_pit_all(self):
        code, out, _ = run(["pit", "SAMPLECO", "--offline", DIR, "--now", NOW, "--days", "90", "--all"])
        self.assertIn("TEST HOLDINGS PRIVATE LIMITE", out)               # names are cut at 28 characters
        self.assertIn("PLEDGE CREATION 500,000 shares", out)
        self.assertIn("ESOP", out)

    def test_deals_filter(self):
        code, out, _ = run(["deals", "--offline", DIR, "--tickers", "SAMPLECO"])
        self.assertEqual(code, 0)
        self.assertIn("EXAMPLE CAPITAL FUND", out)
        self.assertNotIn("OTHEREX", out)

    def test_new_then_nothing_new(self):
        args = ["new", "--tickers", "SAMPLECO", "--offline", DIR, "--now", NOW, "--days", "90", "--state", self.state]
        code, out, _ = run(args)
        self.assertEqual(code, 0)
        self.assertIn("first run", out)
        self.assertIn("ASHA EXAMPLE", out)
        self.assertIn("DEMO MUTUAL FUND", out)
        code, out, _ = run(args)
        self.assertEqual(code, 1)
        self.assertIn("Nothing new.", out)

    def test_no_symbols(self):
        cwd = os.getcwd()
        os.chdir(self.dir)
        try:
            code, _, err = run(["new", "--offline", DIR, "--now", NOW])
        finally:
            os.chdir(cwd)
        self.assertEqual(code, 2)
        self.assertIn("no symbols", err)


if __name__ == "__main__":
    unittest.main()

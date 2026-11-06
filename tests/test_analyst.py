"""trader-analyst tests, NSE edition. Fixtures: NSE results lists and XBRL filings for
SAMPLECO, a fictional company (see make_nse_fixtures.py): nine quarters from 2024-09-30 to
2026-09-30, a standalone filing of the latest quarter, and a revision of 2026-06-30."""

import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, FIX

fa = load("trader-analyst", "facts")

DIR = os.path.join(FIX, "trader-analyst")


def read(name):
    with open(os.path.join(DIR, name), "rb") as fh:
        return fh.read()


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = fa.main(argv)
    return code, out.getvalue(), err.getvalue()


class Xbrl(unittest.TestCase):
    def test_the_quarter_not_the_year_to_date(self):
        doc = fa.parse_xbrl(read("INTEGRATED_FILING_INDAS_900008_05112026_WEB.xml"))
        self.assertEqual((doc["end"], doc["start"], doc["basis"]), ("2026-09-30", "2026-07-01", "consolidated"))
        v = doc["values"]
        self.assertEqual(v["revenue"], 72600 * 1e7)
        self.assertEqual(v["net_profit"], 9930 * 1e7)
        self.assertEqual(v["eps_basic"], 13.21)
        self.assertEqual(doc["name"], "Sample Industries Limited")

    def test_a_segment_context_is_ignored(self):
        doc = fa.parse_xbrl(read("INTEGRATED_FILING_INDAS_900008_05112026_WEB.xml"))
        self.assertNotIn("other_expenses", doc["values"])

    def test_not_xbrl(self):
        with self.assertRaises(fa.FactsError):
            fa.parse_xbrl(b"<html>")

    def test_ebitda(self):
        v = fa.parse_xbrl(read("INTEGRATED_FILING_INDAS_900008_05112026_WEB.xml"))["values"]
        self.assertEqual(fa.ebitda(v), (13660 + 3410 + 4650 - 1580) * 1e7)


class Filings(unittest.TestCase):
    def setUp(self):
        self.integ = fa.filings_from(json.loads(read("nse-results-SAMPLECO.json")), "integrated")
        self.legacy = fa.filings_from(json.loads(read("nse-results-legacy-SAMPLECO.json")), "legacy")

    def test_the_lists(self):
        self.assertEqual(len(self.integ), 9)                # 7 quarters + a standalone + a revision
        self.assertEqual({f["end"] for f in self.legacy}, {"2024-09-30", "2024-12-31"})
        self.assertTrue(self.integ[0]["xbrl"].startswith("https://nsearchives.nseindia.com/corporate/xbrl/"))

    def test_pick_prefers_the_basis_and_the_revision(self):
        show, read_ = fa.pick(self.integ + self.legacy, "consolidated", 4)
        self.assertEqual(show, ["2026-09-30", "2026-06-30", "2026-03-31", "2025-12-31"])
        byend = {f["end"]: f for f in read_}
        self.assertEqual(byend["2026-09-30"]["basis"], "consolidated")
        self.assertTrue(byend["2026-06-30"]["revised"])
        self.assertIn("2024-12-31", byend)                  # the year-ago quarter of 2025-12-31
        show, read_ = fa.pick(self.integ, "standalone", 1)
        self.assertEqual({f["end"]: f for f in read_}["2026-09-30"]["basis"], "standalone")

    def test_dates(self):
        self.assertEqual(fa.nse_date("30-SEP-2026").isoformat(), "2026-09-30")
        self.assertEqual(fa.nse_stamp("05-Nov-2026 19:30:00"), "2026-11-05 19:30:00")
        self.assertIsNone(fa.nse_date("-"))


class Report(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = fa.report_for(fa.Fetcher(offline=DIR), "SAMPLECO", 4)

    def test_the_rows(self):
        rows = self.res["rows"]
        self.assertEqual([r["end"] for r in rows], ["2026-09-30", "2026-06-30", "2026-03-31", "2025-12-31"])
        cur = rows[0]
        self.assertEqual((cur["revenue_yoy"], cur["net_profit_yoy"], cur["eps_yoy"]), (10.5, 12.1, 12.0))
        self.assertEqual(rows[1]["net_profit"], 9240 * 1e7)            # the revision won
        self.assertEqual(rows[3]["revenue_yoy"], 7.1)                  # against the legacy 2024-12-31 filing
        self.assertEqual(cur["net_margin"], 13.7)
        self.assertEqual(cur["ebitda_margin"], 27.7)

    def test_ttm(self):
        self.assertEqual(self.res["ttm"]["revenue"], (72600 + 68300 + 70900 + 69400) * 1e7)

    def test_crore_format(self):
        self.assertEqual(fa.cr(281200 * 1e7), "2,81,200.0")
        self.assertEqual(fa.cr(-9930 * 1e7), "-9,930.0")
        self.assertEqual(fa.cr(None), "-")

    def test_changes(self):
        text = " ".join(fa.changes(self.res))
        self.assertIn("revenue ₹72,600.0 cr (+10.5% vs a year earlier)", text)
        self.assertIn("Owners of the company keep 90%", text)

    def test_metrics_row(self):
        row = fa.metrics_row("SAMPLECO", self.res)
        self.assertEqual((row["exchange"], row["currency"], row["period_end"]), ("NSE", "INR", "2026-09-30"))
        self.assertEqual(row["eps_ttm"], 51.47)


class Cli(unittest.TestCase):
    def test_text(self):
        code, out, err = run(["SAMPLECO", "--offline", DIR])
        self.assertEqual(code, 0, err)
        self.assertIn("Sample Industries Limited (NSE: SAMPLECO), consolidated results. ₹ crore except EPS.", out)
        self.assertIn("2026-09-30  consol    72,600.0   +10.5%", out)
        self.assertIn("EBITDA is worked out", out)

    def test_standalone(self):
        code, out, _ = run(["SAMPLECO", "--offline", DIR, "--standalone", "--quarters", "1"])
        self.assertEqual(code, 0)
        self.assertIn("2026-09-30  standa    43,560.0", out)

    def test_metrics_file(self):
        d = tempfile.mkdtemp()
        try:
            path = os.path.join(d, "metrics.json")
            code, _, _ = run(["SAMPLECO", "--offline", DIR, "--metrics", path])
            self.assertEqual(code, 0)
            with open(path) as fh:
                self.assertEqual(json.load(fh)["companies"][0]["ticker"], "SAMPLECO")
        finally:
            shutil.rmtree(d)

    def test_an_unknown_symbol(self):
        code, _, err = run(["NOSUCH", "--offline", DIR])
        self.assertEqual(code, 2)
        self.assertIn("NOSUCH", err)


if __name__ == "__main__":
    unittest.main()

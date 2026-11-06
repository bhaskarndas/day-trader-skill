"""trader-news tests, NSE edition. Fixtures: NSE corporate announcements, a Yahoo RSS feed and
a chart for SAMPLECO, a fictional company (see make_nse_fixtures.py)."""

import datetime as dt
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, FIX

news = load("trader-news", "news")

DIR = os.path.join(FIX, "trader-news")
NOW = "2026-11-05T15:00:00Z"   # 20:30 IST


def read(name):
    with open(os.path.join(DIR, name), "rb") as fh:
        return fh.read()


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = news.main(argv)
    return code, out.getvalue(), err.getvalue()


class Announcements(unittest.TestCase):
    def test_parse(self):
        items = news.parse_nse_announcements(read("nse-ann-SAMPLECO.json"), "SAMPLECO")
        self.assertEqual(len(items), 5)
        first = items[0]
        self.assertEqual(first["title"], "Sample Industries Limited: Outcome of Board Meeting")
        self.assertEqual(first["source"], "NSE filing")
        self.assertEqual(first["time"], dt.datetime(2026, 11, 5, 14, 12, 10, tzinfo=dt.timezone.utc))  # 19:42:10 IST
        self.assertTrue(first["important"])
        self.assertTrue(first["earnings"])
        self.assertTrue(first["link"].endswith(".pdf"))

    def test_what_is_important(self):
        items = {i["form"]: i for i in news.parse_nse_announcements(read("nse-ann-SAMPLECO.json"), "SAMPLECO")}
        self.assertTrue(items["Credit Rating"]["important"])
        self.assertTrue(items["Acquisition"]["important"])
        self.assertFalse(items["Trading Window-xbrl"]["important"])
        self.assertFalse(items["Analysts/Institutional Investor Meet/Con. Call Updates"]["important"])

    def test_ist_times(self):
        self.assertEqual(news.parse_ist("04-Nov-2026 20:47:14"),
                         dt.datetime(2026, 11, 4, 15, 17, 14, tzinfo=dt.timezone.utc))
        self.assertIsNone(news.parse_ist("not a date"))

    def test_a_refusal_is_one_plain_error(self):
        with self.assertRaises(news.NewsError) as cm:
            news.parse_nse_announcements(b"<html>Access Denied</html>", "SAMPLECO")
        self.assertIn("refused", str(cm.exception))


class Headlines(unittest.TestCase):
    def test_rss_and_tags(self):
        items = news.parse_rss(read("yahoo-SAMPLECO.xml"), "SAMPLECO")
        watch = {"SAMPLECO": "Sample Industries"}
        news.tag(items, watch)
        byt = {i["title"][:20]: i for i in items}
        self.assertIn("earnings", byt["Sample Industries Q2"]["tags"])
        self.assertIn("analyst", byt["Brokerages raise tar"]["tags"])
        self.assertIn("macro", byt["RBI keeps repo rate "]["tags"])
        self.assertEqual(byt["Sample Industries Q2"]["touches"], ["SAMPLECO"])

    def test_yahoo_symbol(self):
        self.assertEqual(news.yahoo_symbol("SAMPLECO"), "SAMPLECO.NS")
        self.assertEqual(news.yahoo_symbol("M&M"), "M%26M.NS")
        self.assertIn("region=IN", news.YAHOO)


class Moves(unittest.TestCase):
    def test_the_move_line(self):
        m = news.parse_chart(read("chart-SAMPLECO.json"), "SAMPLECO")
        line = news.render_moves([m])[0]
        self.assertTrue(line.startswith("SAMPLECO     ₹"), line)
        self.assertIn("IST", line)


class Cli(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.state = os.path.join(self.dir, "news.json")

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_first_check_then_nothing_new(self):
        code, out, err = run(["--tickers", "SAMPLECO", "--offline", DIR, "--now", NOW, "--hours", "96",
                              "--state", self.state])
        self.assertEqual(code, 0, err)
        self.assertIn("! 2026-11-05 19:42 IST  SAMPLECO     NSE filing    Sample Industries Limited: Outcome of Board "
                      "Meeting", out)
        self.assertIn("Yahoo Finance", out)
        self.assertNotIn("Trading Window", out)                           # older than 96 hours
        code, out, _ = run(["--tickers", "SAMPLECO", "--offline", DIR, "--now", NOW, "--hours", "96",
                            "--state", self.state])
        self.assertEqual(code, 1)
        self.assertIn("Nothing new.", out)

    def test_headlines_only(self):
        code, out, _ = run(["--tickers", "SAMPLECO", "--offline", DIR, "--now", NOW, "--hours", "96", "--no-nse",
                            "--dry-run", "--state", self.state])
        self.assertEqual(code, 0)
        self.assertNotIn("NSE filing", out)

    def test_json(self):
        code, out, _ = run(["--tickers", "SAMPLECO", "--offline", DIR, "--now", NOW, "--hours", "96", "--json",
                            "--dry-run", "--state", self.state])
        doc = json.loads(out)
        self.assertEqual(doc["moves"][0]["ticker"], "SAMPLECO")
        self.assertTrue(any(i["source"] == "NSE filing" and i["important"] for i in doc["items"]))

    def test_no_symbols(self):
        cwd = os.getcwd()
        os.chdir(self.dir)
        try:
            code, _, err = run(["--offline", DIR, "--now", NOW])
        finally:
            os.chdir(cwd)
        self.assertEqual(code, 2)
        self.assertIn("no symbols", err)


if __name__ == "__main__":
    unittest.main()

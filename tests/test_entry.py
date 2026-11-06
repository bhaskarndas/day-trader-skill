"""trader-entry tests, NSE edition. Fixtures in tests/fixtures/trader-entry/ (synthetic, see
make_nse_fixtures.py): RELIANCE.NS 5-minute bars of 2026-11-05 up to 10:29:45 IST, the
opening range 9:15 to 9:30 is 1298.90 to 1309.30 and the 9:50 bar closes at 1311.30; and a
one-minute DEMO.NS session for the 1m path."""

import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, FIX

en = load("trader-entry", "entry")

EDIR = os.path.join(FIX, "trader-entry")
REL = os.path.join(EDIR, "RELIANCE-2026-11-05-5m.json")
DEMO = os.path.join(EDIR, "DEMO-1m-synthetic.json")
with open(REL, encoding="utf-8") as _fh:
    REL_TEXT = _fh.read()


def chart():
    return en.parse_chart(REL_TEXT, "RELIANCE")


def at(text, **kw):
    return en.evaluate(chart(), en.parse_now(text), **kw)


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = en.main(argv)
    return code, out.getvalue(), err.getvalue()


class Symbols(unittest.TestCase):
    def test_yahoo_and_nse_symbols(self):
        self.assertEqual(en.yahoo_symbol("reliance"), "RELIANCE.NS")
        self.assertEqual(en.nse_symbol("RELIANCE.NS"), "RELIANCE")
        self.assertIn("/v8/finance/chart/M%26M.NS?range=1d&interval=5m", en.chart_path("M&M", "1d", "5m"))

    def test_the_result_carries_the_nse_symbol(self):
        self.assertEqual(at("2026-11-05 10:00")["symbol"], "RELIANCE")

    def test_the_chart_must_be_the_symbol(self):
        with self.assertRaises(en.EntryError):
            en.get_chart("TCS", "5m", offline=REL)


class Orb(unittest.TestCase):
    def test_not_open_yet(self):
        r = at("2026-11-05 09:10")
        self.assertEqual((r["status"], r["phase"]), ("waiting", "pre-open"))
        self.assertIn("opens at 9:15", r["reason"])

    def test_the_range_is_forming(self):
        r = at("2026-11-05 09:27")
        self.assertEqual((r["status"], r["phase"]), ("waiting", "forming"))

    def test_waiting_while_the_breakout_bar_is_open(self):
        r = at("2026-11-05 09:52")
        self.assertEqual(r["status"], "waiting")
        self.assertEqual((r["opening_range"]["high"], r["opening_range"]["low"]), (1309.3, 1298.9))
        self.assertEqual(r["forming"]["bar_start"], "09:50")

    def test_triggered_at_the_close_of_the_950_bar(self):
        r = at("2026-11-05 10:00")
        self.assertEqual(r["status"], "triggered")
        t = r["trigger"]
        self.assertEqual((t["time"], t["price"], t["bar_index"]), ("9:55 AM", 1311.3, 7))

    def test_no_entries_before_the_config_window(self):
        r = at("2026-11-05 10:00", cfg={"no_entries_before": "10:05", "no_entries_after": "14:45"})
        self.assertNotEqual(r["status"], "triggered")
        self.assertIn("no entries before 10:05", r["reason"])

    def test_a_level_setup(self):
        r = at("2026-11-05 10:00", setup="level", level=1310.0)
        self.assertEqual(r["status"], "triggered")
        r = at("2026-11-05 10:00", setup="level", level=1400.0)
        self.assertEqual(r["status"], "waiting")

    def test_volume_filter(self):
        r = at("2026-11-05 10:00", min_volume_x=50)
        self.assertNotEqual(r["status"], "triggered")

    def test_a_holiday_is_no_data(self):
        r = en.evaluate(chart(), en.parse_now("2026-11-10 10:00"))
        self.assertEqual(r["status"], "no-data")
        self.assertIn("NSE is closed today", r["reason"])

    def test_expired_after_the_cutoff(self):
        r = at("2026-11-05 10:00", setup="level", level=1400.0,
               cfg={"no_entries_before": "09:30", "no_entries_after": "09:45"})
        self.assertEqual(r["status"], "expired")


class OneMinute(unittest.TestCase):
    def test_the_1m_demo_triggers(self):
        ch = en.get_chart("DEMO", "1m", offline=DEMO)
        r = en.evaluate(ch, en.parse_now("2026-11-05 09:45"), interval="1m",
                        cfg={"no_entries_before": "09:30", "no_entries_after": "14:45"})
        self.assertEqual(r["status"], "triggered", r.get("reason"))
        self.assertEqual(r["trigger"]["time"], "9:32 AM")


class Text(unittest.TestCase):
    def test_describe(self):
        text = "\n".join(en.describe(at("2026-11-05 10:00")))
        self.assertIn("RELIANCE  Thu 2026-11-05 10:00 IST", text)
        self.assertIn("Opening range 9:15-9:30: high ₹1309.30, low ₹1298.90", text)
        self.assertIn("TRIGGERED 9:55 AM at ₹1311.30", text)


class Watch(unittest.TestCase):
    def test_the_watch_loop_replays_to_the_trigger(self):
        lines = []
        clock = en.SimClock(en.parse_now("2026-11-05 09:31"))
        code, res = en.watch_loop(lambda now: chart(), clock.now, clock.sleep, lines.append,
                                  dict(setup="orb", or_minutes=15, interval="5m", level=None, min_volume_x=None,
                                       cfg=dict(en.DEFAULTS)), every=30)
        self.assertEqual(code, 0)
        self.assertEqual(res["trigger"]["time"], "9:55 AM")
        self.assertTrue(any("TRIGGERED" in l for l in lines))


class Cli(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.dir)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.dir)

    def test_check_writes_entry_json(self):
        code, out, err = run(["check", "RELIANCE", "--offline", REL, "--now", "2026-11-05 10:00", "--write"])
        self.assertEqual(code, 0, err)
        with open("trader/entry.json") as fh:
            doc = json.load(fh)
        self.assertEqual((doc["symbol"], doc["status"], doc["price"], doc["time"]),
                         ("RELIANCE", "triggered", 1311.3, "9:55 AM"))

    def test_check_waiting_exits_1(self):
        code, out, _ = run(["check", "RELIANCE", "--offline", REL, "--now", "2026-11-05 09:52"])
        self.assertEqual(code, 1)
        self.assertIn("WAITING", out)

    def test_offline_folder(self):
        os.makedirs("charts")
        shutil.copy(REL, os.path.join("charts", "RELIANCE.json"))
        code, _, err = run(["check", "RELIANCE", "--offline", "charts", "--now", "2026-11-05 10:00"])
        self.assertEqual(code, 0, err)

    def test_watch_offline(self):
        code, out, _ = run(["watch", "RELIANCE", "--offline", REL, "--now", "2026-11-05 09:31"])
        self.assertEqual(code, 0)
        self.assertIn("TRIGGERED", out)


if __name__ == "__main__":
    unittest.main()

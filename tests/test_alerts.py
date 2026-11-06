"""trader-alerts tests, NSE edition: the NSE clock in IST, Yahoo .NS quotes, plan alerts."""

import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, FIX

al = load("trader-alerts", "alerts")

QDIR = os.path.join(FIX, "trader-alerts")
PLAN = os.path.join(FIX, "trader-budget", "plan-reliance.json")


def now(text):
    return al.parse_now(text)


def ev(rules, quotes, when, state=None):
    """Rings for one check at IST time `when`; state carries what already rang."""
    st = al.market_status(now(when))
    rings, new = al.evaluate(rules, quotes, st, state if state is not None else {}, now(when))
    if state is not None:
        state.clear()
        state.update(new)
    return rings


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = al.main(argv)
    return code, out.getvalue(), err.getvalue()


class Clock(unittest.TestCase):
    def test_open_during_the_session(self):
        st = al.market_status(now("2026-11-05 11:30"))
        self.assertTrue(st["open"])
        self.assertEqual((st["opens"], st["closes"]), ("09:15", "15:30"))
        self.assertEqual(st["now_india"], "2026-11-05 11:30")

    def test_before_the_open_and_after_the_close(self):
        st = al.market_status(now("2026-11-05 09:10"))
        self.assertEqual((st["open"], st["reason"], st["next_open"]), (False, "before the open", "2026-11-05 09:15"))
        st = al.market_status(now("2026-11-05 15:30"))
        self.assertEqual((st["open"], st["reason"]), (False, "after the close"))
        self.assertEqual(st["next_open"], "2026-11-06 09:15")

    def test_holidays_and_the_muhurat_sunday(self):
        st = al.market_status(now("2026-11-10 10:00"))
        self.assertEqual(st["reason"], "NSE holiday: Diwali Balipratipada")
        self.assertEqual(st["next_open"], "2026-11-11 09:15")
        st = al.market_status(now("2026-11-08 18:30"))
        self.assertEqual(st["reason"], "weekend")
        self.assertEqual(st["special_session"], "Muhurat trading (Diwali Laxmi Pujan)")
        st = al.market_status(now("2026-11-06 16:00"))                   # Friday after the close
        self.assertEqual(st["next_open"], "2026-11-09 09:15")

    def test_all_2026_holidays_close_the_market(self):
        for d in al.NSE_HOLIDAYS:
            ok, why = al.trading_day(al.datetime.date.fromisoformat(d))
            self.assertFalse(ok, d)
            self.assertTrue(why.startswith("NSE holiday"), d)
        self.assertEqual(len(al.NSE_HOLIDAYS), 16)

    def test_the_calendar_is_known_for_2026_only(self):
        self.assertTrue(al.market_status(now("2026-12-31 10:00"))["calendar_known"])
        self.assertFalse(al.market_status(now("2027-01-04 10:00"))["calendar_known"])

    def test_utc_input(self):
        self.assertEqual(al.market_status(al.parse_now("2026-11-05T06:00:00Z"))["now_india"], "2026-11-05 11:30")


class Quotes(unittest.TestCase):
    def test_yahoo_symbols_and_urls(self):
        self.assertEqual(al.yahoo_symbol("reliance"), "RELIANCE.NS")
        self.assertEqual(al.yahoo_symbol("^NSEI"), "^NSEI")
        self.assertIn("/v8/finance/chart/M%26M.NS?range=1d&interval=1d", al.yahoo_url("M&M"))

    def test_the_fixtures(self):
        quotes, errors = al.get_quotes(["RELIANCE", "TCS", "M&M", "ZZZZ"], offline=QDIR)
        self.assertEqual(quotes["RELIANCE"]["price"], 1318.6)
        self.assertEqual(quotes["RELIANCE"]["prev_close"], 1296.4)
        self.assertEqual(quotes["RELIANCE"]["currency"], "INR")
        self.assertEqual(quotes["M&M"]["price"], 3251.0)
        self.assertEqual(len(errors), 1)
        self.assertIn("No data found", errors[0])

    def test_write_prices(self):
        d = tempfile.mkdtemp()
        try:
            path = os.path.join(d, "prices.json")
            quotes, _ = al.get_quotes(["RELIANCE"], offline=QDIR)
            doc = al.write_prices(path, quotes, now("2026-11-05 11:41"), "yahoo")
            self.assertEqual(doc["prices"]["RELIANCE"], 1318.6)
            self.assertEqual(doc["as_of"], "2026-11-05T06:11:00Z")
        finally:
            shutil.rmtree(d)


class Rules(unittest.TestCase):
    def setUp(self):
        with open(PLAN) as fh:
            self.plan = json.load(fh)

    def test_rules_from_the_plan(self):
        rules = al.rules_from_plan(self.plan)
        self.assertEqual([r["id"] for r in rules], ["reliance-plan-stop", "reliance-plan-target", "reliance-flat-by"])
        self.assertEqual(rules[2]["at"], "15:10")
        self.assertTrue(all(r["date"] == "2026-11-05" for r in rules))

    def test_the_target_rings_once(self):
        rules = al.rules_from_plan(self.plan)
        quotes, _ = al.get_quotes(["RELIANCE"], offline=QDIR)
        state = {}
        rings = ev(rules, quotes, "2026-11-05 11:41", state)
        self.assertEqual([r["id"] for r in rings], ["reliance-plan-target"])
        self.assertEqual(ev(rules, quotes, "2026-11-05 11:42", state), [])

    def test_the_flat_by_time_rings_at_1510_ist(self):
        rules = [r for r in al.rules_from_plan(self.plan) if r["type"] == "time"]
        self.assertEqual(ev(rules, {}, "2026-11-05 15:09"), [])
        rings = ev(rules, {}, "2026-11-05 15:10")
        self.assertEqual(len(rings), 1)
        self.assertIn("IST", rings[0]["message"])

    def test_a_plan_rule_is_quiet_on_another_day(self):
        rules = al.rules_from_plan(self.plan)
        quotes, _ = al.get_quotes(["RELIANCE"], offline=QDIR)
        self.assertEqual(ev(rules, quotes, "2026-11-06 11:41"), [])

    def test_the_opening_bell(self):
        rule = [{"id": "opening-bell", "type": "opening_bell"}]
        rings = ev(rule, {}, "2026-11-05 09:16")
        self.assertEqual(len(rings), 1)
        self.assertIn("NSE is open", rings[0]["message"])
        self.assertEqual(ev(rule, {}, "2026-11-10 09:16"), [])

    def test_a_pct_move(self):
        rule = [{"id": "itc-pct", "symbol": "ITC", "type": "pct_move", "pct": 3}]
        quotes, _ = al.get_quotes(["ITC"], offline=QDIR)
        rings = ev(rule, quotes, "2026-11-05 11:41")
        self.assertEqual(len(rings), 1)                                  # 412.30 -> 426.85 is +3.53%


class Cli(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.dir)
        os.makedirs("trader")
        shutil.copy(PLAN, "trader/plan.json")

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.dir)

    def test_clock(self):
        code, out, _ = run(["clock", "--now", "2026-11-05 11:30"])
        self.assertEqual(code, 0)
        self.assertIn("IST 2026-11-05 11:30 (Thursday): NSE OPEN, regular session.", out)
        code, out, _ = run(["clock", "--now", "2026-11-08 18:00"])
        self.assertEqual(code, 1)
        self.assertIn("Muhurat", out)
        code, out, _ = run(["clock", "--now", "2027-01-04 10:00"])
        self.assertIn("nseindia.com", out)

    def test_add_from_plan_then_check(self):
        code, out, err = run(["add", "--from-plan"])
        self.assertEqual(code, 0, err)
        code, out, _ = run(["check", "--now", "2026-11-05 11:41", "--offline", QDIR])
        self.assertEqual(code, 0)
        self.assertIn("RELIANCE", out)
        self.assertIn("1318.6", out)
        code, out, _ = run(["check", "--now", "2026-11-05 11:42", "--offline", QDIR])
        self.assertEqual(code, 1)                                       # nothing new rang

    def test_quote_write(self):
        code, out, _ = run(["quote", "RELIANCE", "TCS", "--offline", QDIR, "--write", "trader/prices.json",
                            "--now", "2026-11-05 11:41"])
        self.assertEqual(code, 0)
        with open("trader/prices.json") as fh:
            self.assertEqual(json.load(fh)["prices"]["TCS"], 2981.2)


if __name__ == "__main__":
    unittest.main()

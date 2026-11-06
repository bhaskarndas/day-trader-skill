"""trader-timemachine tests, NSE edition. The fixture is synthetic (see
tests/fixtures/make_nse_fixtures.py): 60 sessions of RELIANCE.NS 5-minute bars on
the real NSE calendar, IST, 75 bars a day, with an opening-range breakout on
2026-11-05 (range 1298.90 to 1309.30, the 9:50 bar closes at 1311.30)."""

import copy
import gzip
import io
import json
import os
import shutil
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout, redirect_stderr

from _load import load, FIX

tm = load("trader-timemachine", "timemachine")

DIR = os.path.join(FIX, "trader-timemachine")
REL = os.path.join(DIR, "RELIANCE-60d5m.json.gz")
with gzip.open(REL, "rt", encoding="utf-8") as _fh:
    TEXT = _fh.read()
NOW = "2026-11-05 10:30"
NOW_UTC = tm.parse_now(NOW)

PLAN = {"created_by": "trader-exit", "symbol": "RELIANCE", "side": "buy", "date": "2026-11-05", "setup": "orb",
        "entry": 1311.30, "entry_time": "9:55 AM", "entry_bar": 7, "interval": "5m",
        "opening_range": {"high": 1309.30, "low": 1298.90, "minutes": 15},
        "stop": 1304.10, "stop_rule": "or_mid", "target": 1318.50, "target_r": 1.0,
        "risk_per_share": 7.20, "reward_risk": 1.0, "flat_by": "15:10"}


def plan(**kw):
    raw = dict(PLAN)
    raw.update(kw)
    return tm.normalize_plan(raw)


def machine(p=None, text=TEXT, now=NOW_UTC, **kw):
    return tm.time_machine(text, p or plan(), now, **kw)


def edited(fn):
    doc = json.loads(TEXT)
    fn(doc["chart"]["result"][0])
    return json.dumps(doc)


def keep_bars(result, keep):
    q = result["indicators"]["quote"][0]
    idx = [i for i, ts in enumerate(result["timestamp"]) if keep(ts)]
    result["timestamp"] = [result["timestamp"][i] for i in idx]
    for k in q:
        q[k] = [q[k][i] for i in idx]


def ist(ts):
    return tm.to_ist(tm.utc_of(ts))


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = tm.main(argv)
    return code, out.getvalue(), err.getvalue()


class Clock(unittest.TestCase):
    def test_ist_is_utc_plus_530_all_year(self):
        for month in (1, 4, 7, 11):
            utc = tm.datetime.datetime(2026, month, 5, 4, 0)
            self.assertEqual(tm.to_ist(utc), tm.datetime.datetime(2026, month, 5, 9, 30))
        self.assertEqual(tm.ist_to_utc(tm.datetime.datetime(2026, 11, 5, 9, 15)),
                         tm.datetime.datetime(2026, 11, 5, 3, 45))
        self.assertEqual(tm.parse_now("2026-11-05 10:30"), tm.datetime.datetime(2026, 11, 5, 5, 0))
        self.assertEqual(tm.parse_now("2026-11-05T05:00:00Z"), tm.datetime.datetime(2026, 11, 5, 5, 0))

    def test_the_session_is_75_bars_from_915(self):
        self.assertEqual(tm.SESSION_BARS, 75)
        self.assertEqual(tm.OPEN_MIN, 9 * 60 + 15)
        self.assertEqual(tm.CLOSE_MIN, 15 * 60 + 30)

    def test_clock_text(self):
        self.assertEqual(tm.parse_clock("9:55 AM", "x"), 9 * 60 + 55)
        self.assertEqual(tm.parse_clock("15:10", "x"), 15 * 60 + 10)
        self.assertEqual(tm.parse_clock("3:10", "x"), 15 * 60 + 10)   # a bare 1 to 8 is the afternoon
        self.assertEqual(tm.clock12(9 * 60 + 55), "9:55 AM")
        with self.assertRaises(tm.TMError):
            tm.parse_clock("25:00", "x")


class Symbols(unittest.TestCase):
    def test_yahoo_symbols(self):
        self.assertEqual(tm.yahoo_symbol("reliance"), "RELIANCE.NS")
        self.assertEqual(tm.yahoo_symbol("RELIANCE.NS"), "RELIANCE.NS")
        self.assertEqual(tm.yahoo_symbol("^NSEI"), "^NSEI")
        self.assertEqual(tm.nse_symbol("M&M.NS"), "M&M")
        url = tm.chart_url("M&M")
        self.assertIn("/v8/finance/chart/M%26M.NS?range=60d&interval=5m", url)
        self.assertIn("BAJAJ-AUTO.NS", tm.chart_url("BAJAJ-AUTO"))

    def test_plan_symbols_with_ampersand_and_hyphen(self):
        self.assertEqual(plan(symbol="m&m")["symbol"], "M&M")
        self.assertEqual(plan(symbol="BAJAJ-AUTO")["symbol"], "BAJAJ-AUTO")
        self.assertEqual(plan(symbol="RELIANCE.NS")["symbol"], "RELIANCE")
        with self.assertRaises(tm.TMError):
            plan(symbol="NOT A SYMBOL")


class Ticks(unittest.TestCase):
    def test_tick_bands(self):
        for price, tick in ((9.8, 0.01), (249.99, 0.01), (250, 0.05), (1000, 0.05), (1000.05, 0.10),
                            (5000, 0.10), (8750, 0.50), (15000, 1.00), (25000, 5.00)):
            self.assertEqual(tm.tick_size(price), tick, price)

    def test_stop_rounds_away_from_the_entry_on_the_tick(self):
        self.assertEqual(tm.cents_away(1304.10, True), 1304.10)
        self.assertEqual(tm.cents_away(1304.17, True), 1304.10)
        self.assertEqual(tm.cents_away(1304.17, False), 1304.20)
        self.assertEqual(tm.cents_away(812.33, True), 812.30)
        self.assertEqual(tm.cents_away(812.33, False), 812.35)
        self.assertEqual(tm.cents_away(212.337, True), 212.33)
        self.assertEqual(tm.cents_away(1304.0999999, True), 1304.10)


class TheReplay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = machine()

    def test_odds_add_up_and_are_pinned(self):
        m = self.doc["mc"]
        self.assertAlmostEqual(m["p_target"] + m["p_stop"] + m["p_neither"], 1.0, places=6)
        self.assertEqual((m["p_target"], m["p_stop"], m["p_neither"]), (0.5817, 0.406, 0.0123))
        self.assertEqual(m["replays"], 10000)
        self.assertEqual(m["seed"], 19)
        self.assertEqual(m["bars_left"], 67)
        self.assertEqual(m["until"], "15:30")

    def test_the_pool_is_full_sessions_before_the_plan_day(self):
        m = self.doc["mc"]
        self.assertEqual(m["pool_sessions"], 58)
        self.assertEqual(m["pool_to"], "2026-11-04")
        short = self.doc["data"]["short_sessions_left_out"]
        self.assertEqual([s["date"] for s in short], ["2026-09-23"])
        self.assertEqual(short[0]["bars"], 60)

    def test_holidays_are_not_sessions(self):
        days = tm.split_sessions(tm.parse_bars(tm.chart_result(TEXT, "RELIANCE"), NOW_UTC)[1])
        for h in ("2026-09-14", "2026-10-02", "2026-10-20"):
            self.assertNotIn(h, days)

    def test_bands_start_at_the_entry(self):
        m = self.doc["mc"]
        self.assertEqual(m["bands"][0], [1311.30] * 5)
        self.assertEqual(m["band_times"][0], "09:55")
        self.assertEqual(m["band_times"][-1], "15:30")
        self.assertTrue(all(p[0] == 1311.30 and len(p) == 68 for p in m["sample_paths"]))

    def test_the_history_replay(self):
        h = self.doc["history"]
        self.assertEqual(h["rule"]["stop_rule"], "or_mid")
        self.assertEqual(h["sessions"], 58)
        self.assertEqual(h["triggered"], h["target"] + h["stop"] + h["close"])
        for tr in h["trades"]:
            self.assertEqual(tm.cents_away(tr["stop"], True), tr["stop"])   # every stop on the tick

    def test_the_verdict(self):
        self.assertEqual(self.doc["verdict"], "Leans toward the target: target first 58.2 % vs stop first 40.6 %.")

    def test_the_text_report(self):
        text = "\n".join(tm.report(self.doc))
        self.assertIn("RELIANCE buy, Thursday 2026-11-05: entry 1311.30 at 9:55 AM (bar 7), stop 1304.10, "
                      "target 1318.50 (1R, risk ₹7.20 a share).", text)
        self.assertIn("10,000 replays of the rest of the session, 9:55 AM to 3:30 PM (67 five-minute bars), seed 19.",
                      text)
        self.assertIn("Left out 1 short session(s) (Muhurat or gaps): 2026-09-23.", text)
        self.assertIn("IST", self.doc["data"]["last_bar"])

    def test_same_seed_same_numbers_another_seed_others(self):
        a, b = machine()["mc"], machine()["mc"]
        self.assertEqual((a["p_target"], a["median_close"], a["bands"]), (b["p_target"], b["median_close"], b["bands"]))
        c = machine(seed=7)["mc"]
        self.assertNotEqual((a["p_target"], a["median_close"]), (c["p_target"], c["median_close"]))


class Until(unittest.TestCase):
    def test_flat_by_1510_cuts_the_replay(self):
        doc = machine(until="15:10")
        self.assertEqual(doc["mc"]["until"], "15:10")
        self.assertEqual(doc["mc"]["bars_left"], 63)
        self.assertEqual(doc["mc"]["band_times"][-1], "15:10")
        self.assertIn("3:10 PM", doc["verdict"] + " ".join(doc["verdict_notes"]) + "\n".join(tm.report(doc)))

    def test_until_after_the_close_or_off_grid_is_refused(self):
        for bad in ("15:35", "15:12"):
            with self.assertRaises(tm.TMError):
                machine(until=bad)

    def test_until_before_the_entry_is_refused(self):
        with self.assertRaises(tm.TMError):
            machine(until="9:50")


class Data(unittest.TestCase):
    def test_the_live_tick_and_the_open_bar_are_dropped(self):
        meta, bars, dropped = tm.parse_bars(tm.chart_result(TEXT, "RELIANCE"), NOW_UTC)
        self.assertEqual(dropped["off_grid"], 1)                    # the 10:29:45 tick
        self.assertEqual(dropped["not_complete"], 1)                # the 10:25 bar, still open then
        last = bars[-1]
        self.assertEqual((last["date"], last["start"]), ("2026-11-05", "10:20"))   # the data says 10:29:45

    def test_now_pins_the_clock(self):
        _, bars, dropped = tm.parse_bars(tm.chart_result(TEXT, "RELIANCE"), tm.parse_now("2026-11-05 10:00"))
        self.assertEqual(bars[-1]["start"], "09:55")
        self.assertGreater(dropped["not_complete"], 0)

    def test_bars_outside_the_session_are_dropped(self):
        def add_preopen(r):
            first = r["timestamp"][0]
            r["timestamp"].insert(0, first - 900)                   # 9:00 IST, the pre-open
            for k in r["indicators"]["quote"][0]:
                r["indicators"]["quote"][0][k].insert(0, 1.0)
        _, _, dropped = tm.parse_bars(tm.chart_result(edited(add_preopen), "RELIANCE"), NOW_UTC)
        self.assertEqual(dropped["outside_hours"], 1)

    def test_a_short_day_is_left_out(self):
        target = "2026-10-15"

        def cut(r):
            keep_bars(r, lambda ts: not (ist(ts).date().isoformat() == target and ist(ts).hour >= 12))
        doc = machine(text=edited(cut))
        self.assertIn(target, [s["date"] for s in doc["data"]["short_sessions_left_out"]])
        self.assertEqual(doc["mc"]["pool_sessions"], 57)

    def test_fewer_than_20_sessions_is_refused(self):
        def cut(r):
            keep_bars(r, lambda ts: ist(ts).date().isoformat() >= "2026-10-20")
        with self.assertRaises(tm.TMError) as cm:
            machine(text=edited(cut))
        self.assertIn("needs at least 20", str(cm.exception))

    def test_the_data_must_be_the_plans_symbol(self):
        with self.assertRaises(tm.TMError) as cm:
            machine(plan(symbol="TCS"))
        self.assertIn("RELIANCE", str(cm.exception))

    def test_an_entry_not_in_the_data_is_refused(self):
        with self.assertRaises(tm.TMError):
            machine(now=tm.parse_now("2026-11-05 09:52"))

    def test_broken_data(self):
        for bad in ("not json", "{}", json.dumps({"chart": {"result": None, "error": {"description": "No data"}}})):
            with self.assertRaises(tm.TMError):
                machine(text=bad)


class Plans(unittest.TestCase):
    def test_plan_checks(self):
        with self.assertRaises(tm.TMError):
            plan(stop=1320.0)                          # a buy's stop above the entry
        with self.assertRaises(tm.TMError):
            plan(entry_time="9:57 AM", entry_bar=None)  # off the 5-minute grid
        with self.assertRaises(tm.TMError):
            plan(interval="1m")
        with self.assertRaises(tm.TMError):
            plan(entry_bar=8)                          # disagrees with 9:55 AM
        with self.assertRaises(tm.TMError):
            plan(entry_time="3:30 PM", entry_bar=None)  # nothing left to replay

    def test_entry_time_alone_or_bar_alone(self):
        self.assertEqual(plan(entry_bar=None)["entry_bar"], 7)
        self.assertEqual(plan(entry_time=None)["entry_time"], "9:55 AM")

    def test_the_stop_rule_is_worked_out(self):
        self.assertEqual(tm.resolve_rule(plan(stop_rule="auto"), {i: b for i, b in enumerate(
            [{"h": 1309.30, "l": 1298.90}] * 3)})["stop_rule"], "or_mid")
        self.assertEqual(tm.resolve_rule(plan(stop_rule="auto", stop=1298.90), {i: {"h": 1309.30, "l": 1298.90}
                                                                                for i in range(3)})["stop_rule"],
                         "or_low")

    def test_a_setup_other_than_orb_skips_the_history(self):
        doc = machine(plan(setup="level"))
        self.assertIsNone(doc["history"]["rule"])
        self.assertIn("orb", doc["history"]["note"])

    def test_a_sell_plan_mirrors_the_rules(self):
        doc = machine(plan(side="sell", entry=1311.30, stop=1318.50, target=1304.10, stop_rule="pct"))
        m = doc["mc"]
        self.assertAlmostEqual(m["p_target"] + m["p_stop"] + m["p_neither"], 1.0, places=6)
        self.assertIn("below the entry", "\n".join(tm.report(doc)))


class Verdicts(unittest.TestCase):
    def mc(self, pt, ps, r=1.0, pn=None, avg=0.0):
        return {"p_target": pt, "p_stop": ps, "p_neither": 1 - pt - ps if pn is None else pn, "r_at_target": r,
                "avg_R": avg, "until": "15:30"}

    def test_thresholds_at_1r(self):
        self.assertTrue(tm.verdict(self.mc(0.30, 0.29)).startswith("Close to a coin flip"))
        self.assertTrue(tm.verdict(self.mc(0.40, 0.30)).startswith("Leans toward the target"))
        self.assertTrue(tm.verdict(self.mc(0.20, 0.50)).startswith("Strongly toward the stop"))
        self.assertTrue(tm.verdict(self.mc(0.0, 0.0)).startswith("No replay reached"))

    def test_2r_is_judged_against_its_break_even(self):
        v = tm.verdict(self.mc(0.241, 0.505, r=2.0))
        self.assertTrue(v.startswith("Close to break-even"), v)

    def test_notes_when_many_hit_neither(self):
        notes = tm.verdict_notes(self.mc(0.2, 0.1, pn=0.7))
        self.assertTrue(any("3:30 PM" in n for n in notes))


class Network(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.real_get, self.real_sleep = tm._get, tm._sleep
        tm._sleep = lambda s: None

    def tearDown(self):
        tm._get, tm._sleep = self.real_get, self.real_sleep

    def answer(self, codes):
        def fake(url, timeout=20):
            self.calls.append(url)
            code = codes.pop(0)
            if code == 200:
                return TEXT
            raise urllib.error.HTTPError(url, code, "x", {}, io.BytesIO(b""))
        tm._get = fake

    def test_429_retries_then_falls_back_to_query1(self):
        self.answer([429, 429, 200])
        self.assertEqual(tm.fetch_chart("RELIANCE"), TEXT)
        self.assertIn("query2", self.calls[0])
        self.assertIn("query1", self.calls[2])
        self.assertIn("RELIANCE.NS", self.calls[0])

    def test_404_is_one_plain_line(self):
        self.answer([404])
        with self.assertRaises(tm.TMError) as cm:
            tm.fetch_chart("NOSUCH")
        self.assertIn("check the ticker", str(cm.exception))


class Cli(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.plan = os.path.join(self.dir, "plan.json")
        with open(self.plan, "w") as fh:
            json.dump(PLAN, fh)

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_run_with_the_plan_end_to_end(self):
        out = os.path.join(self.dir, "tm.json")
        code, text, err = run(["run", "--plan", self.plan, "--offline", REL, "--now", NOW, "--write", out])
        self.assertEqual(code, 0, err)
        self.assertIn("target first   58.2 %", text)
        self.assertIn("Repeat this run with --seed 19.", text)
        with open(out) as fh:
            self.assertEqual(json.load(fh)["mc"]["p_target"], 0.5817)

    def test_the_plan_as_flags_matches_the_file(self):
        code, text, _ = run(["run", "--symbol", "RELIANCE", "--date", "2026-11-05", "--entry", "1311.30",
                             "--stop", "1304.10", "--target", "1318.50", "--entry-time", "9:55 AM",
                             "--offline", REL, "--now", NOW, "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(text)["mc"]["p_target"], 0.5817)

    def test_offline_folder(self):
        code, _, err = run(["run", "--plan", self.plan, "--offline", DIR, "--now", NOW])
        self.assertEqual(code, 0, err)

    def test_errors_are_one_plain_line(self):
        code, _, err = run(["run", "--plan", os.path.join(self.dir, "nope.json"), "--offline", REL, "--now", NOW])
        self.assertEqual(code, 1)
        self.assertEqual(len(err.strip().splitlines()), 1)

    def test_chart(self):
        out = os.path.join(self.dir, "tm.json")
        run(["run", "--plan", self.plan, "--offline", REL, "--now", NOW, "--write", out])
        code, text, _ = run(["chart", "--from", out])
        self.assertEqual(code, 0)
        self.assertTrue(any(l.strip().startswith("1318.50 |") for l in text.splitlines()))
        self.assertTrue(any(l.strip().startswith("1304.10 |") for l in text.splitlines()))


if __name__ == "__main__":
    unittest.main()

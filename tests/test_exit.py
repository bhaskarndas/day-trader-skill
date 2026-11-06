"""trader-exit tests, NSE edition. The ATR stop reads the synthetic RELIANCE
session in tests/fixtures/trader-entry/ (see make_nse_fixtures.py)."""

import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from decimal import Decimal

from _load import load, FIX

ex = load("trader-exit", "exit")

REL = os.path.join(FIX, "trader-entry", "RELIANCE-2026-11-05-5m.json")
REL_CLOSE = os.path.join(FIX, "trader-entry", "RELIANCE-2026-11-05-5m-close.json")
NOW = "2026-11-05 10:00"


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = ex.main(argv)
    return code, out.getvalue(), err.getvalue()


def compute(entry="1311.30", stop=("or_mid", None), target=("r", Decimal(1)), oh="1309.30", ol="1298.90", **kw):
    return ex.compute(entry, stop[0], stop[1], target[0], target[1], oh, ol, **kw)


class Ticks(unittest.TestCase):
    def test_tick_bands(self):
        self.assertEqual(ex.tick_size(200), Decimal("0.01"))
        self.assertEqual(ex.tick_size(812), Decimal("0.05"))
        self.assertEqual(ex.tick_size(1311.30), Decimal("0.10"))
        self.assertEqual(ex.tick_size(8750), Decimal("0.50"))
        self.assertEqual(ex.tick_size(15000), Decimal("1.00"))
        self.assertEqual(ex.tick_size(30000), Decimal("5.00"))

    def test_a_stop_rounds_down_to_the_tick_and_a_target_half_up(self):
        self.assertEqual(ex.floor_cents("1304.17"), Decimal("1304.10"))
        self.assertEqual(ex.floor_cents("812.34"), Decimal("812.30"))
        self.assertEqual(ex.floor_cents("212.339"), Decimal("212.33"))
        self.assertEqual(ex.tick_round("1318.55"), Decimal("1318.60"))
        self.assertEqual(ex.tick_round("1318.54"), Decimal("1318.50"))
        self.assertEqual(ex.tick_round("8761.30"), Decimal("8761.50"))


class Money(unittest.TestCase):
    def test_rupees_with_lakh_grouping(self):
        self.assertEqual(ex.money(1311.3), "₹1,311.30")
        self.assertEqual(ex.money(74744.1), "₹74,744.10")
        self.assertEqual(ex.money(1234567.5), "₹12,34,567.50")
        self.assertEqual(ex.money(-483.82), "-₹483.82")
        self.assertEqual(ex.group_in("100000000"), "10,00,00,000")


class Compute(unittest.TestCase):
    def test_the_orb_plan(self):
        c = compute()
        self.assertEqual((c["entry"], c["stop"], c["target"], c["risk"]),
                         (Decimal("1311.30"), Decimal("1304.10"), Decimal("1318.50"), Decimal("7.20")))
        self.assertEqual(c["stop_label"], "opening-range midpoint")
        self.assertEqual(c["reward_risk"], Decimal("1.00"))

    def test_2r_is_on_the_tick(self):
        c = compute(target=("r", Decimal(2)))
        self.assertEqual(c["target"], Decimal("1325.70"))
        c = compute(target=("r", Decimal("1.5")))
        self.assertEqual(c["target"], Decimal("1322.10"))

    def test_or_low_pct_price(self):
        self.assertEqual(compute(stop=("or_low", None))["stop"], Decimal("1298.90"))
        c = compute(stop=("pct", Decimal(1)))
        self.assertEqual(c["stop"], Decimal("1298.10"))          # 1298.187 rounded down to the 0.10 tick
        self.assertIn("rounded down to the tick", c["stop_detail"])
        self.assertEqual(compute(stop=("price", Decimal("1300")))["stop"], Decimal("1300.00"))

    def test_a_cheap_stock_keeps_paise_ticks(self):
        c = ex.compute("212.40", "pct", Decimal("0.75"), "r", Decimal(1))
        self.assertEqual(c["stop"], Decimal("210.80"))
        self.assertEqual(c["target"], Decimal("214.00"))

    def test_refusals(self):
        with self.assertRaises(ex.PlanError):
            compute(stop=("price", Decimal("1312")))            # at or above the entry
        with self.assertRaises(ex.PlanError):
            compute(target=("price", Decimal("1300")))          # under the entry
        with self.assertRaises(ex.PlanError):
            compute(stop=("price", Decimal("1311.00")))         # under 0.05% of the price
        with self.assertRaises(ex.PlanError):
            compute(oh=None, ol=None)

    def test_atr(self):
        c = compute(stop=("atr", Decimal("1.5")), atr=4.0, atr_bars=8)
        self.assertEqual(c["stop"], Decimal("1305.30"))
        self.assertIn("fewer than 14 so far", c["stop_detail"])

    def test_parse_inputs_take_rupee_signs(self):
        self.assertEqual(ex.parse_stop("price:₹1,300"), ("price", Decimal("1300")))
        self.assertEqual(ex.parse_target("price:₹1,330.5"), ("price", Decimal("1330.5")))
        self.assertEqual(ex.parse_stop("or-mid"), ("or_mid", None))
        with self.assertRaises(ex.PlanError):
            ex.parse_stop("trailing")


class Bars(unittest.TestCase):
    def test_session_bars_drop_the_live_tick_and_open_bar(self):
        chart = ex.load_chart("RELIANCE", "5m", ex.datetime.date(2026, 11, 5), REL)
        bars = ex.session_bars(chart, ex.datetime.date(2026, 11, 5), "5m")
        self.assertEqual(len(bars), 14)                         # 9:15 to 10:20, the data's own time is 10:29:45
        bars = ex.session_bars(chart, ex.datetime.date(2026, 11, 5), "5m", upto_slot=7)
        self.assertEqual(len(bars), 8)
        atr, n = ex.atr_of(bars)
        self.assertEqual(n, 8)
        self.assertGreater(atr, 0)

    def test_the_chart_must_be_the_symbol(self):
        with self.assertRaises(ex.PlanError):
            ex.load_chart("TCS", "5m", ex.datetime.date(2026, 11, 5), REL)

    def test_a_holiday_has_no_session(self):
        self.assertIsNone(ex.session(ex.datetime.date(2026, 11, 10)))     # Diwali Balipratipada
        self.assertIsNone(ex.session(ex.datetime.date(2026, 11, 8)))      # a Sunday (the Muhurat session)
        self.assertEqual(ex.session(ex.datetime.date(2026, 11, 5)), (ex.OPEN, ex.CLOSE))
        self.assertEqual(ex.OPEN, ex.datetime.time(9, 15))
        self.assertEqual(ex.CLOSE, ex.datetime.time(15, 30))


class Cli(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.dir)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.dir)

    def entry_json(self, **kw):
        os.makedirs("trader", exist_ok=True)
        doc = {"created_by": "trader-entry", "symbol": "RELIANCE", "setup": "orb", "side": "buy", "status": "triggered",
               "date": "2026-11-05", "time": "9:55 AM", "price": 1311.3, "bar_index": 7, "interval": "5m",
               "opening_range": {"high": 1309.3, "low": 1298.9, "minutes": 15}}
        doc.update(kw)
        with open("trader/entry.json", "w") as fh:
            json.dump(doc, fh)

    def test_plan_from_entry_json_writes_plan_json(self):
        self.entry_json()
        code, out, err = run(["plan", "--target", "1R", "--now", NOW, "--write"])
        self.assertEqual(code, 0, err)
        self.assertIn("Entry         ₹1,311.30 at 9:55 AM (bar 7)", out)
        self.assertIn("Stop          ₹1,304.10  opening-range midpoint", out)
        self.assertIn("Target        ₹1,318.50  1R (one times the risk)", out)
        self.assertIn("Flat by       15:10 IST", out)
        with open("trader/plan.json") as fh:
            plan = json.load(fh)
        self.assertEqual((plan["stop"], plan["target"], plan["risk_per_share"], plan["flat_by"]),
                         (1304.1, 1318.5, 7.2, "15:10"))

    def test_a_waiting_entry_is_refused(self):
        self.entry_json(status="waiting")
        code, _, err = run(["plan", "--now", NOW])
        self.assertEqual(code, 1)
        self.assertIn("not triggered", err)

    def test_the_config_flat_by_and_a_late_entry(self):
        self.entry_json(time="3:15 PM")
        code, _, err = run(["plan", "--now", NOW])
        self.assertEqual(code, 1)
        self.assertIn("after your flat-by 15:10", err)

    def test_atr_from_the_offline_chart(self):
        code, out, err = run(["plan", "--symbol", "RELIANCE", "--entry", "1311.30", "--date", "2026-11-05",
                              "--time", "9:55 AM", "--entry-bar", "7", "--stop", "atr:1.5", "--offline", REL_CLOSE,
                              "--now", NOW, "--json"])
        self.assertEqual(code, 0, err)
        plan = json.loads(out)
        self.assertEqual(plan["atr_bars"], 8)
        self.assertLess(plan["stop"], 1311.30)
        self.assertEqual(round(plan["stop"] * 10) / 10.0, plan["stop"])   # on the 0.10 tick

    def test_shorts_are_refused(self):
        code, _, err = run(["plan", "--symbol", "RELIANCE", "--entry", "1311.3", "--side", "short", "--stop",
                            "pct:1", "--now", NOW])
        self.assertEqual(code, 1)
        self.assertIn("longs only", err)

    def test_show(self):
        self.entry_json()
        run(["plan", "--target", "1R", "--now", NOW, "--write"])
        code, out, _ = run(["show", "--now", NOW])
        self.assertEqual(code, 0)
        self.assertIn("RELIANCE long", out)


if __name__ == "__main__":
    unittest.main()

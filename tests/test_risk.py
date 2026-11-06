"""trader-risk tests, NSE edition."""

import copy
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, ROOT, FIX

risk = load("trader-risk", "check")

with open(os.path.join(ROOT, "trader-budget", "config.example.json")) as _fh:
    CFG = json.load(_fh)
NOW = risk.parse_now("2026-11-05 10:00")
ORDER = {"symbol": "RELIANCE", "exchange": "NSE", "side": "buy", "qty": "57", "type": "market",
         "time_in_force": "day", "product": "MIS", "order_class": "bracket", "take_profit_limit_price": "1318.50",
         "stop_loss_stop_price": "1304.10",
         "plan": {"entry": 1311.3, "stop": 1304.1, "target": 1318.5, "risk_per_share": 7.2, "max_loss": 483.82}}


def check(orders=None, cfg=None, now=NOW, **kw):
    return risk.check(orders if orders is not None else [ORDER], dict(CFG, **(cfg or {})), now=now, **kw)


def order(**kw):
    o = copy.deepcopy(ORDER)
    for k, v in kw.items():
        if v is None:
            o.pop(k, None)
        else:
            o[k] = v
    return o


def reasons(res, i=0):
    return " | ".join(res["results"][i]["reasons"])


class Pass(unittest.TestCase):
    def test_the_reliance_bracket_passes(self):
        res = check()
        r = res["results"][0]
        self.assertEqual(r["verdict"], "PASS", reasons(res))
        self.assertEqual(r["max_loss"], 483.82)
        self.assertEqual(r["risk_per_share"], 7.2)
        self.assertEqual(r["kind"], "entry")
        self.assertEqual(r["value_inr"], 74744.1)

    def test_the_fingerprint_covers_product_and_exchange(self):
        a = risk.fingerprint(ORDER)
        self.assertNotEqual(a, risk.fingerprint(order(product="CNC")))
        self.assertNotEqual(a, risk.fingerprint(order(exchange="BSE")))
        self.assertEqual(a, risk.fingerprint(order(why="a note")))     # notes are not in it


class Format(unittest.TestCase):
    def test_notional_and_fractions_are_blocked(self):
        self.assertIn("whole shares", reasons(check([order(qty=None, notional="5000")])))
        self.assertIn("whole shares only", reasons(check([order(qty="2.5")])))
        self.assertIn("give qty", reasons(check([order(qty=None)])))

    def test_products(self):
        self.assertIn("product", reasons(check([order(product="NRML")])))
        res = check([order(product="CNC")])
        self.assertEqual(res["results"][0]["verdict"], "PASS")
        self.assertTrue(any("delivery" in w for w in res["results"][0]["warnings"]))

    def test_types_and_tifs(self):
        self.assertIn("unknown order type", reasons(check([order(type="trailing_stop")])))
        self.assertIn("time_in_force", reasons(check([order(time_in_force="gtc")])))
        self.assertIn("limit_price", reasons(check([order(type="limit")])))
        self.assertIn("bracket", reasons(check([order(stop_loss_stop_price=None)])))


class Assets(unittest.TestCase):
    def test_nse_symbols_pass(self):
        for sym in ("M&M", "BAJAJ-AUTO", "3MINDIA"):
            res = check([order(symbol=sym)], cfg={"max_position_pct": 100})
            self.assertNotIn("asset", reasons(res), sym)

    def test_futures_and_options_are_off(self):
        for sym in ("RELIANCE26NOVFUT", "NIFTY26NOV24000CE", "BANKNIFTY2611225000PE", "RELIANCE26NOV1300PE"):
            self.assertIn("F&O is off", reasons(check([order(symbol=sym)])), sym)

    def test_not_an_nse_symbol(self):
        for sym in ("BTC/INR", "AAPL US", "RELIANCE.NS", "#1"):
            self.assertIn("asset", reasons(check([order(symbol=sym)])), sym)


class DayTrade(unittest.TestCase):
    def test_the_loss_counts_the_charges(self):
        res = check(cfg={"max_loss_per_trade_inr": 450})
        self.assertIn("57 shares x 7.20 risk a share + ₹73.42 charges = ₹483.82 at the stop", reasons(res))

    def test_no_stop(self):
        o = order(stop_loss_stop_price=None, order_class=None, take_profit_limit_price=None)
        o["plan"] = {"entry": 1311.3}
        self.assertIn("stop: no stop", reasons(check([o])))

    def test_reward_risk(self):
        o = order(take_profit_limit_price="1314.00")
        o["plan"] = dict(o["plan"], target=1314.0)
        self.assertIn("reward:risk", reasons(check([o])))

    def test_the_daily_loss_and_the_trade_count(self):
        state = {"orders": [{"status": "placed", "date": "2026-11-05", "symbol": "TCS", "side": "buy",
                             "kind": "entry", "max_loss": 1200.0}]}
        self.assertIn("daily loss", reasons(check(state=state)))
        state = {"orders": [{"status": "placed", "date": "2026-11-05", "symbol": s, "side": "buy", "kind": "entry",
                             "max_loss": 10.0} for s in ("TCS", "INFY", "ITC")]}
        self.assertIn("trades: 3 entries placed today", reasons(check(state=state)))

    def test_the_entry_window_is_ist(self):
        self.assertIn("no new entries before 09:30", reasons(check(now=risk.parse_now("2026-11-05 09:25"))))
        self.assertIn("no new entries after 14:45", reasons(check(now=risk.parse_now("2026-11-05 14:50"))))
        self.assertEqual(check(now=risk.parse_now("2026-11-05 14:45"))["results"][0]["verdict"], "PASS")

    def test_closed_on_weekends_holidays_and_outside_hours(self):
        self.assertIn("weekend", reasons(check(now=risk.parse_now("2026-11-08 10:00"))))    # Muhurat Sunday
        self.assertIn("NSE holiday: Diwali Balipratipada", reasons(check(now=risk.parse_now("2026-11-10 10:00"))))
        self.assertIn("market is closed", reasons(check(now=risk.parse_now("2026-11-05 15:40"), cfg={
            "no_entries_after": None})))
        self.assertIn("NSE holiday: Prakash Gurpurb", reasons(check(now=risk.parse_now("2026-11-24 11:00"))))

    def test_the_holiday_list_warns_outside_2026(self):
        res = check(now=risk.parse_now("2027-01-05 10:00"))
        self.assertTrue(any("nseindia.com" in w for w in res["warnings"]))

    def test_an_exit_is_never_blocked_by_the_day_limits(self):
        pf = {"cash": 25255.9, "positions": [{"ticker": "RELIANCE", "shares": 57}]}
        sell = {"symbol": "RELIANCE", "exchange": "NSE", "side": "sell", "qty": "57", "type": "market",
                "time_in_force": "day", "product": "MIS"}
        res = check([sell], portfolio=pf, now=risk.parse_now("2026-11-05 15:05"), prices={"RELIANCE": 1318.5})
        self.assertEqual(res["results"][0]["verdict"], "PASS", reasons(res))
        self.assertEqual(res["results"][0]["kind"], "exit")

    def test_selling_short_is_off(self):
        sell = order(side="sell", order_class=None, take_profit_limit_price=None, stop_loss_stop_price=None)
        self.assertIn("short", reasons(check([sell])))


class Account(unittest.TestCase):
    def test_cash_buffer_and_position_cap(self):
        self.assertIn("cash", reasons(check([order(qty="70")], cfg={"max_order_inr": 200000,
                                                                     "max_loss_per_trade_inr": 5000,
                                                                     "max_position_pct": 100})))
        self.assertIn("position", reasons(check([order(qty="60")], cfg={"max_loss_per_trade_inr": 5000,
                                                                         "max_daily_loss_inr": 9000})))

    def test_order_size_limits(self):
        self.assertIn("max order", reasons(check(cfg={"max_order_inr": 50000})))
        self.assertIn("minimum order", reasons(check([order(qty="1")], cfg={"min_order_inr": 5000})))

    def test_a_live_account_warns(self):
        res = check(cfg={"paper": False})
        self.assertTrue(any("LIVE" in w for w in res["warnings"]))


class Cli(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.dir)
        os.makedirs("trader")
        shutil.copy(os.path.join(ROOT, "trader-budget", "config.example.json"), "trader/config.json")
        with open("trader/orders.json", "w") as fh:
            json.dump({"orders": [ORDER]}, fh)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.dir)

    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = risk.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_pass_writes_the_verdicts(self):
        code, out, err = self.run_cli(["--now", "2026-11-05 10:00"])
        self.assertEqual(code, 0, err)
        self.assertIn("PASS  #1 buy RELIANCE 57 shares, entry", out)
        self.assertIn("max loss ₹483.82 (limit ₹500)", out)
        self.assertIn("(paper account)", out)
        with open("trader/state/risk.json") as fh:
            doc = json.load(fh)
        self.assertEqual(doc["results"][0]["fingerprint"], risk.fingerprint(ORDER))

    def test_block_exits_1(self):
        code, out, _ = self.run_cli(["--now", "2026-11-05 15:00", "--no-write"])
        self.assertEqual(code, 1)
        self.assertIn("BLOCK #1", out)


if __name__ == "__main__":
    unittest.main()

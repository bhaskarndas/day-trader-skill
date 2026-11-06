"""trader-budget tests, NSE edition: rupees, whole shares, Indian charges in the max loss."""

import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, ROOT, FIX

size = load("trader-budget", "size")

CFG_PATH = os.path.join(ROOT, "trader-budget", "config.example.json")
PLAN_PATH = os.path.join(FIX, "trader-budget", "plan-reliance.json")
TOP5 = os.path.join(FIX, "trader-budget", "nifty-top5.json")
NOW = "2026-11-05 10:00"
TODAY = "2026-11-05"
with open(CFG_PATH) as _fh:
    CFG = json.load(_fh)
with open(PLAN_PATH) as _fh:
    PLAN = json.load(_fh)
PRICES = {"RELIANCE": 1311.30, "HDFCBANK": 992.40, "TCS": 3051.20, "INFY": 1482.60, "ITC": 412.35}


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = size.main(argv)
    return code, out.getvalue(), err.getvalue()


class Charges(unittest.TestCase):
    def test_the_intraday_charges_on_the_reliance_trade(self):
        c = size.charges(57 * 1311.30, 57 * 1304.10)
        self.assertEqual(c, {"brokerage": 40.0, "stt": 18.58, "exchange": 4.43, "sebi": 0.15, "stamp": 2.24,
                             "gst": 8.02, "total": 73.42})

    def test_brokerage_is_capped_at_20_an_order_and_small_orders_pay_the_percent(self):
        self.assertEqual(size.charges(10000, 10000)["brokerage"], 6.0)     # 0.03% of each side
        self.assertEqual(size.charges(500000, 500000)["brokerage"], 40.0)
        self.assertEqual(size.charges(0, 0)["total"], 0.0)

    def test_stt_on_the_sell_stamp_on_the_buy(self):
        c = size.charges(100000, 0)
        self.assertEqual((c["stt"], c["stamp"]), (0.0, 3.0))
        c = size.charges(0, 100000)
        self.assertEqual((c["stt"], c["stamp"]), (25.0, 0.0))

    def test_rates_from_the_config_override_the_defaults(self):
        rates = size.charge_rates({"charges": {"brokerage_max_per_order": 0, "stt_sell_pct": 0.1}})
        c = size.charges(100000, 100000, rates)
        self.assertEqual((c["brokerage"], c["stt"]), (0.0, 100.0))
        self.assertEqual(size.charge_rates({"charges": {"nonsense": 5, "gst_pct": -1}}), size.CHARGES)

    def test_shares_after_charges(self):
        self.assertEqual(size.shares_after_charges(500, 1311.30, 1304.10, size.CHARGES), 59)
        self.assertEqual(int(500 // 7.2), 69)    # without charges it would have been 69
        self.assertEqual(size.shares_after_charges(10, 1311.30, 1304.10, size.CHARGES), 1)   # 7.20 + ₹1.38
        self.assertEqual(size.shares_after_charges(8, 1311.30, 1304.10, size.CHARGES), 0)


class Money(unittest.TestCase):
    def test_inr(self):
        self.assertEqual(size.money(100000), "₹1,00,000")
        self.assertEqual(size.money(74744.1), "₹74,744.10")
        self.assertEqual(size.inr(12345678.9, paise=True), "₹1,23,45,678.90")


class PlanMode(unittest.TestCase):
    def sized(self, **kw):
        args = dict(cfg=CFG, today=TODAY)
        args.update(kw)
        return size.size_trade(PLAN, **args)

    def test_reliance_is_57_shares_bound_by_the_position_cap(self):
        s = self.sized()
        self.assertEqual((s["qty"], s["bound_by"]), (57, "position cap"))
        self.assertEqual(s["cost"], 74744.10)
        self.assertEqual(s["charges_at_stop"]["total"], 73.42)
        self.assertEqual(s["max_loss"], 483.82)
        self.assertEqual(s["net_gain_at_target"], 336.74)
        self.assertEqual(s["net_reward_risk"], 0.70)
        self.assertEqual(s["break_even_move"], 1.29)
        limits = {l["name"]: l["shares"] for l in s["limits"]}
        self.assertEqual(limits, {"max loss": 59, "position cap": 57, "max order": 61, "cash": 68})

    def test_the_max_loss_binds_with_a_wider_stop(self):
        s = size.size_trade(dict(PLAN, stop=1296.0, target=1326.6), CFG, today=TODAY)
        self.assertEqual(s["bound_by"], "max loss")
        self.assertLessEqual(s["max_loss"], 500)
        self.assertGreater(s["max_loss"], 500 - 15.3 - 5)          # one more share would break it

    def test_the_bracket_order(self):
        s = self.sized()
        o = size.bracket_order(s)
        self.assertEqual({k: o[k] for k in ("symbol", "exchange", "side", "qty", "type", "time_in_force", "product",
                                            "order_class", "take_profit_limit_price", "stop_loss_stop_price")},
                         {"symbol": "RELIANCE", "exchange": "NSE", "side": "buy", "qty": "57", "type": "market",
                          "time_in_force": "day", "product": "MIS", "order_class": "bracket",
                          "take_profit_limit_price": "1318.50", "stop_loss_stop_price": "1304.10"})
        self.assertEqual(o["plan"]["max_loss"], 483.82)
        self.assertEqual(o["plan"]["charges_at_stop"], 73.42)
        self.assertIn("+ charges", o["why"])

    def test_a_limit_order(self):
        s = self.sized(limit=1310.0)
        o = size.bracket_order(s)
        self.assertEqual((o["type"], o["limit_price"]), ("limit", "1310.00"))
        self.assertEqual(s["entry_from"], "limit")

    def test_a_fresh_higher_price_means_a_bigger_risk(self):
        s = self.sized(price=1313.0)
        self.assertEqual((s["entry"], s["entry_from"]), (1313.0, "price"))
        self.assertEqual(s["risk_per_share"], 8.9)

    def test_zero_shares_is_a_plain_refusal(self):
        s = size.size_trade(PLAN, dict(CFG, max_loss_per_trade_inr=5), today=TODAY)
        self.assertEqual(s["qty"], 0)
        self.assertIn("plus charges", s["refusal"])
        self.assertIsNone(size.bracket_order(s))

    def test_reward_risk_under_the_minimum(self):
        s = size.size_trade(dict(PLAN, target=1314.0), CFG, today=TODAY)
        self.assertIn("reward:risk", s["refusal"])

    def test_bad_plans(self):
        for bad in (dict(PLAN, side="sell"), dict(PLAN, stop=1320), dict(PLAN, symbol=""), dict(PLAN, target=1300)):
            with self.assertRaises(size.SizeError):
                s = size.size_trade(bad, CFG, today=TODAY)
                if s["refusal"]:
                    raise size.SizeError(s["refusal"])
        with self.assertRaises(size.SizeError):
            size.size_trade(PLAN, CFG, today="2026-11-06")       # yesterday's plan
        with self.assertRaises(size.SizeError):
            size.size_trade(PLAN, dict(CFG, blocked=["RELIANCE"]), today=TODAY)

    def test_the_report(self):
        s = self.sized()
        text = size.plan_report(s, size.bracket_order(s))
        self.assertIn("Max loss at the stop: 57 x 7.20 + ₹73.42 charges = ₹483.82.", text)
        self.assertIn("Charges at the stop: brokerage ₹40, STT ₹18.58, exchange ₹4.43, SEBI ₹0.15, stamp ₹2.24, "
                      "GST ₹8.02.", text)
        self.assertIn("Reward:risk after charges 0.70.", text)
        self.assertIn("buy 57 RELIANCE on NSE, market, MIS, day, take-profit 1318.50, stop-loss 1304.10", text)
        self.assertIn("not financial advice", text.lower())


class WeightsMode(unittest.TestCase):
    def test_whole_shares_need_prices(self):
        rows = size.parse_weights(size.weights_from_arg("RELIANCE=25,TCS=20"))
        with self.assertRaises(size.SizeError):
            size.size(rows, dict(CFG, budget=100000))

    def test_a_split_in_whole_shares_as_cnc_orders(self):
        with open(TOP5) as fh:
            rows = size.parse_weights(json.load(fh))
        res = size.size(rows, dict(CFG, budget=100000, max_position_pct=40), prices=PRICES)
        orders = size.orders_from(res)
        self.assertEqual([o["symbol"] for o in orders], ["RELIANCE", "HDFCBANK", "TCS", "INFY", "ITC"])
        for o in orders:
            self.assertEqual((o["exchange"], o["product"], o["type"]), ("NSE", "CNC", "market"))
            self.assertNotIn("notional", o)
            self.assertEqual(o["qty"], str(int(o["qty"])))
        spent = sum(int(o["qty"]) * PRICES[o["symbol"]] for o in orders)
        self.assertLessEqual(spent, 90000 + 0.01)                  # never into the 10% cash buffer


class Cli(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.dir)
        os.makedirs("trader")
        shutil.copy(CFG_PATH, "trader/config.json")
        shutil.copy(PLAN_PATH, "trader/plan.json")

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.dir)

    def test_cli_writes_one_bracket_order(self):
        code, out, err = run(["--now", NOW, "--write"])
        self.assertEqual(code, 0, err)
        with open("trader/orders.json") as fh:
            doc = json.load(fh)
        self.assertEqual(len(doc["orders"]), 1)
        self.assertEqual(doc["orders"][0]["qty"], "57")
        self.assertIn("Wrote 1 proposed bracket order", out)

    def test_cli_json(self):
        code, out, _ = run(["--now", NOW, "--json"])
        self.assertEqual(code, 0)
        doc = json.loads(out)
        self.assertEqual(doc["sizing"]["charges_at_target"]["total"], 73.66)

    def test_a_stale_plan_is_refused(self):
        code, _, err = run(["--now", "2026-11-06 10:00"])
        self.assertEqual(code, 1)
        self.assertIn("today is 2026-11-06", err)


if __name__ == "__main__":
    unittest.main()

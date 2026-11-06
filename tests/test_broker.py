"""trader-broker tests, NSE edition: tickets, an explicit yes, paper fills with charges."""

import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, ROOT

tk = load("trader-broker", "ticket")
risk = load("trader-risk", "check")

ORDER = {"symbol": "RELIANCE", "exchange": "NSE", "side": "buy", "qty": "57", "type": "market",
         "time_in_force": "day", "product": "MIS", "order_class": "bracket", "take_profit_limit_price": "1318.50",
         "stop_loss_stop_price": "1304.10", "why": "opening-range breakout on RELIANCE",
         "plan": {"entry": 1311.3, "stop": 1304.1, "target": 1318.5, "risk_per_share": 7.2, "max_loss": 483.82,
                  "flat_by": "15:10"}}
NOW = "2026-11-05 10:01"


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = tk.main(argv)
    return code, out.getvalue(), err.getvalue()


class Pure(unittest.TestCase):
    def test_the_fingerprint_matches_trader_risk(self):
        self.assertEqual(tk.ORDER_FIELDS, risk.ORDER_FIELDS)
        self.assertEqual(tk.fingerprint(ORDER), risk.fingerprint(ORDER))

    def test_the_plain_ticket(self):
        self.assertEqual(tk.plain(ORDER), "BUY 57 RELIANCE on NSE, market, intraday (MIS), good for today / "
                                          "stop-loss 1304.10 / take-profit 1318.50 / max loss about ₹483.82 if the "
                                          "stop fills at 1304.10 (it can fill worse in a fast market)")

    def test_leg_charges(self):
        buy = tk.leg_charges("buy", 74749.8, tk.CHARGES)
        self.assertEqual((buy["brokerage"], buy["stt"], buy["stamp"]), (20.0, 0.0, 2.24))
        sell = tk.leg_charges("sell", 75154.5, tk.CHARGES)
        self.assertEqual((sell["brokerage"], sell["stt"], sell["stamp"]), (20.0, 18.79, 0.0))
        self.assertEqual(round(buy["total"] + sell["total"], 2), 73.66)

    def test_yes_rules(self):
        others = ["RELIANCE", "TCS"]
        self.assertTrue(tk.parse_yes("yes", ORDER, others)[0])
        self.assertTrue(tk.parse_yes("yes, 57 RELIANCE", ORDER, others)[0])
        for bad in ("ok", "sure", "yes to all", "yes but wait", "yes TCS", "yes 60", "yes?", ""):
            self.assertFalse(tk.parse_yes(bad, ORDER, others)[0], bad)

    def test_symbols_with_ampersand_in_a_reply(self):
        o = dict(ORDER, symbol="M&M")
        self.assertFalse(tk.parse_yes("yes RELIANCE", o, ["M&M", "RELIANCE"])[0])
        self.assertTrue(tk.parse_yes("yes M&M", o, ["M&M", "RELIANCE"])[0])

    def test_ist_iso(self):
        self.assertEqual(tk.ist_iso(tk.parse_now("2026-11-05 10:01")), "2026-11-05T10:01:00+05:30")


class Flow(unittest.TestCase):
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

    def risk_check(self, now="2026-11-05 10:00"):
        out = io.StringIO()
        with redirect_stdout(out):
            return risk.main(["--now", now])

    def test_not_ready_until_trader_risk_passes(self):
        code, out, _ = run(["show", "--now", NOW])
        self.assertEqual(code, 1)
        self.assertIn("NOT READY", out)
        code, _, err = run(["approve", "--index", "1", "--reply", "yes", "--now", NOW])
        self.assertEqual(code, 1)
        self.assertIn("not ready", err)

    def test_show_is_paper_only(self):
        self.risk_check()
        code, out, _ = run(["show", "--now", NOW])
        self.assertEqual(code, 0)
        self.assertIn("PAPER account (simulated fills, no broker)", out)
        self.assertIn("READY: trader-risk PASS", out)
        self.assertIn("Reply \"yes\" to fill this one order on paper", out)
        doc = json.loads(run(["show", "--index", "1", "--json", "--now", NOW])[1])
        self.assertEqual((doc["broker"], doc["paper"], doc["ready"]), ("paper", True, True))

    def test_approve_fills_on_paper_then_the_target_fills(self):
        self.risk_check()
        code, out, err = run(["approve", "--index", "1", "--reply", "yes", "--price", "1311.40", "--now", NOW])
        self.assertEqual(code, 0, err)
        self.assertIn("PAPER fill: BUY 57 RELIANCE at 1311.40 (your --price). Charges ₹28.54. Cash now ₹25,221.66.", out)
        with open("trader/portfolio.json") as fh:
            pf = json.load(fh)
        self.assertEqual(pf["positions"][0]["shares"], 57.0)
        self.assertEqual(pf["positions"][0]["lots"][0]["cost"], 74778.34)     # the buy's charges in the basis
        with open("trader/state/broker.json") as fh:
            st = [r["status"] for r in json.load(fh)["orders"]]
        self.assertEqual(st, ["approved", "placed", "filled"])
        code, out, _ = run(["fill", "--symbol", "RELIANCE", "--side", "sell", "--qty", "57", "--price", "1318.50",
                            "--now", "2026-11-05 11:40"])
        self.assertEqual(code, 0)
        self.assertIn("Charges ₹45.12. Cash now ₹1,00,331.04. Realized P&L so far ₹331.04.", out)
        with open("trader/portfolio.json") as fh:
            pf = json.load(fh)
        self.assertEqual((pf["positions"], pf["realized_pnl"], pf["charges_paid"]), ([], 331.04, 73.66))

    def test_a_second_yes_is_refused(self):
        self.risk_check()
        run(["approve", "--index", "1", "--reply", "yes", "--price", "1311.40", "--now", NOW])
        code, _, err = run(["approve", "--index", "1", "--reply", "yes", "--now", NOW])
        self.assertEqual(code, 1)
        self.assertIn("DONE", err)

    def test_the_paper_price_falls_back_to_the_plan(self):
        self.risk_check()
        code, out, _ = run(["approve", "--index", "1", "--reply", "yes", "--now", NOW])
        self.assertEqual(code, 0)
        self.assertIn("at 1311.30 (the plan's entry", out)

    def test_a_fresh_price_is_used(self):
        self.risk_check()
        with open("trader/prices.json", "w") as fh:
            json.dump({"as_of": "2026-11-05T04:30:30Z", "prices": {"RELIANCE": 1311.9}}, fh)
        code, out, _ = run(["approve", "--index", "1", "--reply", "yes", "--now", NOW])
        self.assertIn("at 1311.90 (the latest price in trader/prices.json)", out)

    def test_a_vague_reply_is_not_recorded(self):
        self.risk_check()
        code, out, _ = run(["approve", "--index", "1", "--reply", "sure", "--now", NOW])
        self.assertEqual(code, 1)
        self.assertIn("Not recorded", out)
        self.assertFalse(os.path.exists("trader/portfolio.json"))

    def test_decline(self):
        self.risk_check()
        code, out, _ = run(["decline", "--index", "1", "--now", NOW])
        self.assertEqual(code, 0)
        self.assertIn("Nothing was sent", out)

    def test_flatten_and_log(self):
        self.risk_check()
        run(["approve", "--index", "1", "--reply", "yes", "--price", "1311.40", "--now", NOW])
        code, out, _ = run(["flatten", "--symbol", "RELIANCE", "--now", "2026-11-05 15:05"])
        self.assertEqual(code, 0)
        self.assertIn("SELL 57 shares of RELIANCE on NSE, market order, intraday (MIS), good for today", out)
        with open("trader/orders.json") as fh:
            o = json.load(fh)["orders"][0]
        self.assertEqual((o["side"], o["qty"], o["product"], o["exchange"]), ("sell", "57", "MIS", "NSE"))
        self.assertIn("15:10", o["why"])
        code, out, _ = run(["log", "--now", "2026-11-05 15:06"])
        self.assertEqual(code, 0)
        self.assertIn("1 placed today.", out)


if __name__ == "__main__":
    unittest.main()

---
name: trader-exit
description: >-
  Exit Planner for NSE day trades. Sets the stop and the target BEFORE you
  enter, so you know when to get out: a stop at the opening-range midpoint,
  the range low, a percent, a price or an ATR multiple, rounded down to the
  NSE tick (0.01 under ₹250, 0.05 to ₹1,000, 0.10 to ₹5,000, 0.50 to
  ₹10,000, 1.00 to ₹20,000, 5.00 above); a target in R multiples or a price,
  on the tick; and a flat-by time (default 15:10 IST, before the broker's
  intraday square-off). Writes trader/plan.json for trader-timemachine and
  trader-budget. Long side only. Use when the user says "where is my stop",
  "set my stop and target", "plan the exit", "what is my risk", "2R target",
  "when do I get out", or after /trader-entry triggers and before
  /trader-timemachine.
argument-hint: "[--stop or-mid|or-low|pct:X|price:X|atr:K] [--target 1R|2R|price:X]"
---

# trader-exit

The Exit Planner writes down the way out before the way in. Once the stop is
set it is never moved further away. It never places an order.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan                                  # from trader/entry.json: or-mid stop, 2R
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --stop or-mid --target 1R --write
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --symbol RELIANCE --entry 1311.30 --or-high 1309.30 --or-low 1298.90
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --stop atr:1.5                   # ATR on the session's bars to the entry
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --symbol INFY --entry 1482.60 --setup level --stop pct:1
python3 "${CLAUDE_SKILL_DIR}/exit.py" show
```

`--now "2026-11-05 10:00"` (IST) pins the clock; `--offline FILE` gives the
ATR stop a saved chart.

## Stops and targets

| stop | where |
| --- | --- |
| `or-mid` | the opening-range midpoint (the default for an orb entry) |
| `or-low` | the opening-range low |
| `pct:X` | X percent under the entry |
| `price:X` | your price (₹ and commas are fine: `price:₹1,300`) |
| `atr:K` | K times the 14-bar ATR under the entry, on the session's bars up to the entry bar |

A long's stop rounds DOWN to the NSE tick, away from the entry. A target is
`1R`, `1.5R`, `2R` ... (entry + R x risk) or `price:X`, rounded half up to the
tick. NSE only accepts prices on the tick, so a plan off the tick would be
rejected by a broker.

Refused, with the reason: a stop at or above the entry, a target at or below
it, a risk under 0.05 % of the price (normal wiggle would stop you out), an
entry.json that has not triggered (unless you give `--entry`), a short.

**flat_by** (default 15:10 IST, or `"flat_by"` in trader/config.json): out by
then, win or lose. Brokers square off intraday (MIS) positions on their own
from about 15:15 to 15:25 IST and charge for it; 15:10 gets you out first.

`min_reward_risk` (default 1.0) only warns here; trader-risk enforces it.
Remember the charges: trader-budget shows the reward:risk after brokerage,
STT and the rest, and a 1R plan is closer to 0.7R once they are paid.

## What it writes

`trader/plan.json`: symbol, side, date, setup, entry, entry_time, entry_bar,
opening_range, stop, stop_rule, target, target_r, risk_per_share,
reward_risk, flat_by. trader-timemachine replays it; trader-budget sizes it;
trader-alerts watches its stop, target and flat-by time.

## Steps

1. Plan from `trader/entry.json` (or the flags). Use the user's stop rule if
   they gave one; otherwise or-mid for an orb.
2. Tell the user the entry, stop, target, risk a share in rupees and as a
   percent, and the flat-by time.
3. Hand on to `/trader-timemachine` to replay it, then `/trader-budget`.

## Example (the test fixtures: synthetic prices)

```
Exit plan: RELIANCE long, Thu 2026-11-05, opening-range breakout on 5-minute bars
  Entry         ₹1,311.30 at 9:55 AM (bar 7)
  Stop          ₹1,304.10  opening-range midpoint: (₹1,309.30 + ₹1,298.90) / 2 = ₹1304.1
  Target        ₹1,318.50  1R (one times the risk)
  Risk a share  ₹7.20 (0.55% of the entry)
  Flat by       15:10 IST, win or lose: no overnight hold (before your broker's MIS square-off)
```

## Rules

- Never move a stop further from the entry once set.
- Say that a stop is a plan, not a guarantee: a gap or a fast market (or a
  stock hitting its price band) can fill past it, or not fill at all.

## What it never does

It never places, sizes or checks an order, and never plans a short.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Paper trading only in this NSE edition (`"paper": true`, `"broker": "paper"`): no order reaches an exchange.
- Nothing in this pack fills an order except trader-broker, on paper, and only when both hold: trader-risk
  passed that exact order today, and the user typed an explicit yes for that one order in the chat.
- No futures and options, margin, short selling or leverage unless the config allows it and the user confirms.
- Intraday (MIS) trades are planned to be flat by 15:10 IST, before the broker's automatic square-off.

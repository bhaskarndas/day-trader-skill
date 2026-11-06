---
name: trader-risk
description: >-
  Risk Manager for NSE trades. Checks every order against your limits and
  stops anything over them, before it can reach the (paper) broker. For a
  day trade: a stop is required, the loss at the stop plus the round-trip
  charges (brokerage, STT, exchange, SEBI, stamp duty, GST) must fit your max
  loss per trade, reward:risk must meet your minimum, the day's total risk
  must fit your daily loss limit, no more than your trades per day, and no
  new entries outside your IST entry window (09:30 to 14:45 by default), on
  an NSE holiday or when the market is closed. It also checks NSE order
  rules: whole shares only, MIS or CNC, day or IOC, no futures and options
  (RELIANCE26NOVFUT, NIFTY26NOV24000CE) unless allowed, the cash buffer,
  position cap, margin, short sales and duplicates. Getting out is never
  blocked by a day limit. Prints PASS or BLOCK with the reason. Use when the
  user says "check my order", "is this safe", "risk check", "does this break
  my rules", "can I take this trade", "how much have I risked today", or
  before /trader-broker, always.
argument-hint: "[path to orders.json]"
---

# trader-risk

The Risk Manager is the gate between a proposal and the broker. Every order
written by trader-budget or trader-broker's flatten passes through it. A
BLOCK is final for that order: it does not go to the user for a yes, and it
does not get filled. Most people who day trade lose money. These limits keep
each loss and each day's losses small. They do not make a trade win.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/check.py"                           # trader/ files; writes trader/state/risk.json
python3 "${CLAUDE_SKILL_DIR}/check.py" --json
python3 "${CLAUDE_SKILL_DIR}/check.py" --no-write                # look without recording
python3 "${CLAUDE_SKILL_DIR}/check.py" --now "2026-11-05 10:00"  # pin the clock (IST)
```

## What it reads and writes

| file | what |
| --- | --- |
| `trader/orders.json` | the proposed orders (trader-budget, or trader-broker's flatten) |
| `trader/config.json` | the limits and the charge rates (trader-budget ships `config.example.json`) |
| `trader/portfolio.json` | cash and holdings; if missing, a fresh account funded with the budget |
| `trader/prices.json` | a fresh price raises the entry it measures risk from; also values holdings |
| `trader/state/broker.json` | what was placed today: duplicates, trades per day, daily loss |
| `trader/state/risk.json` | the verdicts it writes, with a fingerprint of each exact order |

## Entries and exits

An ENTRY opens or adds to a position. An EXIT only reduces what you hold.
Getting out must always be possible: an exit is checked for format, asset and
short sales only; every other rule turns into a warning for it.

## The checks

| check | blocks when |
| --- | --- |
| format | no symbol, side not buy or sell, no whole-share qty (NSE has no fractions and no rupee-amount orders), a product other than MIS or CNC, a type other than market, limit, stop (SL-M) or stop_limit (SL), a time_in_force other than day or ioc, a limit order with no limit price, a bracket that is not day or misses a leg |
| asset | an NSE futures or options symbol while `allow_options` is false; crypto or anything that is not an NSE equity symbol |
| short | a sell of more than you hold (`allow_short` false) |
| blocked | (entries) the symbol is on the `blocked` list |
| size | (entries) under `min_order_inr` or over `max_order_inr` |
| position | (entries) the stock would be over `max_position_pct` of the account |
| cash | (entries) the buy would leave less than the cash buffer, or need margin |
| stop | (entries) no stop while `require_stop` is true; a stop on the wrong side of the entry |
| loss | (entries) qty x (entry minus stop) + the charges at the stop, over `max_loss_per_trade_inr` |
| reward:risk | (entries) (target minus entry) / (entry minus stop) under `min_reward_risk` |
| daily loss | (entries) the max losses of today's entries plus this one, over `max_daily_loss_inr` |
| trades | (entries) `max_trades_per_day` entries already placed today |
| window | (entries) before `no_entries_before` or after `no_entries_after` (IST), or the market is closed: a weekend, an NSE holiday, outside 9:15 to 15:30 |
| duplicate | (entries) the same symbol and side twice in one batch, or already placed today |
| daily limit | (entries) `max_orders_per_day` orders already placed today |

Notes:

- **The entry it measures from**: the limit price for a limit order; for a
  market order the HIGHER of the plan's entry and a fresh price (under 15
  minutes old), so a stale plan cannot understate the risk.
- **The charges** use the same rates as trader-budget (`"charges"` in the
  config), so the two agree on the max loss to the paisa.
- **A CNC (delivery) order** passes with a warning: it is not squared off by
  the close, and its STT is 0.1 % on both sides.
- **The window** is IST, with the 2026 NSE trading holidays built in. For a
  date outside 2026 it warns that the holiday list is not known yet.
- India has no pattern-day-trader rule, so there is no PDT check.

## Steps

1. Run `check.py` after trader-budget writes the order.
2. Say PASS or BLOCK for each order with the reasons, word for word, and the
   max loss with the limit.
3. A BLOCK goes back to the user with the fix (a closer stop, fewer shares,
   another time). Never edit the order to slip it past a rule.
4. A PASS goes to `/trader-broker`, which still asks for a yes.

## Example (the test fixtures: synthetic prices)

```
PASS  #1 buy RELIANCE 57 shares, entry
          entry 1311.30 (the plan's entry), stop 1304.10, target 1318.50: risk 7.20 a share
          max loss ₹483.82 (limit ₹500), reward:risk 1.00 (min 1)
          today before this: 0 of 3 trades, ₹0 of ₹1,500 daily loss

1 passed, 0 blocked at 2026-11-05 10:00 IST. Cash after the passed orders: ₹25,255.90 (paper account).
```

The same order at 14:50 IST: `BLOCK ... window: no new entries after 14:45 IST (it is 14:50)`.

## Rules

- A BLOCK is final. Never suggest bypassing it by changing the config on the
  spot to let one order through.
- Say the numbers the check used (entry, stop, max loss, the day so far).

## What it never does

It never places or fills an order, never changes an order, and never
loosens a limit.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Paper trading only in this NSE edition (`"paper": true`, `"broker": "paper"`): no order reaches an exchange.
- Nothing in this pack fills an order except trader-broker, on paper, and only when both hold: trader-risk
  passed that exact order today, and the user typed an explicit yes for that one order in the chat.
- No futures and options, margin, short selling or leverage unless the config allows it and the user confirms.
- Intraday (MIS) trades are planned to be flat by 15:10 IST, before the broker's automatic square-off.

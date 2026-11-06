---
name: trader-budget
description: >-
  Budget Manager for NSE day trades. Sizes every position to your budget and
  your max loss per trade AFTER Indian trading charges: brokerage (0.03 %, at
  most ₹20 an order), STT (0.025 % of the sell), the NSE transaction charge,
  the SEBI fee, stamp duty and 18 % GST. Whole shares only, rupees with lakh
  grouping. Writes one bracket order (entry, stop-loss, take-profit, product
  MIS) to trader/orders.json and shows the charges at the stop and at the
  target, the reward:risk after charges and the move a share needs just to
  pay them. Also splits a budget across a list of NSE stocks by weight, in
  whole shares (delivery, CNC). Use when the user says "how many shares",
  "size this trade", "position size", "how much can I risk", "what are the
  charges", "brokerage and STT", "split ₹1 lakh across these", or after
  /trader-timemachine and before /trader-risk.
argument-hint: "[--limit PRICE] [--write]"
---

# trader-budget

The Budget Manager turns a plan into a number of shares so that one loss at
the stop, charges included, stays inside your limit. It writes a proposed
order. It never places anything: trader-risk checks it and trader-broker asks
you yes or no.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/size.py"                          # trader/plan.json + trader/config.json
python3 "${CLAUDE_SKILL_DIR}/size.py" --write                  # -> trader/orders.json
python3 "${CLAUDE_SKILL_DIR}/size.py" --limit 1311.00 --write  # a limit order
python3 "${CLAUDE_SKILL_DIR}/size.py" --now "2026-11-05 10:00" --json
python3 "${CLAUDE_SKILL_DIR}/size.py" --weights RELIANCE=25,HDFCBANK=20,TCS=20,INFY=20,ITC=15 \
    --budget 100000 --prices trader/prices.json
```

Copy `config.example.json` to `trader/config.json` and edit it. The keys:

- **budget** (₹1,00,000 in the example), **cash_buffer_pct** (10): the buffer
  stays in cash.
- **max_loss_per_trade_inr** (500): the most one trade may lose at the stop,
  charges included.
- **max_position_pct** (75), **max_order_inr** (80,000), **min_order_inr**
  (100).
- The day limits trader-risk enforces: **max_daily_loss_inr** (1,500),
  **max_trades_per_day** (3), **max_orders_per_day** (10),
  **no_entries_before** / **no_entries_after** (09:30 / 14:45 IST),
  **flat_by** (15:10), **min_reward_risk** (1.0), **require_stop** (true).
- **product**: `MIS` (intraday, the default) or `CNC` (delivery).
- **charges**: the rates below; change them to match your broker.
- **paper** (true) and **broker** (`paper`): this NSE edition fills on paper only.

## How many shares

| limit | shares |
| --- | --- |
| max loss | the most shares whose loss at the stop PLUS the round-trip charges fits `max_loss_per_trade_inr` |
| position cap | budget x `max_position_pct` / entry |
| max order | `max_order_inr` / entry |
| cash | (budget minus the buffer) / entry, and no more than the cash in trader/portfolio.json |

The smallest wins. The entry it sizes at: a limit order's limit price; for a
market order the plan's entry, or a fresh price (under 15 minutes old) in
trader/prices.json if it is higher. Zero shares, or a reward:risk under
`min_reward_risk`, is a plain refusal: no order is written.

## The charges (intraday equity on NSE, read 2026-11-06)

| charge | rate | on |
| --- | --- | --- |
| brokerage | 0.03 % of the order, at most ₹20 | each order (discount brokers) |
| STT | 0.025 % | the sell side |
| exchange transaction charge | 0.00297 % | buy + sell |
| SEBI turnover fee | ₹10 a crore | buy + sell |
| stamp duty | 0.003 % | the buy side |
| GST | 18 % | brokerage + exchange + SEBI fee |

Delivery (CNC) is different: STT is 0.1 % on both sides and stamp duty
0.015 %; put those rates under `"charges"` when you size delivery trades.
Rates change with budgets and brokers: check yours.

## Steps

1. Run it on today's plan. Tell the user the shares, which limit bound, the
   cost, and the max loss at the stop with the charges in it.
2. Say the charges at the stop and at the target, and the reward:risk after
   charges. On a small target the charges are a big slice: say so.
3. `--write` the order and hand on to `/trader-risk`.

## Example (the test fixtures: synthetic prices)

```
Limits (whole shares; the smallest one wins):
  max loss      ₹500 max loss, 7.20 risk a share + charges            59 shares
  position cap  75% of ₹1,00,000 = ₹75,000 / 1311.30                  57 shares  <- binds
  max order     ₹80,000 / 1311.30                                     61 shares
  cash          budget ₹1,00,000 minus the ₹10,000 cash buffer = ₹90,000 / 1311.30  68 shares

Size: 57 shares of RELIANCE = ₹74,744.10 at 1311.30. Max loss at the stop: 57 x 7.20 + ₹73.42 charges = ₹483.82.
Charges at the stop: brokerage ₹40, STT ₹18.58, exchange ₹4.43, SEBI ₹0.15, stamp ₹2.24, GST ₹8.02.
At the target: ₹410.40 gross - ₹73.66 charges = ₹336.74 net. Reward:risk after charges 0.70.
Each share has to move 1.29 just to pay the round trip's charges.

Proposed bracket order (nothing has been placed):
  buy 57 RELIANCE on NSE, market, MIS, day, take-profit 1318.50, stop-loss 1304.10
```

Without the charges the max-loss limit would have allowed 69 shares; with
them it is 59. A "1R" trade is 0.70R after charges.

## Weights mode

Splits a budget across a list of NSE stocks by weight (renormalised to 100,
capped at `max_position_pct`, the buffer kept in cash), in whole shares, as
delivery (CNC) market orders. It needs prices (`--prices trader/prices.json`,
from `alerts.py quote ... --write`). These are not day trades; they still go
through trader-risk and your yes.

## What it never does

It never places an order, never sizes a short, never uses margin, and never
calls a size safe: a stop can fill worse than its price.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Paper trading only in this NSE edition (`"paper": true`, `"broker": "paper"`): no order reaches an exchange.
- Nothing in this pack fills an order except trader-broker, on paper, and only when both hold: trader-risk
  passed that exact order today, and the user typed an explicit yes for that one order in the chat.
- No futures and options, margin, short selling or leverage unless the config allows it and the user confirms.
- Intraday (MIS) trades are planned to be flat by 15:10 IST, before the broker's automatic square-off.

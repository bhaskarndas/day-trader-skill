---
name: trader-broker
description: >-
  Order Executor for the NSE edition, PAPER ONLY. Shows each approved order
  as a plain ticket (a bracket shows its stop-loss, take-profit and the max
  loss at the stop, charges included), records your yes word for word, and
  fills the order on paper in trader/portfolio.json with the Indian charges
  (brokerage, STT, exchange, SEBI, stamp duty, GST) taken off your cash. No
  real broker is connected and no order reaches an exchange. Builds the sell
  ticket that closes a day trade by your flat-by time (15:10 IST, before the
  MIS square-off), records the stop or target fill when trader-alerts rings
  it, and keeps a realized P&L after charges. Use when the user says "place
  the order", "buy it", "execute", "fill it", "paper trade this", "close my
  position", "flatten", "get me out", "what did I make", or after
  /trader-risk passes.
argument-hint: "[order number]"
---

# trader-broker

In this NSE edition the Order Executor trades on **paper only**. It never
talks to a broker and never sends anything to NSE. That is on purpose: run the
whole pack on real prices for weeks, see the results after charges, and only
then decide, on your own, whether to trade real money elsewhere.

An order is filled on paper only after two gates, every time, for every order:

1. **trader-risk passed this exact order today** (matched by fingerprint).
2. **The user typed an explicit yes for this one order** in the chat.

No PASS, no yes, no fill.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/ticket.py" show                     # every ticket, READY or not
python3 "${CLAUDE_SKILL_DIR}/ticket.py" approve --index 1 --reply "yes"
python3 "${CLAUDE_SKILL_DIR}/ticket.py" approve --index 1 --reply "yes" --price 1311.40
python3 "${CLAUDE_SKILL_DIR}/ticket.py" fill --symbol RELIANCE --side sell --qty 57 --price 1318.50
python3 "${CLAUDE_SKILL_DIR}/ticket.py" flatten --symbol RELIANCE
python3 "${CLAUDE_SKILL_DIR}/ticket.py" log
```

`--now "2026-11-05 10:00"` (IST) pins the clock.

## What it reads and writes

| file | what |
| --- | --- |
| `trader/orders.json` | the proposed orders (trader-budget writes it; `flatten` replaces it) |
| `trader/state/risk.json` | trader-risk's verdicts; only a PASS from today is READY |
| `trader/state/broker.json` | every yes, no, paper placement and fill, with each entry's max loss |
| `trader/portfolio.json` | cash, shares, cost basis (charges included), `realized_pnl`, `charges_paid` |
| `trader/prices.json` | a fresh price (under 15 minutes old) for a market order's paper fill |
| `trader/plan.json` | the flat-by time for `flatten` |

## The paper fill

- **Price**: `--price` if given (the price the user saw on their screen),
  else a fresh price in trader/prices.json, else the plan's entry; a limit
  order fills at its limit. Say which one was used.
- **Charges** on each fill: brokerage 0.03 % of the order (at most ₹20), STT
  0.025 % of a sell, exchange 0.00297 %, SEBI ₹10 a crore, stamp duty 0.003 %
  of a buy, GST 18 % of brokerage + exchange + SEBI (`"charges"` in the config
  overrides them).
- **The bracket's legs** are not simulated tick by tick: trader-alerts rings
  the stop, the target and the flat-by time, and whichever happens first is
  recorded with `ticket.py fill --side sell`.
- A paper fill is kinder than the market: a real market order can fill worse,
  and a stop can fill past its price in a fast market or a gap.

## Steps: the entry

1. `ticket.py show`. Show the user the ticket in plain words: what, how many,
   the stop, the target, the max loss with charges, and that it is paper.
2. Ask for a yes for THIS order. Only a reply that starts with "yes" counts.
   "ok", "sure", "go", "do it", "yes to all", or a yes with a doubt or another
   stock in it is not a yes: ask again.
3. `ticket.py approve --index N --reply "<their words>"` (add `--price` if
   they gave the price on their screen). It records the yes and the paper fill.
4. Set the alerts: `/trader-alerts` (`alerts.py add --from-plan`).

## Steps: while it is open, and out by the close

1. When the stop or the target rings: `ticket.py fill --symbol S --side sell
   --qty Q --price P`. It prints the charges, the cash and the realized P&L.
2. At the flat-by time (15:10 IST) with the position still open:
   `ticket.py flatten --symbol S`, then `/trader-risk`, then a yes, then
   `approve`. A sell that only closes what you hold is never blocked by the
   day limits.
3. `ticket.py log` at the end of the day.

## Example (the test fixtures: synthetic prices)

```
ORDER 1 of 1, PAPER account (simulated fills, no broker)
  BUY 57 RELIANCE on NSE, market, intraday (MIS), good for today
  stop-loss 1304.10
  take-profit 1318.50
  max loss about ₹483.82 if the stop fills at 1304.10 (it can fill worse in a fast market)
  READY: trader-risk PASS, waiting for your yes

PAPER fill: BUY 57 RELIANCE at 1311.40 (your --price). Charges ₹28.54. Cash now ₹25,221.66.
PAPER fill: sell 57 RELIANCE at ₹1,318.50 on 2026-11-05. Charges ₹45.12. Cash now ₹1,00,331.04.
Realized P&L so far ₹331.04.
```

57 shares x ₹7.10 = ₹404.70 gross; ₹73.66 of charges; ₹331.04 net.

## What it never does

It never connects to a broker, never sends an order to NSE, never fills an
order trader-risk did not pass today, never fills without the user's own yes
for that order, and never counts one yes for a batch.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Paper trading only in this NSE edition (`"paper": true`, `"broker": "paper"`): no order reaches an exchange.
- Nothing in this pack fills an order except trader-broker, on paper, and only when both hold: trader-risk
  passed that exact order today, and the user typed an explicit yes for that one order in the chat.
- No futures and options, margin, short selling or leverage unless the config allows it and the user confirms.
- Intraday (MIS) trades are planned to be flat by 15:10 IST, before the broker's automatic square-off.
- No broker keys belong anywhere in this pack. If the user wants real trading, that is their own
  decision in their own broker's app, outside this skill.

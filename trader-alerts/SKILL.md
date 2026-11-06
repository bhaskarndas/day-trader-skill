---
name: trader-alerts
description: >-
  Price Alerts and the NSE clock. Rings when a price, a stop, a target, a
  percent move or the 9:15 IST opening bell hits, and at your flat-by time
  (15:10 IST by default, before the broker's intraday square-off), once per
  rule. Knows the NSE session (9:15 to 15:30 IST), the 2026 NSE trading
  holidays and the Diwali Muhurat session. Reads free delayed quotes from
  Yahoo (SYMBOL.NS) and writes trader/prices.json for trader-budget,
  trader-risk and trader-broker's paper fills. Use when the user says "alert
  me", "tell me when RELIANCE hits", "watch my stop", "remind me to get out",
  "is the market open", "is NSE open today", "is tomorrow a holiday", "get a
  quote", or right after /trader-broker fills an entry.
argument-hint: "[clock | quote SYMBOL | add | check | list]"
---

# trader-alerts

Price Alerts watch the numbers a plan cares about once a trade is open: the
stop, the target and the flat-by time. It also answers the simplest question
in trading: is the market open right now?

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/alerts.py" clock                       # is NSE open? next open
python3 "${CLAUDE_SKILL_DIR}/alerts.py" quote RELIANCE --write      # -> trader/prices.json
python3 "${CLAUDE_SKILL_DIR}/alerts.py" quote --holdings --write    # every symbol in your portfolio and plan
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --from-plan             # stop, target and flat-by from trader/plan.json
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --symbol RELIANCE --stop 1304.10
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --symbol ITC --pct 3
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --opening-bell
python3 "${CLAUDE_SKILL_DIR}/alerts.py" check                       # rings what hit, once; exit 1 if nothing rang
python3 "${CLAUDE_SKILL_DIR}/alerts.py" list
```

`--now "2026-11-05 15:10"` (IST) pins the clock; `--offline DIR` reads saved
quotes (`yahoo-SYMBOL.json`).

## Rule types

| type | rings when |
| --- | --- |
| `above` / `target` | the price is at or above `price` |
| `below` / `stop` | the price is at or below `price` |
| `pct_move` | the price moved `pct` percent or more from the previous close |
| `opening_bell` | NSE opened today (once per trading day) |
| `time` | the IST clock passed `at` (HH:MM) on a trading day (once per trading day) |

A rule with `date` is watched on that IST date only (rules from a plan are
for the plan's day). A price alert rings ONCE and stays quiet until reset,
unless it has `"rearm": true`.

## The NSE clock

- Normal session 9:15 to 15:30 IST, Monday to Friday. The pre-open auction
  (9:00 to 9:08) is not the session.
- The 2026 equity-segment trading holidays from NSE's circular (16 weekday
  closures, among them Holi, Good Friday, Diwali Balipratipada on 10 November
  and Christmas). NSE publishes the next year's list in December: outside 2026
  the clock says the holiday list is unknown.
- The Muhurat session on Diwali (Sunday 8 November 2026) has its timings set
  by an NSE circular; the clock mentions it but does not treat it as a
  regular session.
- India has no daylight saving: IST is always UTC+5:30.

## Quotes

Yahoo's chart endpoint, `SYMBOL.NS`: free, delayed, unofficial. Good for
alerts and sizing checks, never for timing an order. Each quote in
trader/prices.json carries its own time, so trader-budget and trader-risk
only use it while it is fresh (15 minutes).

## Steps

1. After a paper entry: `add --from-plan`. Tell the user the three rules
   (stop, target, flat by 15:10 IST).
2. While the trade is open, run `check` on a schedule the user sets (every
   minute or every few minutes). When a stop or target rings, hand on to
   `/trader-broker` (`ticket.py fill`). When the flat-by time rings, hand on
   to `ticket.py flatten`.
3. "Is the market open?" is `clock`: answer with the IST time and the next
   open if it is closed.

## Example (the test fixtures: synthetic quotes)

```
alerts.py clock --now "2026-11-08 18:00"
IST 2026-11-08 18:00 (Sunday): NSE closed, weekend.
Next open: 2026-11-09 09:15 IST.
Special session today: Muhurat trading (Diwali Laxmi Pujan) (timings by NSE circular).
```

## Rules

- Times in IST, prices in rupees.
- A ring is a prompt, not an order: nothing is sold until the user says yes in
  trader-broker.

## What it never does

It never places or fills an order, and never calls a delayed quote live.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Paper trading only in this NSE edition (`"paper": true`, `"broker": "paper"`): no order reaches an exchange.
- Nothing in this pack fills an order except trader-broker, on paper, and only when both hold: trader-risk
  passed that exact order today, and the user typed an explicit yes for that one order in the chat.
- No futures and options, margin, short selling or leverage unless the config allows it and the user confirms.
- Intraday (MIS) trades are planned to be flat by 15:10 IST, before the broker's automatic square-off.

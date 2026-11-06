---
name: trader-entry
description: >-
  Entry Timer for NSE day trades. Watches a setup bar by bar and says the
  moment to get in: an opening-range breakout (the first 5-minute close above
  the 9:15 to 9:30 IST range high) or the first close above a level. Reads
  free Yahoo bars (SYMBOL.NS), counts a bar only once it has closed, drops
  the live tick, knows the NSE session (9:15 to 15:30 IST) and the 2026 NSE
  holidays, honours your entry window (default 09:30 to 14:45 IST) and writes
  trader/entry.json for trader-exit. Use when the user says "when do I get
  in", "watch RELIANCE", "tell me when it breaks out", "time my entry", "has
  it triggered", "watch my watchlist", or after /trader-news and before
  /trader-exit.
argument-hint: "SYMBOL [--setup orb|level] [--level PRICE]"
---

# trader-entry

The Entry Timer says the moment a setup triggers, and nothing else. It does
not say whether to take the trade. It never places an order. A trigger is a
close above a line on a chart; most trades that trigger still lose, which is
why trader-exit and trader-timemachine come next.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/entry.py" check RELIANCE                   # orb, 5-minute bars
python3 "${CLAUDE_SKILL_DIR}/entry.py" check RELIANCE --write           # -> trader/entry.json when triggered
python3 "${CLAUDE_SKILL_DIR}/entry.py" check INFY --setup level --level 1495.00
python3 "${CLAUDE_SKILL_DIR}/entry.py" check TCS --interval 1m --min-volume-x 1.5
python3 "${CLAUDE_SKILL_DIR}/entry.py" watch RELIANCE --every 30 --until 14:45
python3 "${CLAUDE_SKILL_DIR}/entry.py" watchlist                         # every hit in trader/watchlist.json
```

`--now "2026-11-05 10:00"` (IST) pins the clock and `--offline FILE` replays a
saved chart; together they replay a day without waiting.

## Setups

- **orb**: the range is the high and low of the first `--or-minutes` (15:
  the 9:15, 9:20 and 9:25 five-minute bars). It triggers on the first
  COMPLETED bar after the range that CLOSES above the range high. A wick above
  the high is not a trigger.
- **level**: the first completed bar that closes above `--level`.
- `--min-volume-x X`: the trigger bar also needs X times the average volume
  of the opening-range bars (the 9:15 bar carries the pre-open auction's
  orders, so 1.0 is already a high bar).

A trigger's time is the bar's CLOSE time (the 9:50 bar closes at 9:55 AM) and
its price is that close.

## Statuses

| status | meaning |
| --- | --- |
| triggered | a bar closed above; time and price given |
| waiting | not open yet, range still forming, or no close above yet |
| expired | no trigger by `no_entries_after` (default 14:45 IST) |
| no-data | an NSE holiday or weekend, or Yahoo sent no bars |

`no_entries_before` (09:30) and `no_entries_after` (14:45) come from
`trader/config.json`. 14:45 leaves time to hold a trade and still be flat by
15:10, before brokers square off intraday positions (about 15:15 to 15:25).

## Steps

1. Run `check SYMBOL` (or `watch` to follow it bar by bar).
2. Say the status in one line, with the time in IST and the price in rupees.
3. If it triggered, say how many minutes ago: a late entry is a different
   trade at a worse price. Write `trader/entry.json` with `--write`.
4. Hand on to `/trader-exit` to set the stop and target BEFORE buying.

## Example (the test fixtures: synthetic prices on the real NSE calendar)

```
RELIANCE  Thu 2026-11-05 10:00 IST  opening-range breakout (15-minute range) on 5-minute bars (Yahoo, free, can lag)
Opening range 9:15-9:30: high ₹1309.30, low ₹1298.90 (3 of 3 bars).
TRIGGERED 9:55 AM at ₹1311.30: the 9:50 bar (bar 7) closed above the range high ₹1309.30 (+0.15%).
```

At 9:52 the same file says WAITING: the 9:50 bar was still forming.

## Rules

- Times in IST. Prices in rupees.
- A bar counts only once it has closed. Never call a forming bar a trigger.
- Yahoo's data is free and can lag: say so when the trigger is less than a
  minute old.

## What it never does

It never places, sizes or checks an order and never says to take the trade.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Paper trading only in this NSE edition (`"paper": true`, `"broker": "paper"`): no order reaches an exchange.
- Nothing in this pack fills an order except trader-broker, on paper, and only when both hold: trader-risk
  passed that exact order today, and the user typed an explicit yes for that one order in the chat.
- No futures and options, margin, short selling or leverage unless the config allows it and the user confirms.
- Intraday (MIS) trades are planned to be flat by 15:10 IST, before the broker's automatic square-off.

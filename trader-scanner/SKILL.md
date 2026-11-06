---
name: trader-scanner
description: >-
  Chart Scanner for India's NSE. Scans thousands of NSE charts for setups:
  opening-range breakouts, flags, oversold bounces. Builds the list of
  EQ-series symbols (the ones you can trade intraday) from NSE's own equity
  list or the Nifty 500, runs a pre-market scan of daily closes (20-day
  closing-high breakout, bull flag, reclaimed the 20-day average, oversold,
  oversold bounce) and an intraday opening-range breakout scan on 5-minute
  bars from 9:15 IST, then writes trader/watchlist.json for trader-news and
  trader-entry. Free Yahoo data (SYMBOL.NS), bar by bar, prices in rupees.
  Use when the user says "scan the market", "scan NSE", "find me setups",
  "what is breaking out", "opening range breakouts", "Nifty 500 scan", "scan
  for bull flags", "oversold stocks", "pre-market scan", "build my
  watchlist", "what should I look at today", or at the start of a trading
  day before /trader-news.
argument-hint: "[universe | daily | orb] [--at HH:MM]"
---

# trader-scanner

The Chart Scanner is the first step of an NSE day trade. It reads free charts
and lists the ones that match a rule. That is all it does. A scan is a list of
charts that match a rule, not a list of stocks to buy, and a setup on a chart
is not a prediction. Most people who day trade lose money; SEBI's own study of
equity intraday traders found most of them lose. The scanner does not change
that. It only saves you from flipping through 2,000 charts by hand.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/scan.py" universe                        # NSE EQ series -> trader/universe.txt
python3 "${CLAUDE_SKILL_DIR}/scan.py" universe --list nifty500        # only the Nifty 500
python3 "${CLAUDE_SKILL_DIR}/scan.py" daily                           # before 9:15 IST -> trader/watchlist.json
python3 "${CLAUDE_SKILL_DIR}/scan.py" daily --symbols RELIANCE,TCS,M&M  # or --watchlist FILE, --limit 200
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb                             # after 9:35 IST -> trader/watchlist.json
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb --at 10:00                  # cut the clock at 10:00 IST
```

Flags: `--min-price 50` (rupees) and `--min-volume` (daily 5,00,000 shares,
orb 0), `--or-minutes 15`, `--max-confirm 200` (orb stage 2),
`--now "2026-11-05 10:00"` (IST) to pin the clock, `--offline PATH` to read
saved files, `--no-write`, `--show N`, `--json`. Exit code 0 when the scan
found something, 1 when it found nothing or could not run (the reason is one
plain line).

## What it reads and writes

| file | what |
| --- | --- |
| `trader/universe.txt` | written by `universe`: one `SYMBOL\|Name` a line, read by `daily` and `orb` |
| `trader/watchlist.json` | written by `daily` and `orb`: `mode`, `as_of`, `universe`, `scanned`, `failed`, `hits[]`. trader-news, trader-entry and trader-insider read `hits[].symbol` |
| `trader/config.json` | read by `orb`: `no_entries_after` (default 14:45) |

## The universe

`universe` downloads NSE's `EQUITY_L.csv` (every listed equity: SYMBOL, NAME
OF COMPANY, SERIES, ...) from nsearchives.nseindia.com and keeps the **EQ**
series only. EQ is the rolling-settlement series that allows intraday
trading; BE and BZ are trade-for-trade (delivery only, no intraday), and SME
boards are out. `--list nifty500` reads the Nifty 500 constituents instead,
a smaller and more liquid list. NSE's archive wants a browser-like request;
if it refuses, the user downloads the CSV in a browser and runs
`scan.py universe --offline FOLDER`.

Symbols are NSE's own: `RELIANCE`, `M&M`, `BAJAJ-AUTO`, `3MINDIA`. Yahoo's
symbol is the same plus `.NS` (`M&M.NS`, URL-encoded as `M%26M.NS`); the
tool adds and strips the suffix, so the user never types it.

## The daily scan (before the open)

Yahoo's spark endpoint returns closes for 20 symbols a request, so about
2,000 EQ symbols take about 100 requests. Liquidity comes from the spark meta:
last price at least `--min-price` (₹50 keeps out penny stocks) and last
session's volume at least `--min-volume`. Run it before 9:15 IST or after
15:30: during the session the volume is the day's so far, and today's daily
bar is left out until the close.

The setups are computed from daily closes only (spark has no highs or lows):

| setup | the rule on closes |
| --- | --- |
| `breakout_20d` | the last close is above every close of the 20 sessions before it |
| `bull_flag` | up more than 10 % over the 10 sessions before the last 5, then the last 5 closes inside a 5 % range |
| `reclaim_ma20` | the close before was under its 20-day average, the last close is above it |
| `oversold` | RSI 14 (Wilder) under 30 |
| `oversold_bounce` | RSI 14 was under 30 yesterday and today closed up |

Hits are listed most traded first (price times volume).

## The opening-range breakout scan (during the session)

NSE's normal session runs 9:15 to 15:30 IST (the pre-open auction is 9:00 to
9:08). The opening range is the first `--or-minutes` (15) of the session: the
9:15, 9:20 and 9:25 five-minute bars. A hit is the first completed 5-minute
bar to CLOSE above the range high, at that bar's close time.

1. Stage 1, every symbol: spark closes of today's 5-minute bars, 20 a
   request. A chart goes on only if a completed bar after the range closed at
   or above the highest close of the range (a necessary condition, so no
   breakout is lost).
2. Stage 2, each candidate: the v8 chart with real highs and lows, one
   request each. At most `--max-confirm` (200) of them, the most traded first;
   PARTIAL is printed with the count it skipped. `--max-confirm 0` checks all.

A chart is usable only when every 5-minute bar from 9:15 to the cutoff is
there; a missing bar means a halt, a stock locked in its price band (upper or
lower circuit), or no trades. Null closes are dropped, the live tick off the
5-minute grid (like 10:29:45) is dropped, and a bar counts only once it is
complete. Before 9:35 IST, on a weekend or an NSE holiday, after the close, or
after `no_entries_after`, it prints one plain line and writes nothing.

## Data and limits

- Yahoo's chart and spark endpoints are free, unofficial and can lag. Bars are
  5-minute bars, never tick by tick. query2 first, query1 on a 429 or 5xx.
- Partial results are said as partial: "Fetched 1,960 of 2,010 charts (50
  failed or had no data)". Never round a partial scan up to "the whole market".
- The NSE 2026 trading holidays are built in (NSE circular, read 2026-11-06).
  NSE publishes the next year's list in December; until it is added, a 2027
  date is checked for weekends only, and the tool says so.

## Steps

1. Once a week or so: `scan.py universe` (or `--list nifty500`).
2. Before 9:15 IST: `scan.py daily`. Tell the user the counts (fetched,
   liquid, scanned, hits) and the top few by setup.
3. After 9:35 IST (10:00 is a common choice): `scan.py orb`. Tell the user
   how many usable charts broke their range and when, and that a later hit is
   closer to the price now.
4. The user picks one chart. Hand it on: `/trader-news SYMBOL` (what is moving
   it), then `/trader-entry SYMBOL`. Never pick for them.

## Example (the test fixtures: synthetic prices on the real NSE calendar)

Thursday 2026-11-05, scan at 10:00 IST over ten NSE symbols:

```
python3 scan.py orb --offline tests/fixtures/trader-scanner/wall5m-2026-11-05.json.gz --now "2026-11-05 10:00"
Fetched 10 of 10 charts; 8 usable (1 under the price / volume floor); 6 candidates, 6 confirmed with real highs and lows.
2 of 8 charts closed above their opening-range high by 10:00 AM:
   9:55 AM  RELIANCE  ₹1,311.30  range 1,298.90 to 1,309.30  +0.15% over
   9:55 AM  SBIN      ₹837.20  range 831.00 to 835.95  +0.15% over
```

TATAMOTORS is not usable (two bars are missing), IDEA is under the ₹50
floor. The user picks RELIANCE and Claude hands it to `/trader-news RELIANCE`,
then `/trader-entry RELIANCE`. These are made-up prices for the tests, not
what RELIANCE did that day.

## Rules

- Say what was scanned: how many symbols, how many charts came back, how many
  were usable, and the time of the data in IST.
- Say "matched a rule", never "a buy", "a winner" or "a good trade".
- Never print a P&L, a return or a profit figure.
- A hit is stale once the price has moved on. Re-run before acting on it.

## What it never does

It never places, sizes or checks an order, never says which stock to buy,
never calls data real time, and never promises that a setup works.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Paper trading only in this NSE edition (`"paper": true`, `"broker": "paper"`): no order reaches an exchange.
- Nothing in this pack fills an order except trader-broker, on paper, and only when both hold: trader-risk
  passed that exact order today, and the user typed an explicit yes for that one order in the chat.
- No futures and options, margin, short selling or leverage unless the config allows it and the user confirms.
- Intraday (MIS) trades are planned to be flat by 15:10 IST, before the broker's automatic square-off.

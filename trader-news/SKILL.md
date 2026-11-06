---
name: trader-news
description: >-
  News Monitor for NSE stocks. Tracks the corporate announcements listed
  companies must file with NSE (board meeting outcomes, quarterly results,
  credit ratings, acquisitions, director changes, analyst meets, pledges)
  plus Yahoo Finance headlines, for every stock you watch or hold, and shows
  only what is new since the last check, newest first, in IST, with how far
  each stock has moved today and a "!" on filings that usually move a stock.
  Use when the user says "any news on RELIANCE", "what is moving this
  stock", "check the news", "NSE announcements", "corporate filings", "board
  meeting outcome", "did TCS file anything", "results today", or after
  /trader-scanner picks a chart and before /trader-entry.
argument-hint: "[SYMBOL ...] [--hours N]"
---

# trader-news

The News Monitor answers one question before an entry: is something moving
this stock that a chart cannot show? In India the first place a company has
to say anything material is the exchange: listed companies must file price
sensitive information with NSE promptly (SEBI's listing rules), so the NSE
announcement feed is the primary source, and headlines come second.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/news.py"                                  # watchlist + plan + portfolio
python3 "${CLAUDE_SKILL_DIR}/news.py" --tickers RELIANCE TCS INFY
python3 "${CLAUDE_SKILL_DIR}/news.py" --tickers RELIANCE --all --hours 72
python3 "${CLAUDE_SKILL_DIR}/news.py" --no-nse                          # headlines only
python3 "${CLAUDE_SKILL_DIR}/news.py" --json
```

Other flags: `--no-moves`, `--move-pct 3`, `--dry-run` (do not remember what
was shown), `--now ISO` to pin the clock, `--offline DIR`. Exit code 0 when
something new showed, 1 when nothing was new.

## What it reads and writes

| file | what |
| --- | --- |
| `trader/watchlist.json`, `trader/plan.json`, `trader/portfolio.json` | your symbols when `--tickers` is not given |
| `trader/state/news.json` | what you have seen (30 days), so each item shows once |
| NSE | `https://www.nseindia.com/api/corporate-announcements?index=equities&symbol=SYMBOL` |
| Yahoo | `feeds.finance.yahoo.com/rss/2.0/headline?s=SYMBOL.NS&region=IN&lang=en-IN` and the day's chart for the move |

NSE's site wants a browser-like visit first: the tool opens
`https://www.nseindia.com/` once per run for its cookies, then reads the API.
If NSE refuses anyway (it sometimes blocks scripts), the tool says so in one
line and headlines still run. Yahoo's RSS is often thin for NSE stocks; the
NSE feed is the one to trust.

## What gets a "!"

An NSE announcement whose subject usually moves a stock: financial results,
outcome of board meeting, acquisition, amalgamation, merger, scheme of
arrangement, credit rating, resignation or cessation of a director or
officer, change in auditor, fraud, default, insolvency, liquidation,
suspension, delisting, buyback, bonus, split, pledge or encumbrance,
restructuring, orders and contracts, litigation, search or raid. Each item is
also tagged by its words: earnings, analyst, legal, deal, capital, people,
risk, halt (circuit, ASM or GSM surveillance), regulatory (SEBI, RBI, CCI,
USFDA) and macro (RBI policy, CPI, GDP, the Budget, FII flows, GIFT Nifty,
crude).

## Steps

1. Run it for the chart the user picked (or the whole watchlist).
2. Lead with the "!" items: what was filed, when (IST), and the one-line
   summary NSE shows. Then the move line (price against yesterday's close).
3. If results or a board meeting are today or tomorrow, say so plainly: an
   intraday trade is flat by 15:10 IST, but results often come during market
   hours in India, and the price can gap on them.
4. Never say a headline makes a stock a buy. Say what was filed and let the
   user decide. Then hand on to `/trader-entry SYMBOL` if they go ahead.

## Example (the test fixtures: a fictional company, SAMPLECO)

```
SAMPLECO     ₹1,197.70 -0.51% vs yesterday's close ₹1,203.90 at 15:30 IST

! 2026-11-05 19:42 IST  SAMPLECO     NSE filing    Sample Industries Limited: Outcome of Board Meeting
      Sample Industries Limited has informed the Exchange about the outcome of the Board meeting ...
      tags: earnings  https://nsearchives.nseindia.com/corporate/SAMPLECO_106900001.pdf
! 2026-11-05 11:05 IST  SAMPLECO     NSE filing    Sample Industries Limited: Credit Rating
```

## Rules

- Times in IST, always with the date.
- A headline is a lead, not a fact: open the filing (the PDF link) before
  acting, and say when only the headline was read.
- Say what was checked and what failed ("NSE announcements for X: HTTP 403").

## What it never does

It never places or sizes an order, never trades on a headline, and never
calls a filing good or bad news for the price. Not financial advice.

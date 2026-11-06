---
name: trader-insider
description: >-
  Insider Tracker for NSE stocks: India's version of watching what insiders
  do with their own money. Reads the SEBI insider-trading (PIT) disclosures
  promoters, directors and designated persons must make within two trading
  days of a trade (and their company passes on to NSE), and NSE's daily bulk and
  block deals (big trades with the buyer's or seller's name). Shows, by
  default, insiders' open-market buys and sells, flags filings made late, and
  alerts once per new filing for the stocks you watch or hold. Use when the
  user says "are promoters buying", "insider trading in RELIANCE", "promoter
  buying", "insider buys", "SEBI PIT disclosures", "bulk deals today", "block
  deals", "who bought TCS shares", or "run the insider check".
argument-hint: "[pit SYMBOL | deals | new] [--days N]"
---

# trader-insider

This skill replaces the original pack's Pelosi tracker. In India the closest
public record of insiders trading their own company's shares is the SEBI
Prohibition of Insider Trading (PIT) disclosure: when a promoter, director,
key managerial person or designated employee trades more than ₹10 lakh of the
company's shares in a quarter, they must tell the company within two trading
days (regulation 7(2)), and the company tells the exchange within two more. NSE also publishes every bulk deal
(more than 0.5 % of a company's shares in a day) and block deal, with names.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/insider.py" pit RELIANCE                  # the last 30 days
python3 "${CLAUDE_SKILL_DIR}/insider.py" pit RELIANCE --days 90 --all  # every kind of filing
python3 "${CLAUDE_SKILL_DIR}/insider.py" deals                         # today's bulk and block deals
python3 "${CLAUDE_SKILL_DIR}/insider.py" deals --tickers RELIANCE TCS
python3 "${CLAUDE_SKILL_DIR}/insider.py" new                           # new since the last check, your symbols
python3 "${CLAUDE_SKILL_DIR}/insider.py" new --json
```

`--now "2026-11-06 11:30"` (IST) pins the clock; `--offline DIR` reads saved
files. Exit code 0 when something showed, 1 when nothing did.

## What it reads and writes

| file | what |
| --- | --- |
| `trader/watchlist.json`, `trader/plan.json`, `trader/portfolio.json` | your symbols when `--tickers` is not given |
| `trader/state/insider.json` | what you have seen (120 days), so each filing alerts once |
| NSE | `https://www.nseindia.com/api/corporates-pit?index=equities&symbol=SYMBOL&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY` |
| NSE | `https://www.nseindia.com/api/snapshot-capital-market-largedeal` |

NSE's site wants a browser-like visit first, which the tool makes once per
run. If NSE refuses, it says so in one line.

## What it shows

- **By default**: open-market buys and sells (`Market Purchase` / `Market
  Sale`) by promoters, the promoter group, directors and key managerial
  personnel. These are the trades where an insider paid or took the market
  price, marked "!".
- **`--all`** adds off-market transfers, gifts, ESOP allotments, pledge
  creation and revocation, and designated employees.
- **LATE**: told to the company more than two trading days after the trade
  (weekends and NSE holidays skipped).
- Each line: who, their category, bought or sold, shares, the price (value /
  shares), the value in lakh or crore, their holding before and after, the
  trade date and the filing date.

## Steps

1. For one stock: `pit SYMBOL`. Lead with insiders' market buys, then sells,
   then say how many other filings there were.
2. For the watchlist: `new`, on a schedule the user sets.
3. For big money moving today: `deals`.
4. Say plainly what an insider trade is and is not: a promoter buying in the
   market is a lead, not a signal. Insiders can be early or wrong, and sell
   for reasons that have nothing to do with the price (taxes, a pledge, a
   family need). Never say "buy because the promoter bought".

## Example (the test fixtures: a fictional company and fictional people)

```
SEBI insider-trading (PIT) disclosures on NSE, last 90 days: SAMPLECO.
!  SAMPLECO     ASHA EXAMPLE                 Promoter Group     BOUGHT 150,000 shares at about ₹1325.00 (₹19.88 cr, Market Purchase), holding 0.85% -> 0.87%, traded 2026-11-02, filed 03-Nov-2026 18:10
!  SAMPLECO     RAVI SAMPLE                  Director           SOLD 20,000 shares at about ₹1345.00 (₹2.69 cr, Market Sale), ... LATE (5 trading days after the trade)
(2 more filings: off-market transfers, pledges, ESOPs, designated employees. --all shows them.)
```

## Rules

- Names and numbers exactly as filed. Never guess why someone traded.
- A pledge is not a sale, and an ESOP allotment is not a market buy: say
  which kind each filing is.
- Trading on unpublished price-sensitive information is illegal in India.
  These filings are public after the fact; reading them is not insider trading.

## What it never does

It never places, sizes or checks an order, never says a stock is a buy
because an insider bought it, and never tracks a private person.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Paper trading only in this NSE edition (`"paper": true`, `"broker": "paper"`): no order reaches an exchange.
- Nothing in this pack fills an order except trader-broker, on paper, and only when both hold: trader-risk
  passed that exact order today, and the user typed an explicit yes for that one order in the chat.
- No futures and options, margin, short selling or leverage unless the config allows it and the user confirms.
- Intraday (MIS) trades are planned to be flat by 15:10 IST, before the broker's automatic square-off.

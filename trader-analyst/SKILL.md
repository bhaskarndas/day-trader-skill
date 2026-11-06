---
name: trader-analyst
description: >-
  Earnings Analyst for NSE-listed companies. Reads the quarterly results a
  company files with NSE (the XBRL of SEBI's integrated filing, and the
  older results filings) and sums up what changed: revenue from operations,
  EBITDA and net margins, net profit and the owners' share of it, basic EPS,
  growth against the same quarter a year earlier and the quarter before, and
  the last four quarters added up. Consolidated by default, standalone on
  request, amounts in ₹ crore. Use when the user says "how were TCS's
  results", "Q2 results", "quarterly results", "earnings for RELIANCE", "did
  profit grow", "EPS", "margins", "compare INFY and TCS results", or before
  holding a stock through its results.
argument-hint: "SYMBOL [SYMBOL ...] [--standalone] [--quarters N]"
---

# trader-analyst

The Earnings Analyst reads the numbers a company filed with the exchange and
says what changed. It does not say whether the stock is a buy. Results move
stocks in India, often during market hours, so a day trader wants to know
when they are due and what the last ones said.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/facts.py" RELIANCE
python3 "${CLAUDE_SKILL_DIR}/facts.py" TCS INFY --quarters 6
python3 "${CLAUDE_SKILL_DIR}/facts.py" HDFCBANK --standalone
python3 "${CLAUDE_SKILL_DIR}/facts.py" RELIANCE --json
python3 "${CLAUDE_SKILL_DIR}/facts.py" RELIANCE TCS INFY ITC --metrics trader/metrics.json
```

## Sources

- `https://www.nseindia.com/api/integrated-filing-results?index=equities&symbol=SYMBOL`:
  the "Integrated Filing - Financials" list (SEBI's integrated filing,
  since early 2025), one row per filing with its XBRL link.
- `https://www.nseindia.com/api/corporates-financial-results?index=equities&symbol=SYMBOL&period=Quarterly`:
  the older results filings, used only for quarters the first list lacks
  (so a year-ago comparison still works).
- `https://nsearchives.nseindia.com/corporate/xbrl/...xml`: the filing.

NSE's site wants a browser-like visit first, which the tool makes once per
run. If NSE refuses, it says so in one line.

## How the numbers are read

- Consolidated (the group) by default; `--standalone` for the listed company
  alone. A quarter filed only on the other basis falls back to it and says so.
- Each filing covers its own quarter; comparisons come from the earlier
  filings. A revised filing replaces the original.
- The quarter is the ~3-month period ending on the report date, with no
  segment (the filing's "OneD" context). The year-to-date figures in the same
  file are ignored.
- EBITDA is worked out, not filed: profit before tax + finance costs +
  depreciation - other income. Banks report interest income differently, so
  their revenue falls back to total income.
- Amounts in ₹ crore (1 crore = 1,00,00,000), EPS in rupees.

## Steps

1. Run it for the symbol. Lead with the latest quarter: revenue, net profit
   and EPS with their year-on-year change, then the margins.
2. Say whether it is consolidated or standalone, and the filing date.
3. If a quarter is missing or a filing could not be read, say so (the tool
   prints a note).
4. Never call the results good or bad for the price. The numbers are the
   answer.

## Example (the test fixtures: a fictional company, SAMPLECO)

```
Sample Industries Limited (NSE: SAMPLECO), consolidated results. ₹ crore except EPS. Source: NSE results filings (XBRL).

quarter end basis      revenue  rev yoy  EBITDA     net  net profit   NP yoy      EPS  EPS yoy
2026-09-30  consol    72,600.0   +10.5%   27.7%   13.7%     9,930.0   +12.1%    13.21   +12.0%
2026-06-30  consol    68,300.0    +6.9%   27.6%   13.5%     9,240.0    +9.0%    12.29    +9.0%
...
Last 4 quarters: revenue ₹2,81,200.0 cr, net profit ₹38,680.0 cr, basic EPS ₹51.47.
```

## Rules

- Numbers only, with their basis and period.
- Results days are risky for a day trade: a gap at the results can skip a
  stop. Say so if results are due today or tomorrow (check `/trader-news`).

## What it never does

It never says whether a stock is a buy, never forecasts results, and never
places an order. Not financial advice.

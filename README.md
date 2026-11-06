# The Day Trader skill

11 Claude skills for day trading on India's NSE: scan thousands of charts, track exchange filings, time every entry and exit, and replay every outcome before you risk a rupee.

**NSE edition.** This is a fork of
[Jakeschincariol/day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill),
adapted for the National Stock Exchange of India: IST and the 9:15 to 15:30
session, the 2026 NSE holidays, NSE tick sizes, rupees with lakh grouping,
Indian trading charges (brokerage, STT, exchange, SEBI, stamp duty, GST)
inside every max loss, NSE corporate announcements, results filings and SEBI
insider-trading disclosures. **Paper trading only**: no broker is connected
and no order reaches an exchange.

Free, MIT, no signup, no API key. The tools are plain Python that read free
public data: Yahoo Finance charts for `SYMBOL.NS`, and NSE's own lists,
announcements, results filings, insider-trading disclosures and bulk/block
deals.

One scans thousands of charts for setups. Another tracks the filings and
headlines on every stock you watch. One watches a setup bar by bar and tells
you the moment to get in, and another sets your stop and your target before
you do. And the craziest one is the Time Machine: before you risk a rupee, it
replays the rest of the session 10,000 times from the stock's own recent
bars, plus every past day the same setup fired, and tells you the honest odds.

And no trade goes through until you say yes, and even then only on paper.

## Install

Paste this into Claude:

```
https://github.com/bhaskarndas/day-trader-skill

install skill
```

Or as a plugin, in Claude Code:

```
/plugin marketplace add bhaskarndas/day-trader-skill
/plugin install day-trader-skill@day-trader-skill
```

Claude Code namespaces plugin skills, so installed as a plugin they show up as
`/day-trader-skill:trader-scanner` and so on. Copy the folders instead if you want
plain `/trader-scanner`:

```bash
git clone https://github.com/bhaskarndas/day-trader-skill.git
cp -r day-trader-skill/trader-* ~/.claude/skills/
```

The tools need Python 3.8 or newer. Nothing to pip install. Copy
`trader-budget/config.example.json` to `trader/config.json` in your project
and set your budget and limits in rupees.

## The eleven

| command | job | what it does |
| --- | --- | --- |
| `/trader-scanner` | Chart Scanner | Scans NSE's EQ-series stocks (or the Nifty 500) for setups: opening-range breakouts, flags, oversold bounces. |
| `/trader-news` | News Monitor | Tracks NSE corporate announcements and headlines on every stock you watch and flags the filings that move stocks. |
| `/trader-entry` | Entry Timer | Watches a setup bar by bar from 9:15 IST and tells you the moment to get in. |
| `/trader-exit` | Exit Planner | Sets your stop and your target on the NSE tick before you enter, and a flat-by time before the MIS square-off. |
| `/trader-timemachine` | Time Machine | Replays every possible outcome of a trade before you risk a rupee: 10,000 simulated sessions plus every past time the setup fired. |
| `/trader-risk` | Risk Manager | Checks every trade against your limits, charges included, and stops anything over them. |
| `/trader-budget` | Budget Manager | Sizes every position to your budget and your max loss per trade after brokerage, STT, stamp duty and GST. |
| `/trader-broker` | Order Executor | Fills approved orders on paper, with Indian charges, never without your yes. |
| `/trader-alerts` | Price Alerts | Rings when a price, a stop, the flat-by time or the 9:15 opening bell hits; knows NSE's holidays. |
| `/trader-analyst` | Earnings Analyst | Reads the quarterly results companies file with NSE and sums up what changed. |
| `/trader-insider` | Insider Tracker | Reads SEBI insider-trading disclosures and NSE bulk and block deals: are promoters buying? |

## How to use it

Everything lands in a `trader/` folder in your project, and each skill reads
what the last one wrote:

```
scanner -> news -> entry -> exit -> timemachine -> budget -> risk -> broker (paper)   (one trade)
alerts: stop, target, flat by 15:10 IST                                                (while it is open)
news / analyst / insider                                                               (on a schedule)
```

An example, run on the test fixtures (synthetic prices on the real NSE
calendar; these are not RELIANCE's real prices that day):

1. **`/trader-scanner`** at 10:00 IST: RELIANCE closed above its 15-minute
   opening range (1,298.90 to 1,309.30): the 9:50 candle closed at 1,311.30.
2. **`/trader-news`**: the NSE announcements and headlines for RELIANCE, in
   IST, with a "!" on results, board meeting outcomes, deals and ratings.
3. **`/trader-entry`** watched RELIANCE bar by bar. At 9:52 it said waiting
   (the 9:50 bar was still forming). At 10:00 it said triggered at 9:55 AM,
   1,311.30.
4. **`/trader-exit`** set the plan before the entry: stop at the range's
   midpoint, 1,304.10 (on the 0.10 tick), so ₹7.20 a share at risk; target
   one times that risk, 1,318.50; flat by 15:10 IST either way.
5. **`/trader-timemachine`** replayed the rest of the day 10,000 times from
   RELIANCE's own 5-minute candles over the previous 58 sessions (seed 19):
   target first 58.2 %, stop first 40.6 %. The same rule on those 58 real
   sessions broke even: 22 targets, 22 stops. When the replays and the history
   disagree, it says so.
6. **`/trader-budget`** with a ₹1,00,000 account and a ₹500 max loss: 57
   shares (₹74,744.10), bound by the 75 % position cap. Max loss at the stop:
   57 x 7.20 + ₹73.42 charges = ₹483.82. At the target: ₹410.40 gross,
   ₹336.74 after charges. A "1R" trade is 0.70R once brokerage, STT and the
   rest are paid.
7. **`/trader-risk`** checks it against your limits, charges included, and
   the IST entry window. PASS or BLOCK, with the reason.
8. **`/trader-broker`** shows you the ticket. You type yes for that exact
   order, and it fills on paper, charges taken off your cash.
9. **`/trader-alerts`** rings on the stop, the target and at 15:10 IST to
   flatten whatever is still open, before the broker's square-off.

## The tools

All standard-library Python.

```bash
python3 trader-scanner/scan.py universe                                # NSE EQ series, from EQUITY_L.csv
python3 trader-scanner/scan.py daily                                   # pre-market setups
python3 trader-scanner/scan.py orb --at 10:00                          # opening-range breakouts so far
python3 trader-news/news.py --tickers RELIANCE --hours 12              # NSE filings, headlines, today's move
python3 trader-entry/entry.py check RELIANCE --setup orb               # waiting / triggered / expired
python3 trader-entry/entry.py watch RELIANCE --every 30                # bar by bar until it triggers
python3 trader-exit/exit.py plan --stop or-mid --target 1R --write     # -> trader/plan.json
python3 trader-timemachine/timemachine.py run --write                  # 10,000 replays + the history
python3 trader-budget/size.py --write                                  # -> trader/orders.json
python3 trader-risk/check.py                                           # PASS / BLOCK per order
python3 trader-broker/ticket.py show                                   # the tickets, READY or not
python3 trader-broker/ticket.py approve --index 1 --reply "yes"        # the paper fill
python3 trader-alerts/alerts.py add --from-plan                        # stop, target, flat by 15:10
python3 trader-alerts/alerts.py check                                  # rings what hit, once
python3 trader-analyst/facts.py RELIANCE                               # quarters, growth, EPS (₹ crore)
python3 trader-insider/insider.py pit RELIANCE                         # promoters' and directors' trades
python3 trader-insider/insider.py deals                                # today's bulk and block deals
```

```bash
python3 -m unittest discover -s tests -v
```

The tests run offline. Their fixtures are built by
`tests/fixtures/make_nse_fixtures.py`: synthetic price paths laid on the real
NSE calendar in the exact JSON shape Yahoo returns for `SYMBOL.NS`, and NSE
announcement, results (XBRL), insider-trading and deal files in NSE's own
field layout for a fictional company with fictional people. The shapes were
checked against live answers on 2026-11-06; the numbers are made up.

## Fine print

**Not financial advice.** This is software that reads public data and does
arithmetic. It does not know your situation and it cannot see the future.
SEBI's own study of individual intraday traders in the equity cash segment
found that most of them lose money. You can lose money. Decide for yourself,
and talk to a SEBI-registered investment adviser if you need advice.

**Paper only.** This NSE edition has no broker connection. `/trader-broker`
fills orders on paper, in `trader/portfolio.json`, only after `/trader-risk`
passes that exact order and you type yes for it. Trading real money is your
own decision, in your own broker's app.

**Charges are in every number.** Brokerage (0.03 %, at most ₹20 an order),
STT (0.025 % of the sell, intraday), the NSE transaction charge (0.00297 %),
the SEBI fee (₹10 a crore), stamp duty (0.003 % of the buy) and GST (18 %)
are the defaults, read from broker charge sheets on 2026-11-06. They change
with budgets and brokers: set yours under `"charges"` in the config.

**The Time Machine is a simulation, not a prediction.** It is built from the
stock's own last 60 days of 5-minute bars. The future can do things those 60
days never did: results, a circuit limit, a headline. Its odds are before
charges. Treat them as a reality check, never as a promise.

**A stop is a plan, not a guarantee.** In a fast market, across a gap, or
when a stock hits its price band, a stop can fill well past its price or not
at all. The max loss shown is the loss at the stop price, plus charges.

**Square-off.** Brokers close intraday (MIS) positions on their own from
about 15:15 to 15:25 IST and charge for it. The plans here are flat by 15:10.

**The data is free and unofficial.** Yahoo Finance's chart endpoint is not an
official API, and NSE's website endpoints are built for its own pages: either
can lag, change or refuse scripts. The tools say so in one line when that
happens. Check anything that matters against your broker before you act.

**Holidays.** The 2026 NSE trading holidays are built in. NSE publishes the
next year's list in December; add it to the `NSE_HOLIDAYS` lists when it is out.

**Taxes.** Intraday equity gains are speculative business income in India.
Nothing here is tax advice.

## Files

```
trader-scanner/       SKILL.md, scan.py
trader-news/          SKILL.md, news.py
trader-entry/         SKILL.md, entry.py
trader-exit/          SKILL.md, exit.py
trader-timemachine/   SKILL.md, timemachine.py
trader-risk/          SKILL.md, check.py
trader-budget/        SKILL.md, size.py, config.example.json, targets.example.json
trader-broker/        SKILL.md, ticket.py
trader-alerts/        SKILL.md, alerts.py, alerts.example.json
trader-analyst/       SKILL.md, facts.py, metrics.example.json
trader-insider/       SKILL.md, insider.py
tests/                unittest suite + offline fixtures (make_nse_fixtures.py)
```

MIT. The original pack is by [Jake Schincariol](https://opusjake.ai); this
NSE edition is a fork.

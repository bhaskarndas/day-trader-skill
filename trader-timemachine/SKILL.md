---
name: trader-timemachine
description: >-
  Time Machine for NSE day trades. Replays every possible outcome of a
  trade before you risk a rupee: 10,000 simulated sessions plus every past
  time the setup fired. Takes the plan from trader-exit (entry, stop,
  target), rebuilds the rest of the day 10,000 times from the stock's own
  5-minute bars over the last 60 days (Yahoo SYMBOL.NS, 75 bars a day from
  9:15 IST), and re-runs the same rule on every past session. Prints the odds
  of target first, stop first, or neither by the close (or your flat-by
  time), where the price sits then, the average R, the history, and one
  honest verdict, then hands off to /trader-budget. Use when the user says
  "run the time machine", "replay this trade", "what are the odds",
  "simulate this trade", "monte carlo", "backtest this setup", "how often
  does this hit the target", "is this a coin flip", or after /trader-exit
  writes a plan, : "[path to plan.json, or SYMBOL]"
---

# trader-timemachine

The Time Machine sits between the plan and the money. trader-exit has set
the entry, the stop and the target. Before anything is sized or sent, this
skill asks one question: if today plays out like the stock's own last 60
days, how often does this plan hit the target first, the stop first, or
neither? It answers with 10,000 replays and with the real record of the same
rule on every past session. It is a simulation built from the stock's own
recent bars, not a prediction. Day trading loses most people money, and a
good-looking replay does not change that. The odds are before charges:
trader-budget shows what brokerage, STT and the rest take from each outcome.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run                    # trader/plan.json, 10,000 replays, seed 19
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --write            # also save trader/timemachine.json
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --until 15:10      # end each replay at your flat-by time
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --json
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --symbol RELIANCE --date 2026-11-05 \
    --entry 1311.30 --stop 1304.10 --target 1318.50 --entry-time "9:55 AM"
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" chart --from           # ASCII fan chart of the saved run
```

Other flags: `--replays N`, `--seed N` (default 19), `--window N` (default 2
bars), `--offline FILE` (a saved Yahoo chart JSON, `.json` or `.json.gz`),
`--now "2026-11-05 10:30"` (IST) to pin the clock.

## What it reads and writes

| file | what |
| --- | --- |
| `trader/plan.json` | the plan from trader-exit: symbol, date, entry, entry_time / entry_bar, stop, stop_rule, target, target_r, opening range |
| Yahoo chart API | one request: 60 days of 5-minute bars (`range=60d&interval=5m`), free and unofficial, can lag |
| `trader/timemachine.json` | with `--write`: `{plan, mc, history}` plus the verdict. `mc` holds the odds, percentiles, the fan-chart bands, 160 sample paths and a 24-bin histogram of the close |

## How it works

1. **The pool.** It keeps only FULL sessions before the plan's date: all 75
   five-minute bars, 9:15 to 15:30 IST. Short days (a Muhurat session on
   Diwali), days with missing bars (a halt, a circuit lock) and today are
   left out. NSE holidays are simply not in the data. Every bar becomes four ratios to the bar before it:
   open, high, low and close over the previous close.
2. **One replay.** Start at the entry price. For each bar left in the day,
   pick a past bar from the same time of day (plus or minus 2 bars) at
   random, and scale it to the current price. Bar by bar, it checks the stop
   first, then the target. A bar that touches both counts as the stop.
3. **10,000 replays** give four odds. Target first. Stop first. Neither,
   which means the trade was still open at `--until` (default 3:30 PM, the
   close; pass your flat-by time, 15:10, to match the plan). Green, which means target
   first or above the entry at `--until`.
   R is +1 at a 1R target, -1 at the stop, and otherwise the distance from
   the entry at `--until` divided by the risk. A gap through the stop still
   counts as -1R here. A real fill can be worse.
4. **The history.** The plan's own rule (the same opening range, stop rule
   and target R) runs again on every one of those past sessions. That is
   what really happened, not a simulation.
5. **The verdict** is one line from the numbers. It looks only at the
   replays that hit one side, and asks how often the target came first. A
   bigger target needs to win less often to break even: 1 in (1 + R). That
   is 50 % at 1R, 33 % at 2R, 25 % at 3R. Less than 5 points from break-even:
   "Close to a coin flip" at 1R, "Close to break-even" at any other R. 5 to
   15 points: "Leans toward the target" or "Leans toward the stop". 15 or
   more: "Strongly toward" one of them. So a 2R plan with target first
   24.1 % and stop first 50.5 % is close to break-even (it needs 33 % of
   the 74.6 % that hit a side, and got 32 %), not a loser.
6. **Below the verdict**, when it applies: a line when more than 40 % of the
   replays hit neither (the price at `--until` decides those), and the
   average R when its sign goes against the lean. Those can only point the
   other way because of the replays that hit neither.

**The seed.** The draws come from Python's `random.Random(seed)`, seed 19 by
default. Same plan, same data, same seed: the same numbers, on any machine.
Say the seed with every result so the user can repeat it.

**5-minute bars only.** Yahoo keeps 60 days of 5-min bars but only about 7
days of 1-min bars, too few sessions for a fair pool. It refuses, in one
plain line, when there are fewer than 20 full sessions, when the entry bar is
not in the data (wrong date, not closed yet, a future day), or when the plan
does not make sense (a stop above a buy's entry, an entry off the 5-minute
grid). A live in-progress bar is never used.

## Steps

1. Make sure `trader/plan.json` is today's plan from `/trader-exit`. If there
   is none, run that first, or pass the plan as flags.
2. Run `timemachine.py run --write`. Add `--until 15:10` when the plan has a
   flat-by time, so "neither" means still open at the time you would get out.
3. Tell the user, in this order: the four odds, the median and the 5 to 95
   range of the price at the close, the average R, the history line, then the
   verdict line and any line under it exactly as printed. Say the seed.
4. If the verdict is a coin flip or close to break-even, say so plainly. Do
   not dress it up. If the history and the replays disagree, say that too.
5. Say once that this is built from the last 60 days and is not a prediction.
   Results, news, circuit limits and halts can do things those 60 days never
   did. Check `/trader-news` for the stock before going on.
6. If the user still wants the trade, hand off to `/trader-budget` to size it.

## Example (the test fixtures: synthetic prices on the real NSE calendar)

RELIANCE, Thursday 2026-11-05. The 15-minute opening range is 1298.90 to
1309.30. The 9:50 bar closes above it: entry 1311.30 at 9:55 AM (bar 7), stop
1304.10 (the range midpoint, on the 0.10 tick), target 1318.50 (1R, risk ₹7.20
a share).

```
10,000 replays of the rest of the session, 9:55 AM to 3:30 PM (67 five-minute bars), seed 19.
  target first   58.2 %
  stop first     40.6 %
  neither        1.2 %    still open at 3:30 PM
  green          58.8 %   target first, or above the entry at 3:30 PM
  Price at 3:30 PM: median 1313.98, 90 % of replays between 1292.17 and 1336.14.
  Average R: +0.176 (R = the ₹7.20 risk: +1R at the target, -1R at the stop).
History: the same rule ... on each of those 58 real sessions fired 45 times: 22 target, 22 stop,
1 neither. Average R -0.001.
Leans toward the target: target first 58.2 % vs stop first 40.6 %.
```

The replays lean toward the target, but the same rule on the past sessions
broke even (22 wins, 22 losses). When the two disagree, say so: the history
is what really happened, the replays are a reshuffle of it. And the odds are
before charges: at 1R, brokerage, STT and the rest turn a win of ₹410 into
₹337 and a loss of ₹410 into ₹484 on 57 shares (trader-budget shows it). The
prices in this example are made up for the tests.

## Rules

- Every number comes from the run. Never round a coin flip up into an edge.
- The verdict line and the lines under it are printed by the tool. Repeat
  them, do not rewrite them. Never judge a 2R or 3R plan by target first vs
  stop first alone: the verdict already weighs the target's R.
- Simulated odds are not predictions and not promises. Say it once, plainly.
- Free Yahoo data is unofficial and can lag. Bars are 5-minute bars, checked
  bar by bar, never tick by tick and never real time.
- Always say the seed, so any run can be repeated.
- One plan per run. A changed entry, stop, target or date is a new run.

## What it never does

It never places an order, never sizes a position, never changes the plan,
and never calls a result a sure thing. It never prints a P&L or a profit.
It never uses a bar that has not closed yet, and never mixes today's bars
into the pool.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Paper trading only in this NSE edition (`"paper": true`, `"broker": "paper"`): no order reaches an exchange.
- Nothing in this pack fills an order except trader-broker, on paper, and only when both hold: trader-risk
  passed that exact order today, and the user typed an explicit yes for that one order in the chat.
- No futures and options, margin, short selling or leverage unless the config allows it and the user confirms.
- Intraday (MIS) trades are planned to be flat by 15:10 IST, before the broker's automatic square-off.

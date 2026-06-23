# From an ICT Report to Your Own Edge — A Practical Framework

## 1. What this report actually is

The MMXM ICT/CRT report is an unusually well-organised **concept library**: Power of 3, IPTA cycles, internal/external liquidity, PD arrays (order blocks, FVGs, breakers, mitigation blocks), AMD, market-maker buy/sell models, the Silver Bullet, kill zones, OTE, BPR, plus sound risk rules. As a vocabulary for *reading* a chart, it's coherent and complete.

But notice what it is **not**: every single rule is labelled "verbatim from the video transcripts." Not one is backtested. There is no win rate, no expectancy, no out-of-sample test, no cost assumption anywhere in 28 pages. It is a **belief system, not a measured edge** — and it's the same family (sweep → displacement → order-block / FVG entry in a kill zone) that:
- your own CRT strategy encoded and tested at **−0.099R (losing)** across all four timeframes, and
- the academic literature cannot validate, because the concepts are subjective (two traders mark different order blocks on the same chart) and therefore unfalsifiable as written.

So the report's value to you is **a hypothesis bank**, not a strategy. The job is to convert its claims into testable rules, measure which ones actually carry signal on *your* instruments, keep the survivors, and throw the rest away.

## 2. What an "edge" really is

An edge is not a set of concepts you trust. It is **a number**: a positive expectancy that is (a) measured on real data, (b) net of spread/slippage, (c) stable out-of-sample, and (d) repeatable across time and instruments. The report gives you concepts; an edge is the concept *that survived measurement*. You already own the machinery to manufacture edges — pre-committed kill criteria, the fast backtester, walk-forward, multi-instrument testing. This framework just points that machinery at the report.

## 3. Proof that you must measure, not believe (live test on your gold data)

The report states repeatedly that **"most of the time London session creates the high or low of the day."** I tested that on your XAUUSD M15 data, 1,031 days (New York time):

| Session (NY time) | Holds day's HIGH | Holds day's LOW | Holds an extreme (high OR low) | Avg share of daily range |
|---|---|---|---|---|
| London KZ (2–5am) | 12.9% | 14.0% | **26.8%** | 37.6% |
| **NY KZ (7–10am)** | 20.5% | 19.9% | **37.7%** | **55.5%** |
| Asian KZ (8–10pm) | 6.7% | 5.3% | ~12% | 28.8% |

The London claim is **overstated for gold** — London holds an extreme only ~27% of the time. The real driver of gold's daily range is the **New York session** (holds an extreme 38% of days, ~55% of the daily range). The general *kill-zone idea* (some hours concentrate the action) is partly true, but the specific London emphasis isn't — for gold. That is the whole point: **universal claims aren't universal. Measure on the instrument you actually trade.**

## 4. The process — turn the report into an edge

**Step 1 — Convert each concept into ONE mechanical, falsifiable rule.**
No discretion. "Order block" → "the last down-close candle before a move that exceeds 1×ATR." "Kill zone" → "07:00–10:00 New York." "Sweep" → "price trades beyond yesterday's high then closes back below within N bars." If you can't write it as code with zero judgement calls, you can't test it — and if you can't test it, you can't know it has an edge.

**Step 2 — Cheap premise test before any full strategy.**
Before building entries/exits, test the *underlying claim* with a one-line statistic (like the London table above). "Does a swept high reverse more often than chance?" "Does price at a 0.705 retrace react more than at 0.5?" Kill weak premises here, in minutes, before you waste days building a system on a false foundation.

**Step 3 — Encode survivors as full rules and backtest with discipline.**
Entry, stop, target, all mechanical. Use the conventions you've already standardised: next-bar-open fills, 2bps slippage, R-multiples. **Pre-commit the kill criterion before you look at results** (e.g. ≥150 trades, avg_R ≥ +0.20R, profit factor > 1). Write it down first so you can't move the goalposts.

**Step 4 — Validate the survivors hard.**
Walk-forward (train/test split), regime breakdown (does it only work in trends?), and multiple instruments — exactly the process we just ran on the daily trend system. A real edge survives out-of-sample and isn't a single-market fluke. Most "edges" die here. That's normal.

**Step 5 — Combine only the survivors; apply the report's risk rules.**
The report's risk section is its most reliable part: 0.5–1% risk per trade, ≥1:2 reward:risk, no entries around FOMC/NFP/CPI, stop at 50% of daily loss limit. Bolt these onto whatever passed Step 4. Risk management isn't an edge, but it's what keeps a real edge alive.

**Step 6 — Paper-trade, then live-small, keep a research log.**
Forward-test the survivor in real time, then trade it tiny, then scale. Log every hypothesis (pass/fail) so you stop re-testing dead ideas. Expect ~90% of hypotheses to fail — the edge is the 10% that lived through all six steps.

## 5. Prioritised hypothesis backlog (from the report)

Ranked by prior plausibility × how cleanly it encodes. Start at the top.

| Priority | Concept from report | Why | How to test |
|---|---|---|---|
| **HIGH** | Relative strength — "long the strongest vs weakest" | This is cross-sectional momentum, which has real academic backing | Rank your instruments by N-day return weekly; long top / short bottom; measure |
| **HIGH** | Session/time-of-day filter (kill zones) | Partly validated above — NY drives gold's range | Use as a *filter* on other entries (trade only 07:00–11:00 NY for gold), compare with/without |
| **MED** | Seasonal tendency (gold by quarter) | Testable, modest evidence as a confluence | Average monthly/quarterly returns over many years; use as bias tilt only |
| **MED** | Premium/discount + OTE 0.705 | Range mean-reversion is testable | Do retraces to 0.62–0.79 of a leg reverse more than to 0.5? Measure forward return |
| **MED** | IRL/ERL alternation ("after a sweep, price draws to the nearest FVG") | A clean conditional probability | After an ERL sweep, does price reach the nearest FVG before the opposite extreme? |
| **LOW** | Turtle soup / sweep-reversal | **Already tested — your CRT = −0.099R.** Known failure | n/a (done) |
| **LOW** | Order-block / FVG entries | Core of CRT, negative; subjective to mark | n/a (done) |
| **LOW** | AMD / market-maker models | Too discretionary to encode without judgement → unfalsifiable | Only as post-hoc narrative, not a testable rule |

## 6. The one-sentence version

The report is a **menu of hypotheses written as if they were facts**; your edge is whatever's left after you force each one through mechanical encoding, a cheap premise test, a pre-committed backtest, and out-of-sample validation — and so far the only thing that has survived that gauntlet on your data is **daily trend-following on gold**, not anything in the ICT family.

# ICT Multi-Timeframe Strategy — Systematic Backtesting Research

> **CRT + ICT PD Array Research Project**  
> 240 parameter combinations × 6 instruments × 4 years of data (2022-05-12 → 2026-01-31)

---

## Table of Contents

1. [Strategy Overview](#strategy-overview)
2. [How the Strategy Works](#how-the-strategy-works)
3. [Project Structure](#project-structure)
4. [Setup & Installation](#setup--installation)
5. [Research Scope](#research-scope)
6. [Key Findings](#key-findings)
7. [Top 20 Setups by Total R](#top-20-setups-by-total-r)
8. [Risk-Adjusted Rankings](#risk-adjusted-rankings)
9. [Walk-Forward Validation](#walk-forward-validation)
10. [Dimension Analysis](#dimension-analysis)
11. [Recommended Setup](#recommended-setup)
12. [Rules for Live Trading](#rules-for-live-trading)

---

## Strategy Overview

This project implements and systematically backtests the **ICT (Inner Circle Trader) Multi-Timeframe (MTF)** trading strategy across 6 major instruments over a 4-year period.

**Instruments tested:** EURUSD, GBPUSD, USDJPY, XAUUSD (Gold), NAS100, US30  
**Date range:** 2022-05-12 to 2026-01-31  
**Total setups tested:** 198–240 parameter combinations  
**Total backtests:** ~1,200 individual instrument × parameter runs

---

## How the Strategy Works

### Visual: H4 Bias → M5 Entry Flow (Recommended Setup)

```
 4H CHART (Bias Layer)                      M5 CHART (Entry Layer)
 ─────────────────────────────────          ──────────────────────────────────────

  Swing High ──┐                                         MSS confirmed  <── ENTRY
               │  BOS (Break of Structure)               ┌──────────────────────
  │            ▼  => Bullish Bias                        │    CHoCH candle closes
  │   ┌────────────┐                                     │    above prev swing high
  │   │  IMPULSE   │  (strong move up)                   │
  │   └────────────┘                                     │    ^ price sweeps below OB
  │         │                                            │    │ (liquidity grab)
  │         │ pullback                                   │    │
  │         ▼                                            └────┴─────
  │   ┌─────────────────────────────┐
  │   │  ORDER BLOCK (OB) ZONE      │ <── 4H candle:   M5 zooms into OB zone:
  │   │  Last bearish candle before │     the "last     ┌──────────────────────┐
  │   │  the bullish impulse        │     down candle"  │  price enters zone   │
  │   └─────────────────────────────┘     before the    │  sweeps liq. below   │
  │         │                             big up move   │  MSS forms <- WAIT   │
  │         │  (price returns to OB)                    │  for this candle     │
  │         ▼                                           └──────────────────────┘
  └────────────────────────────────────────────────────────────────────────────

 FULL TRADE EXECUTION FLOW
 ──────────────────────────────────────────────────────────────────────────────

  [1] 4H CHART: Identify market bias
      │
      ├─ Scan for BOS / CHoCH on 4H
      ├─ Bullish? => Look for BUY setups
      └─ Bearish? => Look for SELL setups
             │
             ▼
  [2] 4H CHART: Locate the Order Block (OB)
      │
      ├─ Find the last DOWN candle before the bullish impulse (for buys)
      ├─ Mark OB High and OB Low as the entry zone
      └─ OB must be "fresh" (price never returned here yet)
             │
             ▼
  [3] SESSION FILTER: Is this a Kill Zone window?
      │
      ├─ YES (London KZ 02:00-05:00 NY / NY AM KZ 07:00-10:00 NY) => continue
      └─ NO => skip, wait for next session
             │
             ▼
  [4] M5 CHART: Watch price enter the 4H OB zone
      │
      ├─ Price drops INTO the OB zone
      ├─ Often sweeps liquidity BELOW the OB low (stop hunt)
      └─ DO NOT ENTER YET (this is the Risk entry -- avoid it)
             │
             ▼
  [5] M5 CHART: Wait for MSS (Market Structure Shift)
      │
      ├─ Look for a M5 CHoCH (Change of Character):
      │    price breaks ABOVE the last M5 swing high while still inside OB
      ├─ This confirms the OB held and buyers are in control
      └─ MSS candle CLOSES above swing high => ENTER LONG
             │
             ▼
  [6] SET STOPS AND TARGETS
      │
      ├─ Stop Loss:   below MSS candle low  (or OB low + 0.1x ATR buffer)
      ├─ Take Profit: 50% at 1R | 30% at 2R | 20% at 3R+
      └─ Result expressed in R-multiples (1R = initial dollar risk)

 ──────────────────────────────────────────────────────────────────────────────

 EXAMPLE: EURUSD BUY SETUP (4H OB + M5 MSS Confirm)

  4H CHART                                  M5 CHART (zoom into OB zone)
  ─────────────────                         ──────────────────────────────
  1.0900                                     1.0862  -- swing high (MSS) <- ENTRY
         │                                           │  CHoCH closes here    LONG
  1.0870 ▼  BOS (bullish)                   1.0855  │
         ─────────────────                          │
  1.0840 ▲  OB HIGH     <── 4H OB ZONE      1.0848  │  price enters OB
  1.0835 │  OB LOW           (entry zone)   1.0840  │  OB HIGH
         │                                  1.0835  │  OB LOW
  1.0810 └── Swing Low                      1.0832      liq. sweep (wick)

         SL: 1.0833   TP1: 1.0868 (+1R)   TP2: 1.0903 (+2R)

 ──────────────────────────────────────────────────────────────────────────────
```

### Why This Works
- The **4H OB** marks where large institutions placed orders on the way up — they defend this price level when price returns.
- The **M5 MSS** proves the institution's defense was successful — the stop hunt (liquidity grab) cleared weak hands, and the MSS candle confirms the reversal.
- Trading only during **Kill Zone sessions** ensures there is enough institutional volume to actually move price away from the OB after entry.

---

### Two-Timeframe Architecture

The strategy operates on two simultaneous timeframes:

| Layer | Timeframe | Purpose |
|-------|-----------|---------|
| **HTF (Higher Timeframe)** | 4H or 1H | Determine market bias (bullish/bearish), identify supply/demand zones |
| **LTF (Lower Timeframe)** | M15 or M5 | Time precise entries within HTF-identified zones |

### Step 1 — HTF Bias (Market Structure)

The engine scans the HTF chart for:
- **Swing Highs / Swing Lows** — structural pivots that define the current directional bias
- **BOS (Break of Structure)** — confirms trend continuation
- **CHoCH (Change of Character)** — signals potential reversal

Once bias is determined (bullish = price above key swing low, bearish = price below key swing high), the engine identifies the relevant **PD Arrays** on that side.

### Step 2 — PD Arrays (Premium / Discount Zones)

PD Arrays are specific price structures that represent institutional order flow. The strategy targets two types:

#### Order Blocks (OB)
The **last bearish candle before a bullish impulse** (for buys) or the **last bullish candle before a bearish impulse** (for sells). This candle represents institutional accumulation/distribution.

- Identified on the **HTF**
- Entry is triggered when LTF price returns to the OB zone
- The OB must be "fresh" (price has not returned to it since formation)

#### Fair Value Gaps (FVG)
A **3-candle imbalance** where the wicks of candle 1 and candle 3 do not overlap — leaving a gap of untraded price. Markets tend to return to fill these gaps.

- FVGs represent price inefficiency / liquidity voids
- Treated as high-probability entry zones when aligned with HTF bias

#### Combined (OB + FVG)
When both an OB and FVG overlap in the same zone — the highest-conviction entry area.

### Step 3 — Session Filters

Trading is restricted to specific **Kill Zones** — high-liquidity windows where institutional activity is highest:

| Session | Time (NY local) | Character |
|---------|----------------|-----------|
| Asian KZ | 20:00 – 00:00 | Range formation, liquidity grabs |
| Asian | 00:00 – 04:00 | Low volatility continuation |
| London KZ | 02:00 – 05:00 | Highest volume, trend initiation |
| London | 05:00 – 08:00 | Continuation of London open |
| NY AM KZ | 07:00 – 10:00 | Key US session, news events |

**GO Sessions** = Asian KZ + Asian + London KZ + London + NY AM KZ (5 sessions)  
**All Sessions** = GO Sessions + London Close + NY PM + Off Hours

### Step 4 — Entry Styles

Two entry methods were tested, modelled on ICT's own educational framework:

#### Risk Entry — Section 8.1 (`require_mss=False`)
- Enter **immediately** when price reaches the OB/FVG zone
- Wider stop: placed beyond the OB extremity
- **More trades, lower per-trade R, higher drawdown**
- Suitable for aggressive position-sizing models

#### Confirmation Entry — Section 8.2 (`require_mss=True`)
- Wait for a **Market Structure Shift (MSS/CHoCH)** on the LTF **before** entering
- MSS = the LTF breaks the last swing high (for longs) after sweeping liquidity below the OB
- Tighter entry, tighter stop — the MSS candle low becomes the invalidation level
- **Fewer trades, higher per-trade R, much lower drawdown**
- **This is the winning approach — see findings below**

### Step 5 — Additional Filters

| Filter | ON | OFF |
|--------|-----|-----|
| **Strong Filter** | Only take OBs formed by strong/impulsive moves (high ATR ratio) | Accept all OBs |
| **PD Array Filter** | Only enter from Premium (sells) or Discount (buys) vs. range midpoint | Accept all aligned OBs |

### Risk Management (Scheme A)

- **Stop loss:** Below the OB low (+ buffer of 0.1 × ATR)
- **Take profit:** Two-part exit — 50% at 1R, 30% at 2R, 20% at 3R+
- **R-Multiple:** All results expressed in R (1R = initial risk per trade)
- Spread cost deducted per instrument using realistic FTMO spreads

---

## Project Structure

```
CRT + ICT PD Array Research/
├── Python_Project/
│   ├── engine/
│   │   └── phase2_engine.py        # Core backtest engine
│   ├── dashboard/
│   │   ├── app.py                  # Interactive Dash dashboard
│   │   └── assets/custom.css
│   ├── walkforward/
│   │   ├── run_walk_forward.py     # Walk-forward framework
│   │   └── run_all_pairs.py
│   ├── data_fetch/
│   │   ├── fetch_research_data.py  # Fetch M15 data
│   │   └── fetch_m5_data.py        # Fetch M5 data
│   ├── visualization/
│   │   └── viz_charts.py           # Result charting
│   ├── Examples/                   # ICT setup chart examples
│   ├── ICT_MultiTF_Strategy.pine.txt  # Pine Script strategy
│   └── requirements.txt
├── MT5_Project/
│   └── EA/                         # MetaTrader 5 Expert Advisors (v1.0–v1.3)
├── research/
│   ├── batch_setup_test.py         # 240-combo batch runner
│   ├── batch_risk_adjusted.py      # Risk-adjusted metric batch runner
│   └── walk_forward_rank12.py      # Walk-forward validation script
├── results/
│   ├── setup_results.csv           # All 198 setups ranked by Total R
│   ├── risk_adjusted_results.csv   # 80 setups ranked by Calmar / Adj Sharpe
│   └── ICT_Setup_Research_Report.pdf  # Full 18-page research report
├── reports/                        # Per-instrument trade logs
└── README.md
```

> **Note:** The `data/` directory (49.5 MB of M15/M5 parquet files) is excluded from this repo.  
> Run `data_fetch/fetch_research_data.py` and `data_fetch/fetch_m5_data.py` to regenerate it.

---

## Setup & Installation

### Requirements

- Python 3.11+
- Anaconda recommended

```bash
pip install -r Python_Project/requirements.txt
pip install fpdf2   # for PDF report generation
```

### Data

```bash
# Fetch M15 data (EURUSD, GBPUSD, USDJPY, XAUUSD, NAS100, US30)
python Python_Project/data_fetch/fetch_research_data.py

# Fetch M5 data
python Python_Project/data_fetch/fetch_m5_data.py
```

### Dashboard

```bash
python Python_Project/dashboard/app.py
# Open http://localhost:8050
```

---

## Research Scope

| Dimension | Options Tested |
|-----------|---------------|
| Timeframe pairs | H4-M15, H4-M5, H1-M15, H1-M5, M15-M5 |
| Entry type | OB only, FVG only, OB+FVG combined |
| Entry style | Risk (no MSS), Confirmation (with MSS) |
| Session filter | GO Sessions only, All Sessions |
| Strong OB filter | ON, OFF |
| PD Array filter | ON, OFF |
| **Total combinations** | **240** |
| Instruments | EURUSD, GBPUSD, USDJPY, XAUUSD, NAS100, US30 |
| Period | 2022-05-12 to 2026-01-31 (4 years) |

---

## Key Findings

### Finding 1 — Entry Style is Everything

**Confirmation (MSS) entry completely dominates Risk entry across every metric:**

| Metric | Confirm (MSS) | Risk (no MSS) |
|--------|-------------|--------------|
| Avg Total R | +415 | -539 |
| Avg Calmar (R/DD) | 29.1 | -0.9 |
| Avg Adj Sharpe | 9.35 | -4.57 |

> Risk entries destroy capital on average. Confirmation entries are profitable on average.  
> **Never take a Risk entry.**

### Finding 2 — H4 Bias + M5 Entry is the Optimal Timeframe Pair

The H4-M5 pair produces the best **risk-adjusted** returns. H1-M5 produces higher raw Total R (more trades = more absolute R), but H4-M5 has far lower drawdown and better per-trade quality:

| TF Pair | Total R (avg) | Max DD (avg) | Calmar | WR% |
|---------|-------------|-------------|--------|-----|
| H4-M5 | +992 | 7.07 | 140 | 75% |
| H1-M5 | +3,943 | 92.76 | 42 | 70% |

### Finding 3 — OB-Only Outperforms FVG and Combined

Order Blocks alone produce higher Adj Sharpe (4.63) than OB+FVG combined (3.34). FVG-only is strongly negative.

### Finding 4 — GO Sessions Slightly Edge Out All Sessions (Risk-Adjusted)

Restricting to Kill Zone sessions (GO Sessions) improves Calmar ratio from 11.7 to 15.4 while reducing trade count. For risk-adjusted performance, GO Sessions is preferred.

### Finding 5 — PD and Strong Filters Are Marginal

Neither filter has a clear decisive edge. Strong_OFF slightly better on Calmar; PD_ON slightly better on Adj Sharpe. Recommend OFF for both to maximize trade frequency without meaningfully harming quality.

---

## Top 20 Setups by Total R

Across all 6 instruments, 2022–2026:

| Rank | TF | Entry | Style | Sessions | Strong | P/D | N | WR% | AvgR | TotalR | PF | MaxDD |
|------|-----|-------|-------|----------|--------|-----|---|-----|------|--------|----|-------|
| 1 | H1-M5 | OB_only | Confirm | All | OFF | OFF | 20,901 | 70.3 | 0.189 | +3,943 | 1.54 | 92.76 |
| 2 | H1-M5 | OB_only | Confirm | All | OFF | ON | 15,151 | 70.1 | 0.219 | +3,313 | 1.51 | 99.01 |
| 3 | H1-M5 | OB_only | Confirm | GO | OFF | OFF | 12,738 | 69.3 | 0.176 | +2,244 | 1.50 | 51.40 |
| 4 | H1-M5 | OB_only | Confirm | GO | OFF | ON | 9,106 | 69.4 | 0.207 | +1,886 | 1.47 | 53.52 |
| 5 | H1-M15 | OB_only | Confirm | All | OFF | OFF | 14,247 | 68.2 | 0.123 | +1,753 | 1.30 | 286.41 |
| 6 | H1-M15 | OB_only | Confirm | All | OFF | ON | 9,409 | 72.1 | 0.164 | +1,539 | 1.30 | 286.22 |
| 7 | H4-M5 | OB_only | Confirm | All | OFF | OFF | 5,056 | 72.6 | 0.285 | +1,440 | 1.96 | 32.32 |
| 8 | H4-M15 | OB_only | Confirm | All | OFF | OFF | 3,610 | 76.8 | 0.384 | +1,388 | 2.55 | 59.13 |
| 9 | H4-M5 | OB_only | Confirm | All | OFF | ON | 4,072 | 71.1 | 0.318 | +1,295 | 1.95 | 33.64 |
| 10 | H4-M15 | OB_only | Confirm | All | OFF | ON | 2,745 | 77.0 | 0.459 | +1,261 | 2.59 | 58.87 |
| 11 | H1-M5 | OB_only | Confirm | All | ON | OFF | 4,558 | 72.6 | 0.219 | +1,000 | 2.30 | 22.36 |
| **12** | **H4-M5** | **OB_only** | **Confirm** | **GO** | **OFF** | **OFF** | **3,004** | **75.0** | **0.330** | **+992** | **2.31** | **7.07** |
| 13 | H4-M15 | OB+FVG | Confirm | All | OFF | ON | 3,009 | 70.1 | 0.310 | +934 | 1.94 | 13.24 |
| 14 | H4-M5 | OB_only | Confirm | GO | OFF | ON | 2,299 | 73.4 | 0.381 | +876 | 2.29 | 8.87 |
| 15 | H4-M15 | OB+FVG | Confirm | All | OFF | OFF | 3,873 | 69.6 | 0.224 | +867 | 1.77 | 12.21 |

> **Note:** ALL top 20 setups use `Confirm(MSS)` entry style without exception.  
> Risk entries do not appear anywhere in the profitable setups.

---

## Risk-Adjusted Rankings

Ranking by **Composite Score** (40% Calmar + 40% Adj Sharpe + 20% Expectancy):

> **Calmar** = Total R / Max DD  
> **Adj Sharpe** = (Avg R × √N) / Std(R) — rewards edge strength AND statistical confidence

| Rank | TF | Entry | Style | Sessions | N | WR% | AvgR | TotalR | MaxDD | **R/DD** | **AdjSharpe** |
|------|-----|-------|-------|----------|---|-----|------|--------|-------|----------|--------------|
| **1** | **H4-M5** | **OB_only** | **Confirm** | **GO** | **3,004** | **75.0** | **0.330** | **+992** | **7.07** | **140.3** | **19.3** |
| 2 | H4-M5 | OB_only | Confirm | GO | 2,299 | 73.4 | 0.381 | +876 | 8.87 | 98.8 | 17.6 |
| 3 | H4-M15 | OB+FVG | Confirm | GO | 1,697 | 72.2 | 0.350 | +594 | 7.87 | 75.5 | 12.2 |
| 4 | H4-M5 | OB_only | Confirm | All | 5,056 | 72.6 | 0.285 | +1,440 | 32.32 | 44.6 | 18.0 |
| 5 | H4-M5 | OB_only | Confirm | All | 4,072 | 71.1 | 0.318 | +1,295 | 33.64 | 38.5 | 16.5 |
| 6 | H4-M15 | OB+FVG | Confirm | All | 3,009 | 70.1 | 0.310 | +934 | 13.24 | 70.6 | 15.1 |
| 7 | H4-M15 | OB+FVG | Confirm | All | 240 | 84.2 | 0.566 | +136 | 4.07 | 33.4 | 11.5 |
| 8 | H4-M15 | OB_only | Confirm | All | 3,610 | 76.8 | 0.385 | +1,388 | 59.13 | 23.5 | 16.1 |

**The same setup ranks #1 on all three individual metrics simultaneously** — Calmar, Adj Sharpe, and Composite Score.

---

## Walk-Forward Validation

The #1 risk-adjusted setup (`H4-M5 | OB_only | Confirm(MSS) | GO_Sessions`) was validated out-of-sample using a strict calendar split:

- **In-Sample (IS):** 2022-05-12 → 2024-12-31
- **Out-of-Sample (OOS):** 2025-01-01 → 2026-01-31

### Results by Instrument

**In-Sample:**
| Instrument | N | WR% | AvgR | TotalR | PF | MaxDD |
|-----------|---|-----|------|--------|----|-------|
| EURUSD | 391 | 75.2 | 0.317 | +124.06 | 2.28 | 5.12 |
| GBPUSD | 357 | 74.2 | 0.321 | +114.48 | 2.29 | 4.15 |
| USDJPY | 422 | 73.0 | 0.317 | +133.57 | 2.15 | 5.58 |
| XAUUSD | 391 | 73.7 | 0.256 | +100.25 | 1.93 | 6.51 |
| NAS100 | 258 | 80.6 | 0.434 | +111.99 | 3.11 | 3.10 |
| US30 | 236 | 76.7 | 0.385 | +90.94 | 2.69 | 4.12 |
| **TOTAL** | **2,055** | **75.1** | **0.329** | **+675.28** | **2.31** | **6.51** |

**Out-of-Sample:**
| Instrument | N | WR% | AvgR | TotalR | PF | MaxDD |
|-----------|---|-----|------|--------|----|-------|
| EURUSD | 186 | 69.9 | 0.287 | +53.40 | 2.02 | 4.47 |
| GBPUSD | 169 | 72.2 | 0.229 | +38.65 | 1.78 | 7.07 |
| USDJPY | 174 | 74.7 | 0.279 | +48.59 | 2.08 | 4.62 |
| XAUUSD | 182 | 80.2 | 0.413 | +75.17 | 3.01 | 3.69 |
| NAS100 | 127 | 77.2 | 0.363 | +46.05 | 2.50 | 3.72 |
| US30 | 108 | 75.0 | 0.499 | +53.86 | 3.11 | 3.85 |
| **TOTAL** | **946** | **74.7** | **0.334** | **+315.72** | **2.31** | **7.07** |

### Walk-Forward Summary

| Metric | IS (Train) | OOS (Test) | Retention |
|--------|-----------|-----------|-----------|
| Win Rate | 75.1% | 74.7% | **99.5%** |
| Avg R per trade | 0.329 | 0.334 | **101.5% — improves OOS** |
| Profit Factor | 2.31 | 2.31 | **100.0%** |
| Max Drawdown | 6.51R | 7.07R | (lower = better) |
| Calmar Ratio | 103.73 | 44.66 | — |

**Verdict: STRONG PASS** — The edge is not curve-fitted. Win rate, avg R, and profit factor are essentially identical in-sample vs out-of-sample.

---

## Dimension Analysis

Average metrics across all tested setups, grouped by each parameter:

### Entry Style (Most Critical Parameter)
| Style | Avg Total R | Avg Calmar | Avg Adj Sharpe |
|-------|------------|-----------|---------------|
| Confirm(MSS) | **+415** | **29.1** | **9.35** |
| Risk(no_MSS) | -539 | -0.9 | -4.57 |

### Entry Type
| Type | Avg Total R | Avg Calmar | Avg Adj Sharpe |
|------|------------|-----------|---------------|
| OB+FVG | -100 | 24.1 | 3.34 |
| OB_only | **+185** | **17.1** | **4.63** |
| FVG_only | -363 | 3.7 | -1.33 |

### Timeframe
| TF | Avg Calmar | Avg Adj Sharpe |
|----|-----------|---------------|
| H4-M5 | **15.9** | 1.78 |
| H4-M15 | 11.9 | **2.34** |

### Sessions
| Sessions | Avg Calmar |
|---------|-----------|
| GO_Sessions | **15.4** |
| All_Sessions | 11.7 |

---

## Recommended Setup

Based on all 240 tested combinations, 198 completed backtests, and walk-forward validation:

### For Risk-Adjusted / Capital Preservation Priority
```
Timeframe pair:  H4 bias → M5 entry
Entry type:      Order Blocks only (OB_only)
Entry style:     Confirmation — wait for MSS/CHoCH on M5
Sessions:        GO Sessions only (London KZ, London, NY AM KZ)
Strong filter:   OFF
PD filter:       OFF

Results:  +992R | 75% WR | PF 2.31 | Max DD 7.07R | Calmar 140
```

### For Maximum Absolute Return (Higher Trade Frequency)
```
Timeframe pair:  H1 bias → M5 entry
Entry type:      Order Blocks only (OB_only)
Entry style:     Confirmation — wait for MSS/CHoCH on M5
Sessions:        All Sessions
Strong filter:   OFF
PD filter:       OFF

Results:  +3,943R | 70% WR | PF 1.54 | Max DD 92.76R
```

### Decision Guide

| Priority | Recommended Setup |
|---------|-----------------|
| Minimize drawdown (prop firms, conservative accounts) | H4-M5, GO Sessions |
| Maximize total return (self-funded, aggressive) | H1-M5, All Sessions |
| Balanced approach | H4-M5, All Sessions (Rank #7 by Total R, #4 by Calmar) |

---

## Rules for Live Trading

These rules are derived directly from the backtesting data and should not be violated:

1. **ALWAYS use Confirmation (MSS) entry style.** Risk entries are negative expectancy on average.
2. **Use H4 bias.** It produces lower drawdown and higher per-trade quality than H1.
3. **Use M5 for entry timing.** M5 gives tighter entries and better R:R than M15.
4. **Trade OB_only.** FVGs alone are negative; OB+FVG is lower Adj Sharpe than OB alone.
5. **Stick to Kill Zone sessions.** GO Sessions gives better Calmar. Avoid off-hours.
6. **Do not use Strong or PD filters** — they reduce trade count without proportional quality improvement.
7. **Respect the structure.** The MSS entry requires patience — wait for the confirmation candle close before entering. Jumping the gun converts a Confirmation setup into a Risk entry.
8. **Trade all 6 instruments.** Diversification is what makes the Calmar ratio of 140 possible — no single instrument alone achieves this.

---

## Files

| File | Description |
|------|-------------|
| `results/setup_results.csv` | All 198 tested setups, ranked by Total R |
| `results/risk_adjusted_results.csv` | 80 setups with Calmar, Adj Sharpe, Composite Score |
| `results/ICT_Setup_Research_Report.pdf` | Full 18-page research report (PDF) |
| `research/batch_setup_test.py` | Script that ran all 240 parameter combinations |
| `research/batch_risk_adjusted.py` | Re-run with risk-adjusted metrics |
| `research/walk_forward_rank12.py` | Walk-forward validation of the top risk-adjusted setup |
| `Python_Project/engine/phase2_engine.py` | Core backtest engine |
| `Python_Project/dashboard/app.py` | Interactive Dash dashboard |
| `Python_Project/ICT_MultiTF_Strategy.pine.txt` | TradingView Pine Script implementation |
| `MT5_Project/EA/` | MetaTrader 5 Expert Advisors (v1.0–v1.3) |

---

*Research period: 2022-05-12 to 2026-01-31 | 6 instruments | 198–240 parameter combinations*

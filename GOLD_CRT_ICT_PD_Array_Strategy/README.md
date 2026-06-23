# GOLD / FX — ICT & CRT Strategy Backtesting Research

A Python backtesting suite for three trading strategies built on **ICT (Inner Circle Trader)** and **CRT (Candle Range Theory)** concepts. All strategies are tested on 4 years of tick-accurate Dukascopy M5/M15 data (May 2022 – May 2026).

---

## Strategies Overview

| # | Strategy | Engine | Symbol | Trades | Win Rate | Total R | PF |
|---|---|---|---|---|---|---|---|
| 1 | CRT — Candle Range Theory | `crt_engine.py` | GBPUSD | 2,177 | 35.7% | −18.38R | 0.99 |
| 2 | ICT H4 OB + M5 MSS | `gold_ict_engine.py` | XAUUSD | 66 | 28.8% | +1.32R | 1.03 |
| 3 | ICT Power of 3 (P.O.3) | `po3_engine.py` | XAUUSD | 1,434 | 30.5% | +39.27R | 1.04 |

---

## Strategy 1 — CRT (Candle Range Theory)

### How It Works

The CRT strategy is a **3-candle reversal pattern** that trades false breakouts of higher-timeframe dealing ranges.

**Three phases:**

1. **Reference candle** — A closed H4 bar establishes the dealing range (`ref_high` / `ref_low`)
2. **Sweep / Liquidation** — A lower-timeframe candle wicks *beyond* one extreme of the range, hunting stop orders
3. **Re-entry (Entry)** — A candle closes *back inside* the range — this is the entry signal

**Entry direction:**
- **Bull CRT**: Price sweeps below `ref_low` → closes back above `ref_low` → go long  
- **Bear CRT**: Price sweeps above `ref_high` → closes back below `ref_high` → go short

**Trade management:**
- **SL**: Beyond the deepest sweep wick ± ATR(14) × sl_buffer
- **TP**: The opposite extreme of the reference candle (`ref_high` for bull, `ref_low` for bear)
- **Trend filter**: H4 price vs SMA-200 — bull CRTs only when above SMA200; bear only when below
- **Session**: London (02:00–08:00 NY) and New York (08:00–13:00 NY)
- **Max hold**: Force-close after `max_hold_bars` bars

### Backtest Results (GBPUSD, May 2022 – May 2026)

| Metric | All | Bull | Bear |
|---|---|---|---|
| Trades | 2,177 | 1,110 | 1,067 |
| Win Rate | 35.7% | 35.5% | 35.9% |
| Total R | −18.38R | −28.27R | +9.89R |
| Profit Factor | 0.99 | — | — |
| Max Drawdown | 88.88R | — | — |

**Key finding:** Bear CRTs show positive R (+9.89R) on GBPUSD while bull CRTs lose significantly (−28.27R). The strategy frequency (2,177 trades over 4 years) is high — quality filtering via `--min-rr` and `--session-mode tight` improves precision.

### Usage

```bash
# Default run (4H ref candle, 5M entry, full range)
python run_crt_backtest.py

# Tighter session filter + minimum natural RR
python run_crt_backtest.py --session-mode tight --min-rr 1.5

# 1H reference candle
python run_crt_backtest.py --htf 1h --tf 5m

# Custom date range
python run_crt_backtest.py --start 2024-01-01 --end 2026-05-01
```

---

## Strategy 2 — ICT H4 Order Block + M5 Market Structure Shift

### How It Works

A two-timeframe strategy: the **H4 chart** identifies institutional Order Block zones; the **M5 chart** provides the entry trigger when structure shifts inside that zone.

**Step-by-step:**

1. **Order Block Detection (H4)**
   - **Bull OB**: A strong bullish H4 impulse candle (body > 80% ATR) → the prior *bearish* candle becomes the Bull OB zone
   - **Bear OB**: A strong bearish H4 impulse candle → the prior *bullish* candle becomes the Bear OB zone
   - OBs are cancelled if price closes through them by more than 0.2 × ATR

2. **Session Filter**: London KZ (02–05 NY), London (05–08 NY), NY AM KZ (07–10 NY)

3. **Entry: Market Structure Shift (M5)**
   - Price must be *inside* an active OB zone
   - **Bull MSS**: M5 close breaks above the 10-bar swing high → long entry
   - **Bear MSS**: M5 close breaks below the 10-bar swing low → short entry

4. **Exit**
   - SL: OB edge ± ATR × sl_buffer
   - TP: entry + risk × rr_target (default 3R)
   - Also exits on OB invalidation or 48-hour max hold

### Backtest Results (XAUUSD, May 2022 – May 2026)

| Metric | All Directions | Bull Only | Best Config |
|---|---|---|---|
| Trades | 66 | 28 | 17 |
| Win Rate | 28.8% | 35.7% | **47.1%** |
| Total R | +1.32R | +6.81R | **+8.47R** |
| Profit Factor | 1.03 | 1.41 | **1.94** |
| Max Drawdown | 10.87R | 8.45R | **3.02R** |

**Best config** (2024+, bull-only, SL=0.3×ATR, RR=3): The 2024+ period covers Gold's parabolic move from ~$2,000 → ~$3,300 where H4 bull OBs held cleanly. The wider SL gives trades room to survive Gold's large wicks.

### Parameter Sweep Summary (`test_setups.py`, 27 setups × 7 families)

```
Family       Name                  N    WR%   TotalR    PF   MaxDD
BASELINE     default-3R           66   28.8%  +1.32   1.03   10.9
DIRECTION    bull-only-3R         28   35.7%  +6.81   1.41    8.5
DIRECTION    bear-only-3R         38   23.7%  -5.49   0.79   10.0
COMBO        bull-sl0.3-rr2       30   43.3%  +4.22   1.26    8.4
COMBO        bull-sl0.3-rr3       28   35.7%  +5.00   1.30    8.4
COMBO        bull-2024-sl0.3-rr2  19   52.6%  +5.65   1.63    3.0
COMBO        bull-2024-sl0.3-rr3  17   47.1%  +8.47   1.94    3.0  <- best
```

Full results: `results/ict_h4ob_setups.csv`

### Usage

```bash
# Default run
python run_backtest.py

# Best optimised config
python run_backtest.py --start 2024-01-01 --rr 3.0 --sl-buf 0.3

# Parameter sweep
python test_setups.py          # 27 setups (~25 min)
python test_setups.py --quick  # 9 setups (~5 min)
```

---

## Strategy 3 — ICT Power of 3 (P.O.3) Liquidity Sweep + MSS

### How It Works

The P.O.3 strategy trades the three-phase institutional manipulation cycle:

1. **Accumulation** — Price consolidates, building equal highs/lows (liquidity pools)
2. **Manipulation** — A M15 candle wicks *beyond* the N-bar swing level then **closes back inside** (Turtle Soup / Liquidity Sweep)
   - Bull sweep: `high > swing_hi AND close < swing_hi`
   - Bear sweep: `low < swing_lo AND close > swing_lo`
3. **Distribution** — After a sweep, wait for M5 Market Structure Shift in the *opposite* direction:
   - Bull sweep → expect bearish reversal → wait for M5 bearish MSS → short
   - Bear sweep → expect bullish reversal → wait for M5 bullish MSS → long

**Trade management:**
- SL: Beyond the sweep wick extreme ± ATR(14) × sl_buffer
- TP: entry ± risk × rr_target
- Optional FVG confluence filter (Fair Value Gap must be present at entry)
- Sweep expires after `max_sweep_m15` M15 bars with no entry
- Max hold: 192 M5 bars (~16 hours)

### Backtest Results (XAUUSD, May 2022 – May 2026)

| Metric | All | Bull (long) | Bear (short) |
|---|---|---|---|
| Trades | 1,434 | 663 | 771 |
| Win Rate | 30.5% | 32.1% | 29.2% |
| Total R | +39.27R | +50.68R | −11.42R |
| Profit Factor | 1.04 | — | — |
| Max Drawdown | 37.56R | — | — |
| Max Loss Streak | 22 | — | — |

**Signal pipeline:** 4,661 bull sweeps + 3,685 bear sweeps detected → 1,458 MSS signals → 1,434 entries taken. 3,123 sweeps expired without an MSS entry.

**Key finding:** Same directional asymmetry as the H4 OB strategy — Gold's structural uptrend makes bear reversals risky. Bull (long) P.O.3 trades contribute +50.68R while bear (short) trades lose −11.42R. Filtering to bull-only or using a larger swing lookback (30–50) for higher-quality sweeps improves performance significantly.

### Parameter Sweep Summary (`test_po3_setups.py`, 23 setups × 9 families)

```
Family       Name                  N    WR%   TotalR    PF   MaxDD
BASELINE     default            1434   30.5%  +39.27  1.04   37.6
SWING        swing-30           1013   31.3%  +31.78  1.04   29.9
SWING        swing-40            829   32.2%  +29.12  1.05   24.4
SWING        swing-50            688   32.7%  +25.93  1.06   19.8
RR           rr-2.0             1434   30.5%  +24.38  1.05   28.1
FVG          fvg-rr3             195   37.9%  +18.07  1.22    9.2
PERIOD       2024+               558   34.4%  +29.63  1.12   17.7
COMBO        swing30-rr2-fvg     104   41.3%   +9.17  1.22    8.3
```

Full results: `results/po3_setup_results.csv`

### Usage

```bash
# Default run (XAUUSD)
python run_po3.py

# Save trade log
python run_po3.py --save

# GBPUSD with FVG filter
python run_po3.py --symbol GBPUSD --fvg

# Best combo: larger swing + FVG confluence
python run_po3.py --swing 30 --rr 2.0 --fvg

# 2024 onwards only
python run_po3.py --start 2024-01-01

# Parameter sweep (23 setups × 2 symbols)
python test_po3_setups.py
python test_po3_setups.py --quick           # BASELINE + COMBO only
python test_po3_setups.py --symbol XAUUSD   # one symbol
```

---

## Project Structure

```
GOLD_CRT_ICT_PD_Array_Strategy/
│
├── engine/
│   ├── __init__.py
│   ├── crt_engine.py           # Strategy 1: CRT 3-candle reversal
│   ├── crt_full_engine.py      # CRT with extended parameter set
│   ├── gold_ict_engine.py      # Strategy 2: ICT H4 OB + M5 MSS
│   └── po3_engine.py           # Strategy 3: ICT Power of 3 Liquidity Sweep
│
├── data/
│   ├── m15/
│   │   ├── XAUUSD_M15.parquet       # XAUUSD 15M bars (Dukascopy)
│   │   └── GBPUSD_M15.parquet       # GBPUSD 15M bars (Dukascopy)
│   ├── m5/
│   │   ├── XAUUSD_M5.parquet        # XAUUSD 5M bars (Dukascopy)
│   │   └── GBPUSD_M5.parquet        # GBPUSD 5M bars (Dukascopy)
│   ├── h4/
│   │   ├── XAUUSD_H4.parquet        # XAUUSD 4H bars (resampled from M15)
│   │   └── GBPUSD_H4.parquet        # GBPUSD 4H bars
│   └── daily/
│       └── XAUUSD_D1.parquet        # XAUUSD daily bars
│
├── data_fetch/
│   ├── fetch_gold_yahoo.py      # Download Gold data from Yahoo Finance
│   ├── resample_dukascopy.py    # Resample M15 → H4 for Gold
│   └── resample_gbpusd.py       # Resample GBPUSD data
│
├── results/
│   ├── crt_trades.csv           # CRT strategy: all 2,177 GBPUSD trades
│   ├── ict_h4ob_trades.csv      # H4 OB strategy: all 66 XAUUSD trades
│   ├── ict_h4ob_setups.csv      # H4 OB strategy: 9-setup parameter sweep
│   ├── po3_xauusd_trades.csv    # P.O.3 strategy: all 1,434 XAUUSD trades
│   └── po3_setup_results.csv    # P.O.3 strategy: full parameter sweep output
│
├── run_crt_backtest.py          # Runner for CRT strategy
├── run_backtest.py              # Runner for ICT H4 OB strategy
├── run_po3.py                   # Runner for ICT P.O.3 strategy
├── test_setups.py               # Parameter sweep for H4 OB (27 setups)
├── test_po3_setups.py           # Parameter sweep for P.O.3 (23 setups)
├── analyse_trades.py            # Trade distribution analysis (CRT)
└── requirements.txt
```

---

## Setup & Installation

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Data

All primary backtest data uses **Dukascopy** M5 and M15 exports placed in `data/m5/` and `data/m15/`. The `data_fetch/` scripts handle Yahoo Finance data (limited to 60 days of 5M data).

| Source | Coverage | Timeframes |
|---|---|---|
| Dukascopy | May 2022 – May 2026 | M5, M15 |
| Yahoo Finance | 2021 – present | Daily, 1H |
| Yahoo Finance | Last 60 days | 5M (hard limit) |

---

## Key Findings Across All Strategies

1. **Gold's bull trend dominates** — all three strategies show better results on long (bull) trades than short (bear) trades on XAUUSD. Bear reversal signals frequently fail against the structural uptrend.

2. **FVG confluence improves quality** — adding a Fair Value Gap filter to P.O.3 lifts win rate from 30.5% → 37.9% while reducing trade count from 1,434 → 195. Quality over quantity.

3. **2024+ is the cleanest period** — Gold's trend from ~$2,000 → ~$3,300 produced clean Order Block reactions and liquidity sweeps. Best configs on both H4 OB and P.O.3 point to 2024 onwards.

4. **CRT works better on GBPUSD bear side** — bear CRTs produced +9.89R while bull CRTs lost −28.27R. The SMA-200 trend filter helps but GBPUSD had a structural range-to-bear shift in 2022–2024.

---

## Requirements

```
pandas>=2.0.0
numpy>=1.24.0
pyarrow>=12.0.0
yfinance>=0.2.36
```

---

## Disclaimer

This project is for educational and research purposes only. Past backtest performance does not guarantee future results. This is not financial advice.

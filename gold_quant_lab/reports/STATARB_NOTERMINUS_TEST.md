# noterminusgit/statarb — Pulled, Inspected, Tested

## What it is
A genuinely institutional-grade statistical-arbitrage system: 20+ alpha strategies,
PCA + Barra factor risk model, NLP portfolio optimizer with transaction-cost and
participation constraints, four simulation engines (daily/order/intraday/full),
daily rebalance across ~1,400 US equities. Recently migrated to Python 3 (99% test pass).
Engineering quality is high — realistic market-impact, slippage, borrow-cost modeling.

## Can it be run as-is? No.
It depends on **proprietary, paid data** and ships with **no sample data**:
- **Barra** risk-model factors (MSCI — paid) — 13 factors + 58 GICS industries
- **IBES** analyst estimates (LSEG/Refinitiv — paid)
- **Short-locate / borrow availability** (broker-proprietary)
- A US-equity **security master + multi-year daily + 30-min intraday** price history (~1,400 names)

Without those feeds (tens of thousands $/yr) the pipeline can't load, optimize, or simulate.
So a faithful "run the repo" test isn't possible here.

## What we CAN test: its core portable alpha
The system's central price-only idea is **PCA residual mean-reversion** (Avellaneda–Lee):
decompose returns into principal components, regress each asset on them, and bet that the
idiosyncratic **residual** reverts (short rich, long cheap, dollar-neutral). We implemented
this faithfully (`research_scripts/pca_statarb.py`) and ran it on the 13-instrument daily
basket (FX majors + indices + metals, 2014–2026).

| PCA stat-arb (60d window, 3 PCs, dollar-neutral) | Ann return | Sharpe | Max DD |
|---|---|---|---|
| Full 2014–2026 | +0.2% | **0.02** | −29.5% |
| 2014–2020 | −0.2% | −0.02 | −29.5% |
| 2020–2026 | +0.7% | 0.05 | −21.4% |

## Read-out: flat — because it's the wrong universe, not a broken method
PCA residual reversion needs a **large, homogeneous cross-section** (hundreds–thousands of
single-name equities) so there are abundant idiosyncratic residuals to harvest. Our basket
has only 13 *heterogeneous macro* assets — the principal components absorb nearly all the
variance and there's almost no stable idiosyncratic residual left to trade. So the alpha is
~zero here. This is expected and is **not** evidence for or against the strategy on its
intended universe.

## Honest verdict
- **Quality:** real, professional stat-arb engineering — far above the ICT/EA material.
- **Usability for you:** low without paid data feeds and a full equity universe.
- **Its core alpha on data we have:** flat (wrong universe).
- **To actually validate it** you'd need daily history for a few hundred liquid US equities
  (free-ish, but the research sandbox can't reach equity-data hosts — would be fetched on
  your machine or via an API you hold). Then the PCA stat-arb (and a pairs/cointegration
  variant) can be tested properly on the universe it was designed for.

## Bottom line
This is the most serious codebase of the leads, but it's an institutional system gated behind
institutional data. The transferable, free-data idea (PCA residual reversion) is sound but needs
a big equity universe to show edge — it does nothing on a 13-asset macro basket. Of everything
tested, **diversified 12-month momentum remains the best edge that works on the data you actually have.**

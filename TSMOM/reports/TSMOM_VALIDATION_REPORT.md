# TSMOM Basket — Validation (the first real edge)

14-instrument daily basket (metals, FX majors, US indices, DXY), 2014-2026, via
the existing `tsmom_basket.py` logic: long if 12m return>0 else short, inverse-vol
sized to 10% target, monthly rebalance.

## Headline (net of 2bps)
```
Sharpe 0.37 | ann 2.0% | vol 5.2% | maxDD -11.9%
cost sweep:  2bps 0.37 | 5bps 0.35 | 10bps 0.31     (survives realistic costs)
regimes:     2015-18 0.52 | 2018-22 0.27 | 2022-26 0.32  (positive in ALL thirds)
```

## Validation
- **Breadth:** 10/14 instruments individually positive (NAS100 +0.54, XAG +0.40,
  SPX +0.29, COPPER +0.26 strongest). Broad, not one name.
- **Beta check (critical):** TSMOM Sharpe 0.37 vs PASSIVE long basket 0.39. Over
  this window TSMOM did NOT beat passive long — BUT corr(TSMOM, passive) = 0.23,
  so it is a near-independent return stream, valuable as a DIVERSIFIER, not a
  standalone outperformer.
- **Excluding gold+equities (10 names):** Sharpe 0.23 — edge leans on the strong
  trenders but survives without them.
- **Cross-sectional rel-strength (63d quartiles):** Sharpe 0.10 — much weaker;
  time-series (absolute) momentum is the right tool for this small, correlated set.

## Verdict
A REAL, broad, regime-robust, cost-surviving edge (unlike the ICT structural
family, which was zero-to-negative everywhere). Magnitude is MODEST (Sharpe ~0.37,
post-2010 trend-following decay visible in the 2018-22 third). Most valuable
combined with low-correlation streams rather than standalone.

## To make it compelling
1. Broaden the universe (rates, energy, ags, more index/EM) -> avg |corr| 0.36 is
   the ceiling here; a real CTA basket runs 0.1-0.2 and Sharpe rises with breadth.
2. Combine with passive-long and/or other low-corr signals (0.23 corr => the blend
   Sharpe exceeds either alone).
3. Port into the gateway and forward-test; this is the horse worth developing.

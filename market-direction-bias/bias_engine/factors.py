"""The factor layer: turn PyIndicator outputs into transparent -1/0/+1 votes.

Each factor is a small pure function that reads one already-computed bar (a
pandas Series / mapping) and returns a ``Vote``: the integer direction plus a
short human-readable reason. Keeping these pure and independent is what makes
the engine auditable -- you can see exactly why each factor voted the way it
did, and you can unit-test each one in isolation.

The functions are tolerant of warm-up NaNs: if the indicator hasn't formed
yet, the factor abstains (votes 0) rather than guessing.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from .config import BiasConfig


@dataclass(frozen=True)
class Vote:
    direction: int   # -1 bearish, 0 neutral/abstain, +1 bullish
    detail: str      # why -- shown in the breakdown


def _is_missing(x) -> bool:
    if x is None:
        return True
    if isinstance(x, float) and math.isnan(x):
        return True
    if isinstance(x, str) and x.strip() == "":
        return True
    return False


def structure_vote(bar, cfg: BiasConfig) -> Vote:
    """Dominant factor: where market structure says price is trying to go.

    ``market_trend`` from PyIndicators' CHoCH/BOS detector already integrates
    the structural picture (it flips on a Change of Character and confirms on a
    Break of Structure), so we read direction straight from it. We surface the
    most recent CHoCH/BOS event in the detail so the *reason* for the trend is
    visible, not just its sign.
    """
    trend = bar.get("market_trend")
    if _is_missing(trend):
        return Vote(0, "structure: not formed")
    trend = int(trend)

    events = []
    if bar.get("choch_bullish"):
        events.append("CHoCH+")
    if bar.get("choch_bearish"):
        events.append("CHoCH-")
    if bar.get("bos_bullish"):
        events.append("BOS+")
    if bar.get("bos_bearish"):
        events.append("BOS-")
    ev = (" [" + ",".join(events) + "]") if events else ""

    if trend > 0:
        return Vote(1, f"structure: market_trend bullish{ev}")
    if trend < 0:
        return Vote(-1, f"structure: market_trend bearish{ev}")
    return Vote(0, f"structure: market_trend neutral{ev}")


def swing_vote(bar, cfg: BiasConfig) -> Vote:
    """Swing sequence: HH/HL is bullish, LH/LL is bearish.

    ``swing_direction`` is already encoded -1/0/+1 by PyIndicators; the
    ``swing_structure`` label (HH/HL/LH/LL) is the readable evidence.
    """
    direction = bar.get("swing_direction")
    label = bar.get("swing_structure")
    label_txt = f" ({label})" if not _is_missing(label) else ""
    if _is_missing(direction):
        return Vote(0, "swing: not formed")
    d = int(direction)
    if d > 0:
        return Vote(1, f"swing: higher structure{label_txt}")
    if d < 0:
        return Vote(-1, f"swing: lower structure{label_txt}")
    return Vote(0, f"swing: balanced{label_txt}")


def supertrend_vote(bar, cfg: BiasConfig) -> Vote:
    """SuperTrend trailing stop: price above line = bull (1), below = bear (0)."""
    t = bar.get("supertrend_trend")
    if _is_missing(t):
        return Vote(0, "supertrend: not formed")
    return Vote(1, "supertrend: bullish") if int(t) == 1 else Vote(-1, "supertrend: bearish")


def directional_vote(bar, cfg: BiasConfig) -> Vote:
    """+DI vs -DI: which directional movement dominates.

    Abstains when the two are within ``di_margin`` of each other, so balanced
    directional movement doesn't get forced into a side.
    """
    dip = bar.get("+DI")
    dim = bar.get("-DI")
    if _is_missing(dip) or _is_missing(dim):
        return Vote(0, "directional: not formed")
    dip, dim = float(dip), float(dim)
    if abs(dip - dim) <= cfg.di_margin:
        return Vote(0, f"directional: balanced (+DI {dip:.1f} ~ -DI {dim:.1f})")
    if dip > dim:
        return Vote(1, f"directional: +DI {dip:.1f} > -DI {dim:.1f}")
    return Vote(-1, f"directional: -DI {dim:.1f} > +DI {dip:.1f}")


def premium_discount_vote(bar, cfg: BiasConfig) -> Vote:
    """Location within the dealing range.

    Smart-Money convention (default): a *discount* (lower half of the range) is
    where you want to buy (bullish, +1) and a *premium* (upper half) is where
    you want to sell (bearish, -1). Set ``cfg.discount_is_bullish=False`` to
    invert the reading.

    ``pdz_zone`` gives the side; ``pdz_zone_pct`` is the *depth into that zone*
    (0 = right at equilibrium, 100 = at the range extreme) -- NOT the absolute
    position in the range. So "premium, 17% into zone" means price is only just
    above fair value. When that depth is below ``cfg.pd_equilibrium_band`` the
    location read is too weak to trust, so the factor abstains rather than cast
    a full vote off a hair away from equilibrium.
    """
    zone = bar.get("pdz_zone")
    pct = bar.get("pdz_zone_pct")
    depth = None if _is_missing(pct) else float(pct)
    depth_txt = "" if depth is None else f", {depth:.0f}% into zone"
    if _is_missing(zone):
        return Vote(0, "premium/discount: range not formed")
    zone = str(zone).strip().lower()
    if zone not in ("premium", "discount"):
        return Vote(0, f"premium/discount: {zone or 'equilibrium'}{depth_txt}")
    # Regime-aware: location is a mean-reversion read, useful only inside a
    # range. In a trend it just fights the move, so abstain. We read the regime
    # off the same ADX the engine's gate uses, so the two stay consistent.
    if cfg.pd_regime_aware:
        adx = bar.get("ADX")
        ranging = (not _is_missing(adx)) and float(adx) < cfg.adx_ranging_threshold
        if not ranging:
            return Vote(0, f"premium/discount: {zone}, muted in trend{depth_txt}")
    if depth is not None and depth < cfg.pd_equilibrium_band:
        return Vote(0, f"premium/discount: {zone} but near equilibrium{depth_txt}")
    bull = 1 if cfg.discount_is_bullish else -1
    if zone == "discount":
        return Vote(bull, f"premium/discount: discount{depth_txt}")
    return Vote(-bull, f"premium/discount: premium{depth_txt}")


# Ordered registry: (factor key, weight attribute, vote function).
# The key is also the column suffix used in the per-bar output.
FACTORS = (
    ("structure", "structure", structure_vote),
    ("swing", "swing", swing_vote),
    ("supertrend", "supertrend", supertrend_vote),
    ("directional", "directional", directional_vote),
    ("premium_discount", "premium_discount", premium_discount_vote),
)

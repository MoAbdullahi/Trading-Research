from __future__ import annotations
from dataclasses import dataclass
import math
from .config import BiasConfig
@dataclass(frozen=True)
class Vote:
    direction: int
    detail: str
def _is_missing(x):
    if x is None: return True
    if isinstance(x,float) and math.isnan(x): return True
    if isinstance(x,str) and x.strip()=="": return True
    return False
def structure_vote(bar,cfg):
    t=bar.get("market_trend")
    if _is_missing(t): return Vote(0,"structure: not formed")
    t=int(t)
    return Vote(1,"structure: bull") if t>0 else (Vote(-1,"structure: bear") if t<0 else Vote(0,"structure: neutral"))
def swing_vote(bar,cfg):
    d=bar.get("swing_direction")
    if _is_missing(d): return Vote(0,"swing: not formed")
    d=int(d)
    return Vote(1,"swing: higher") if d>0 else (Vote(-1,"swing: lower") if d<0 else Vote(0,"swing: balanced"))
def supertrend_vote(bar,cfg):
    t=bar.get("supertrend_trend")
    if _is_missing(t): return Vote(0,"supertrend: not formed")
    return Vote(1,"supertrend: bull") if int(t)==1 else Vote(-1,"supertrend: bear")
def directional_vote(bar,cfg):
    dip=bar.get("+DI"); dim=bar.get("-DI")
    if _is_missing(dip) or _is_missing(dim): return Vote(0,"directional: not formed")
    dip,dim=float(dip),float(dim)
    if abs(dip-dim)<=cfg.di_margin: return Vote(0,"directional: balanced")
    return Vote(1,f"+DI>{dim:.0f}") if dip>dim else Vote(-1,f"-DI>{dip:.0f}")
def premium_discount_vote(bar,cfg):
    zone=bar.get("pdz_zone"); pct=bar.get("pdz_zone_pct")
    depth=None if _is_missing(pct) else float(pct)
    depth_txt="" if depth is None else f", {depth:.0f}% into zone"
    if _is_missing(zone): return Vote(0,"premium/discount: range not formed")
    zone=str(zone).strip().lower()
    if zone not in ("premium","discount"):
        return Vote(0,f"premium/discount: {zone or 'equilibrium'}{depth_txt}")
    if cfg.pd_regime_aware:
        adx=bar.get("ADX")
        ranging=(not _is_missing(adx)) and float(adx)<cfg.adx_ranging_threshold
        if not ranging:
            return Vote(0,f"premium/discount: {zone}, muted in trend{depth_txt}")
    if depth is not None and depth<cfg.pd_equilibrium_band:
        return Vote(0,f"premium/discount: {zone} but near equilibrium{depth_txt}")
    bull=1 if cfg.discount_is_bullish else -1
    if zone=="discount": return Vote(bull,f"premium/discount: discount{depth_txt}")
    return Vote(-bull,f"premium/discount: premium{depth_txt}")
FACTORS=(("structure","structure",structure_vote),("swing","swing",swing_vote),("supertrend","supertrend",supertrend_vote),("directional","directional",directional_vote),("premium_discount","premium_discount",premium_discount_vote))

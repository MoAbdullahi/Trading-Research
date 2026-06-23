import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bias_engine import BiasEngine, BiasConfig, FactorWeights
from bias_engine.factors import FACTORS, premium_discount_vote

def _ohlc(close, spread=0.4, seed=7):
    rng=np.random.default_rng(seed); n=len(close)
    high=close+np.abs(rng.normal(0,spread,n))+spread
    low=close-np.abs(rng.normal(0,spread,n))-spread
    op=close+rng.normal(0,spread/2,n)
    idx=pd.date_range("2024-01-01",periods=n,freq="h")
    return pd.DataFrame({"Open":op,"High":high,"Low":low,"Close":close,"Volume":rng.integers(1000,10000,n)},index=idx)

def uptrend(n=400): return _ohlc(np.linspace(100,200,n)+np.sin(np.linspace(0,12,n))*1.5)
def downtrend(n=400): return _ohlc(np.linspace(200,100,n)+np.sin(np.linspace(0,12,n))*1.5)
def ranging(n=400):
    rng=np.random.default_rng(3); return _ohlc(130+rng.normal(0,1.5,n),spread=0.25)

def test_default_weights_sum_to_one():
    assert abs(FactorWeights().total()-1.0)<1e-9
def test_uptrend_reads_bullish():
    r=BiasEngine().current_bias(uptrend()); assert r.bias==1,r.breakdown_table(); assert r.score>0
    assert next(c for c in r.components if c.name=="structure").vote==1
def test_downtrend_reads_bearish():
    r=BiasEngine().current_bias(downtrend()); assert r.bias==-1,r.breakdown_table(); assert r.score<0
def test_ranging_market_gate_engages():
    r=BiasEngine().current_bias(ranging())
    assert r.regime=="ranging",r.breakdown_table()
    assert r.neutral_band==BiasConfig().neutral_band_ranging
    assert abs(r.effective_score-r.score*0.5)<1e-6
def test_current_bias_has_all_components():
    r=BiasEngine().current_bias(uptrend())
    assert [c.name for c in r.components]==[k for k,_,_ in FACTORS]
    for c in r.components: assert abs(c.contribution-c.vote*c.weight)<1e-9
    assert abs(r.score-sum(c.contribution for c in r.components))<1e-6
def test_score_is_bounded():
    for df in (uptrend(),downtrend(),ranging()):
        out=BiasEngine().compute(df)
        assert out["bias_score"].between(-1,1).all()
        assert out["bias_effective_score"].between(-1,1).all()
        assert set(out["bias"].unique()).issubset({-1,0,1})
def test_compute_adds_expected_columns():
    out=BiasEngine().compute(uptrend())
    for k,_,_ in FACTORS: assert f"bias_vote_{k}" in out.columns
    for col in ("bias_score","bias_effective_score","bias_regime","bias","bias_label"): assert col in out.columns
def test_ablation_changes_score():
    df=uptrend(); full=BiasEngine().current_bias(df)
    ab=BiasEngine(BiasConfig(weights=FactorWeights(supertrend=0.0))).current_bias(df)
    st=next(c for c in full.components if c.name=="supertrend")
    if st.vote!=0: assert abs(ab.score-full.score)>1e-9
    st2=next(c for c in ab.components if c.name=="supertrend"); assert st2.weight==0 and st2.contribution==0
def test_premium_discount_sign_is_configurable():
    bar=BiasEngine()._ensure_indicators(uptrend()).iloc[-1]
    assert premium_discount_vote(bar,BiasConfig(discount_is_bullish=True)).direction==-premium_discount_vote(bar,BiasConfig(discount_is_bullish=False)).direction
def test_missing_ohlc_raises():
    try: BiasEngine().current_bias(uptrend().drop(columns=["High"])); assert False
    except ValueError: pass


def test_premium_discount_regime_aware():
    from bias_engine.factors import premium_discount_vote
    cfg=BiasConfig()
    trend_bar={"pdz_zone":"discount","pdz_zone_pct":100,"ADX":30.0}
    range_bar={"pdz_zone":"discount","pdz_zone_pct":100,"ADX":12.0}
    assert premium_discount_vote(trend_bar,cfg).direction==0
    assert premium_discount_vote(range_bar,cfg).direction==1
    assert premium_discount_vote(trend_bar,BiasConfig(pd_regime_aware=False)).direction==1

fns=[v for k,v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
p=0
for fn in fns:
    fn(); print("PASS ",fn.__name__); p+=1
print(f"\n{p}/{len(fns)} passed")

"""The technical agent must apply setup-appropriate criteria per regime:
trend_up -> momentum (no RSI extreme required); reversal -> strict Aziz RSI<10/>90;
neutral -> conservative. We capture the system prompt sent to the LLM and assert
the right ruleset was selected."""
import agents.agents as A
from agents.agents import technical_agent

BASE = dict(vwap=307.0, atr=0.26, orb_high=310.0, orb_low=306.0,
            support_levels=[305.0], resistance_levels=[311.0],
            rvol=2.5, rsi=8.0, ema={9: 309.0, 20: 308.5})


def _capture_system(fs):
    grabbed = {}

    def fake(model, system, user):
        grabbed["system"] = system
        grabbed["user"] = user
        return '{"vote":"flat","confidence":0.5,"rationale":"test"}'

    A._call_llm = fake
    technical_agent({"feature_snapshot": fs})
    return grabbed


def test_trend_up_uses_momentum_not_rsi_extremes():
    g = _capture_system({**BASE, "last_close": 311.0})  # above ORB high
    assert "Regime: trend_up" in g["user"]
    assert "do NOT require RSI extremes" in g["system"]
    assert "momentum" in g["system"].lower()


def test_reversal_uses_strict_aziz_criteria():
    g = _capture_system({**BASE, "last_close": 305.0})  # below ORB low
    assert "Regime: reversal" in g["user"]
    assert "RSI < 10" in g["system"]


def test_neutral_defaults_conservative():
    g = _capture_system({**BASE, "last_close": 308.0})  # inside range
    assert "Regime: neutral" in g["user"]
    assert "FLAT" in g["system"]

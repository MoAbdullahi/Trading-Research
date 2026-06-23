"""Phase 2 runner — the two-speed flow end to end for one US-equity symbol.

  Alpaca bars -> feature engine -> LangGraph (Technical + Risk) -> TradePlan
              -> deterministic Risk Gateway -> (optional) Execution

By default it runs DRY (no order). Pass execute=True only once you've confirmed
the plan and sizing look right in paper.

    python run_phase2.py                   # dry run on AAPL
    python run_phase2.py TSLA              # dry run on TSLA
    python run_phase2.py AAPL --execute    # submit paper order
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd

from core.enums import AssetClass, Bias
from core.settings import get_settings
from config.sessions import SessionProfile, profile_for
from data.alpaca_adapter import AlpacaEquityAdapter
from features.engine import compute_features
from agents.graph import ALL_AGENTS, build_graph
from risk.gateway import RiskGateway
from risk.models import AccountSnapshot, MarketContext, RiskLimits
from execution.engine import ExecutionEngine
from persistence.logging_db import AuditLog

_HWM_FILE = pathlib.Path("state_hwm.json")

_SEP = "-" * 60


def _header(title: str) -> None:
    print(f"\n{_SEP}")
    print(f"  {title}")
    print(_SEP)


def _update_high_water(equity: float) -> float:
    hwm = equity
    if _HWM_FILE.exists():
        try:
            hwm = max(equity, json.loads(_HWM_FILE.read_text()).get("hwm", equity))
        except Exception:
            pass
    _HWM_FILE.write_text(json.dumps({"hwm": hwm}))
    return hwm


def _bars_to_df(bars, profile: SessionProfile) -> pd.DataFrame:
    rows = [
        {"ts": b.ts, "open": b.open, "high": b.high, "low": b.low,
         "close": b.close, "volume": b.volume}
        for b in bars
    ]
    df = pd.DataFrame(rows).set_index("ts").sort_index()
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    # Strip pre-market / after-hours bars for session-bounded asset classes.
    # Continuous assets (crypto) are left untouched; for equity the windows
    # come from EQUITY_PROFILE.windows = [RTH 09:30-16:00 ET], so no times
    # are hard-coded here.
    if not profile.continuous:
        local = df.index.tz_convert(profile.tz)
        mask = pd.Series(False, index=df.index)
        for w in profile.windows:
            mask |= (local.time >= w.open_t) & (local.time < w.close_t)
        df = df[mask]
    return df


async def _safe(coro, default, label):
    try:
        return await coro
    except NotImplementedError:
        print(f"  [warn] adapter.{label} not wired -> using default {default!r}")
        return default


async def run_symbol(symbol: str, execute: bool = False) -> None:
    s = get_settings()
    adapter = AlpacaEquityAdapter()
    profile = profile_for(AssetClass.EQUITY)
    audit = AuditLog(s.postgres_dsn)

    print(f"\n{'=' * 60}")
    print(f"  TRADING SYSTEM  --  {symbol}  --  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"{'=' * 60}")

    # 1) account snapshot ---------------------------------------------------
    _header("1 / 5  ACCOUNT")
    acct = await adapter.get_account()
    hwm = _update_high_water(acct.equity)
    account = AccountSnapshot(
        equity=acct.equity, cash=acct.cash, buying_power=acct.buying_power,
        open_exposure_value=acct.open_positions_value, high_water_equity=hwm,
        is_pattern_day_trader=acct.is_pattern_day_trader,
        day_trade_count_5d=acct.day_trade_count_5d,
    )
    print(f"  Equity         : ${account.equity:>12,.2f}")
    print(f"  Cash           : ${account.cash:>12,.2f}")
    print(f"  Buying power   : ${account.buying_power:>12,.2f}")
    print(f"  Open exposure  : ${account.open_exposure_value:>12,.2f}")
    print(f"  High-water     : ${account.high_water_equity:>12,.2f}")
    dd = max(0.0, (account.high_water_equity - account.equity) / account.high_water_equity * 100)
    print(f"  Drawdown       : {dd:.2f}%  (lock at {s.max_account_drawdown_pct}%)")
    print(f"  PDT            : {'YES' if account.is_pattern_day_trader else 'no'}  "
          f"day-trades (5d): {account.day_trade_count_5d}")

    # 2) bars -> deterministic features ------------------------------------
    _header("2 / 5  MARKET DATA  &  FEATURES")
    end = datetime.now(timezone.utc)
    bars = await adapter.get_historical_bars(symbol, "1Min", end - timedelta(days=7), end)
    print(f"  Bars fetched   : {len(bars)}  (1-min, last 7 days, IEX feed)")
    if bars:
        print(f"  Bar range      : {bars[0].ts.strftime('%Y-%m-%d %H:%M')} -> "
              f"{bars[-1].ts.strftime('%Y-%m-%d %H:%M')} UTC")

    fs = compute_features(_bars_to_df(bars, profile), profile, symbol)
    await audit.record("feature_snapshot", symbol, fs)

    print(f"\n  Last close     : ${fs.last_close:.2f}")
    print(f"  VWAP           : ${fs.vwap:.2f}" if fs.vwap else "  VWAP           : n/a")
    vwap_pos = "ABOVE" if fs.vwap and fs.last_close > fs.vwap else "BELOW"
    print(f"  Price vs VWAP  : {vwap_pos}  (${abs(fs.last_close - fs.vwap):.2f} away)"
          if fs.vwap else "")
    rsi_label = "EXTREME oversold" if fs.rsi < 10 else "EXTREME overbought" if fs.rsi > 90 else \
                "oversold" if fs.rsi < 30 else "overbought" if fs.rsi > 70 else "neutral"
    print(f"  RSI (14)       : {fs.rsi:.1f}  ({rsi_label})")
    print(f"  ATR (14)       : {fs.atr:.3f}")
    print(f"  Rel. Volume    : {fs.rvol:.2f}x" if fs.rvol else "  Rel. Volume    : n/a")
    if fs.ema:
        ema_str = "  ".join(f"EMA{p}=${v:.2f}" for p, v in sorted(fs.ema.items()))
        print(f"  EMAs           : {ema_str}")
    if fs.orb_high:
        print(f"  ORB            : H=${fs.orb_high:.2f}  L=${fs.orb_low:.2f}")
    if fs.support_levels:
        print(f"  Support        : {[f'${v:.2f}' for v in fs.support_levels]}")
    if fs.resistance_levels:
        print(f"  Resistance     : {[f'${v:.2f}' for v in fs.resistance_levels]}")

    # 3) slow loop: LangGraph (lean: technical + risk) ----------------------
    _header("3 / 5  AI AGENTS  (LangGraph  -  Technical + Macro + Sentiment + Risk)")
    print(f"  Models         : fast={s.fast_model}  reasoning={s.reasoning_model}")
    print(f"  Consensus      : majority of directional votes, floor 2\n")

    graph = build_graph(enabled_agents=ALL_AGENTS)
    state_in = {
        "symbol": symbol,
        "asset_class": AssetClass.EQUITY.value,
        "feature_snapshot": dataclasses.asdict(fs),
        "macro_context": {},
        "news_items": [],
        "account_snapshot": {"equity": account.equity, "buying_power": account.buying_power},
        "consensus_threshold": 3,  # 3 of 5 (4 agents + structural)
    }
    result = graph.invoke(state_in, config={"configurable": {"thread_id": symbol}})
    plan = result["trade_plan"]
    signals = result.get("signals", [])

    for sig in signals:
        icon = {"long": "^", "short": "v", "flat": "-", "abstain": "?"}.get(sig.vote.value, "?")
        print(f"  [{sig.agent_name:<14}]  {icon} {sig.vote.value.upper():<7}  "
              f"conf={sig.confidence:.0%}  {sig.rationale}")

    # structural vote
    close, vwap = fs.last_close, fs.vwap
    struct_vote = "LONG" if vwap and close > vwap else "SHORT" if vwap and close < vwap else "FLAT"
    icon = "^" if struct_vote == "LONG" else "v" if struct_vote == "SHORT" else "-"
    print(f"  [structural    ]  {icon} {struct_vote:<7}  conf=n/a  "
          f"price {'above' if struct_vote == 'LONG' else 'below'} VWAP")

    # regime + filter status
    regime = result.get("regime", "neutral")
    filter_fired = result.get("structural_filter_applied", False)
    regime_labels = {"trend_up": "TREND-UP (VWAP hard filter ON)",
                     "reversal": "REVERSAL (structural advisory)",
                     "neutral":  "NEUTRAL  (structural advisory)"}
    print(f"\n  Regime         : {regime_labels.get(regime, regime)}")
    if filter_fired:
        print(f"  *** VWAP filter vetoed counter-trend trade ***")

    await audit.record("trade_plan", symbol, plan)

    print(f"\n  Consensus score: {plan.consensus_score} / {len([s for s in signals if s.vote.value != 'abstain']) + 1}")
    print(f"  BIAS           : {plan.bias.value.upper()}")
    if plan.key_levels:
        kl = plan.key_levels
        print(f"  Entry          : ${kl.entry:.2f}")
        print(f"  Stop           : ${kl.stop:.2f}")
        print(f"  Targets        : {[f'${t:.2f}' for t in kl.targets]}")

    if plan.bias is Bias.FLAT:
        print(f"\n  Result: FLAT - no trade signal")
        return

    # 4) deterministic risk gateway ----------------------------------------
    _header("4 / 5  RISK GATEWAY")
    gateway = RiskGateway(RiskLimits(
        max_per_trade_risk_pct=s.max_per_trade_risk_pct,
        min_reward_to_risk=s.min_reward_to_risk,
        max_concurrent_exposure_pct=s.max_concurrent_exposure_pct,
        max_account_drawdown_pct=s.max_account_drawdown_pct,
    ))
    market = MarketContext(
        symbol=symbol, asset_class=AssetClass.EQUITY, last_price=fs.last_close,
        is_shortable=await _safe(adapter.is_shortable(symbol), False, "is_shortable"),
        ssr_active=await _safe(adapter.is_ssr_active(symbol), False, "is_ssr_active"),
        session_open=await _safe(adapter.session_is_open(symbol, end), True, "session_is_open"),
    )
    decision = gateway.evaluate(plan, account, market)
    await audit.record("risk_decision", symbol, decision)

    for c in decision.checks:
        mark = "PASS" if c.passed else "FAIL"
        detail = f"  {c.detail}" if c.detail else ""
        print(f"  [{mark}]  {c.name}{detail}")

    if not decision.approved:
        ff = decision.first_failure
        print(f"\n  Result: REJECTED — {ff.reason.value if ff else 'unknown'}")
        return

    so = decision.sized_order
    print(f"\n  Result: APPROVED")
    print(f"  Qty            : {so.qty}")
    print(f"  Dollar risk    : ${so.dollar_risk:.2f}")
    print(f"  Reward / Risk  : {so.reward_to_risk:.2f}x")

    # 5) execution (guarded) -----------------------------------------------
    _header("5 / 5  EXECUTION")
    if execute:
        execution = ExecutionEngine(adapter)
        res = await execution.open_from_plan(so)
        await audit.record("order_submit", symbol, {"accepted": res.accepted, "msg": res.message})
        status = "ACCEPTED" if res.accepted else "REJECTED"
        print(f"  Order {status}  {res.message}")
    else:
        print(f"  DRY RUN — order not submitted")
        print(f"  Re-run with --execute to place the paper bracket:")
        print(f"    .\\venv\\Scripts\\python.exe run_phase2.py {symbol} --execute")

    print(f"\n{'=' * 60}\n")


def _parse_argv() -> tuple[str, bool]:
    args = [a for a in sys.argv[1:]]
    execute = "--execute" in args
    symbol = next((a for a in args if not a.startswith("--")), "AAPL")
    return symbol.upper(), execute


if __name__ == "__main__":
    sym, ex = _parse_argv()
    asyncio.run(run_symbol(sym, execute=ex))

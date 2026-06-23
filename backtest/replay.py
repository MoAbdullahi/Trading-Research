"""Walk-forward replay harness.

For each closed bar t, it builds the feature snapshot from bars[0..t] ONLY (no
look-ahead), gets agent signals from the chosen provider, runs the REAL
orchestrator_node and RiskGateway, and on an approved plan hands the SizedOrder
to the FillSimulator against bars[t+1..session_end]. One position per symbol at a
time (Aziz-style), no overnight holds.

This deliberately reuses production code (compute_features, orchestrator_node,
RiskGateway) so a passing backtest reflects the system that will actually trade.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field

import pandas as pd

from config.sessions import profile_for
from core.enums import AssetClass, Bias, Side
from core.schemas import Bar
from features.engine import compute_features
from agents.orchestrator import orchestrator_node
from risk.gateway import RiskGateway
from risk.models import AccountSnapshot, MarketContext, RiskLimits
from backtest.fills import FillSimulator, TradeResult


@dataclass
class ReplayConfig:
    asset_class: AssetClass = AssetClass.EQUITY
    starting_equity: float = 100_000.0
    warmup_bars: int = 30           # 30 bars (~30 min) is enough for RSI/ATR/EMA9/20/VWAP
    min_bars_between_trades: int = 5
    consensus_threshold: int = 2
    exit_mode: str = "breakeven"       # "breakeven" | "full_target" | "atr_trail"
    target_mode: str = "structural"    # "structural" | "r_multiple"
    max_hold_bars: int | None = None   # continuous assets: force-close after N bars; None = session-end
    feature_window_bars: int = 500    # rolling window cap for compute_features (prevents O(n²) on long datasets)


@dataclass
class ReplayReport:
    symbol: str
    trades: list[TradeResult] = field(default_factory=list)

    # --- metrics (R-multiples; sizing-independent) ---
    def summary(self) -> dict:
        n = len(self.trades)
        if n == 0:
            return {"trades": 0}
        rs = [t.realized_r for t in self.trades]
        wins = [r for r in rs if r > 0]
        losses = [r for r in rs if r <= 0]
        gross_win = sum(wins)
        gross_loss = -sum(losses)
        # max drawdown of the cumulative-R equity curve
        cum, peak, mdd = 0.0, 0.0, 0.0
        for r in rs:
            cum += r
            peak = max(peak, cum)
            mdd = min(mdd, cum - peak)
        # MFE / target-reach analysis
        mfes = [t.mfe_r for t in self.trades]
        avg_mfe = sum(mfes) / n
        # pct_reach_target: trades whose MFE >= their T1 (regardless of exit reason)
        reach_target = sum(1 for t in self.trades if t.target_r > 0 and t.mfe_r >= t.target_r)
        pct_reach_target = reach_target / n
        # avg win and avg loss for payoff analysis
        avg_win = gross_win / len(wins) if wins else 0.0
        avg_loss = -gross_loss / len(losses) if losses else 0.0

        return {
            "trades": n,
            "win_rate": round(len(wins) / n, 3),
            "total_R": round(sum(rs), 2),
            "avg_R": round(sum(rs) / n, 3),
            "avg_win_R": round(avg_win, 3),
            "avg_loss_R": round(-avg_loss, 3),
            "best_R": round(max(rs), 2),
            "worst_R": round(min(rs), 2),
            "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else float("inf"),
            "max_drawdown_R": round(mdd, 2),
            "mfe": {
                "avg_mfe_r": round(avg_mfe, 3),
                "pct_reach_target": round(pct_reach_target, 3),
                "pct_mfe_above_1r": round(sum(1 for m in mfes if m >= 1.0) / n, 3),
                "pct_mfe_above_2r": round(sum(1 for m in mfes if m >= 2.0) / n, 3),
            },
            "by_regime": self._by_regime(),
        }

    def _by_regime(self) -> dict:
        out: dict[str, dict] = {}
        for t in self.trades:
            b = out.setdefault(t.regime, {"trades": 0, "total_R": 0.0})
            b["trades"] += 1
            b["total_R"] = round(b["total_R"] + t.realized_r, 2)
        return out


def _session_end_ts(day_bars: pd.DataFrame, profile) -> object:
    """Last bar timestamp of the trading session (force-close anchor)."""
    return day_bars.index[-1]


def run_replay(
    symbol: str,
    df: pd.DataFrame,
    provider,
    config: ReplayConfig | None = None,
    risk_limits: RiskLimits | None = None,
) -> ReplayReport:
    """`df`: tz-aware UTC index, ascending, closed bars only.
    `provider`: object exposing get_signals(fs, window, asset_class) -> list[AgentSignal].
    `risk_limits`: optional override (e.g. lower min_reward_to_risk for structural gold targets)."""
    cfg = config or ReplayConfig()
    profile = profile_for(cfg.asset_class)
    report = ReplayReport(symbol=symbol)
    gateway = RiskGateway(risk_limits or RiskLimits())
    fills = FillSimulator(exit_mode=cfg.exit_mode, target_mode=cfg.target_mode)

    # Continuous assets (gold, crypto): treat entire DataFrame as one session so
    # positions are not force-closed at arbitrary UTC-date boundaries; max_hold_bars
    # controls duration instead.  Session-based assets still group by trading day.
    if profile.continuous:
        day_iter = [(None, df)]
    else:
        day_iter = list(df.groupby(df.index.tz_convert(profile.tz).date))

    for _, day in day_iter:
        last_trade_i = -10_000  # reset each day — cross-day index comparison is meaningless
        end_ts = _session_end_ts(day, profile)
        bars_list = [
            Bar(symbol=symbol, asset_class=cfg.asset_class, ts=ts, open=r.open,
                high=r.high, low=r.low, close=r.close, volume=r.volume)
            for ts, r in zip(day.index, day.itertuples())
        ]
        in_trade_until = -1  # index until which we hold (one position at a time)

        for i in range(cfg.warmup_bars, len(day) - 1):
            if i <= in_trade_until or (i - last_trade_i) < cfg.min_bars_between_trades:
                continue

            # Cap the feature window at FEATURE_WINDOW_BARS.  ATR/EMA/VWAP/S&R are all
            # stable well within 500 bars; the CRT provider gets ~31 H4 candles which is
            # sufficient.  Without this cap, compute_features is O(i) per bar → O(n²) total
            # across a multi-year dataset, making a 4-year run take 15+ hours.
            window = day.iloc[max(0, i + 1 - cfg.feature_window_bars) : i + 1]
            fs = compute_features(window, profile, symbol)
            fs_dict = dataclasses.asdict(fs)

            signals = provider.get_signals(fs_dict, window=window, asset_class=cfg.asset_class.value)

            orch_out = orchestrator_node({
                "symbol": symbol, "asset_class": cfg.asset_class.value,
                "feature_snapshot": fs_dict, "signals": signals,
                "consensus_threshold": cfg.consensus_threshold,
            })
            plan = orch_out["trade_plan"]
            if plan.bias is Bias.FLAT:
                continue

            account = AccountSnapshot(
                equity=cfg.starting_equity, cash=cfg.starting_equity,
                buying_power=cfg.starting_equity * 4, high_water_equity=cfg.starting_equity,
            )
            market = MarketContext(
                symbol=symbol, asset_class=cfg.asset_class, last_price=fs.last_close,
                is_shortable=True, ssr_active=False, session_open=True,
                atr=fs.atr or 0.0,
            )
            decision = gateway.evaluate(plan, account, market)
            if not decision.approved or decision.sized_order is None:
                continue

            future = bars_list[i + 1:]
            if profile.continuous and cfg.max_hold_bars is not None:
                hold_end_i = min(i + cfg.max_hold_bars, len(bars_list) - 1)
                close_ts = bars_list[hold_end_i].ts
            else:
                close_ts = end_ts
            trade = fills.simulate(decision.sized_order, future, close_ts, atr=fs.atr or 0.0)
            if trade is None:
                continue
            trade.regime = orch_out.get("regime", "")
            report.trades.append(trade)
            last_trade_i = i
            # block re-entry until this trade's last exit bar
            exit_ts = trade.exits[-1].ts if trade.exits else end_ts
            in_trade_until = next((j for j, b in enumerate(bars_list) if b.ts >= exit_ts), len(day))

    return report

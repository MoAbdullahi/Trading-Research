"""Layer 4 — the deterministic Risk Gateway interceptor.

Sits between the LangGraph slow loop and the broker. Every TradePlan passes
through `evaluate()`, which runs each immutable rule in order and returns a
RiskDecision. If ANY check fails, the plan is rejected and no order is built.
Position size is computed HERE (not by the LLM) from the 2%-risk rule.

Pure functions, fully unit-testable, zero side effects.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import floor

from core.enums import AssetClass, Bias, RejectReason, Side
from core.schemas import TradePlan
from risk.models import (
    AccountSnapshot,
    MarketContext,
    RiskCheck,
    RiskDecision,
    RiskLimits,
    SizedOrder,
    VolatilityCircuitBreaker,
)


class RiskGateway:
    def __init__(self, limits: RiskLimits) -> None:
        self.limits = limits
        self._circuit_breaker = VolatilityCircuitBreaker()

    # --------------------------------------------------------------------- #
    def evaluate(
        self, plan: TradePlan, account: AccountSnapshot, market: MarketContext
    ) -> RiskDecision:
        checks: list[RiskCheck] = []
        now = datetime.now(timezone.utc)

        # 0. FLAT plans are trivially "approved" with no order.
        if plan.bias is Bias.FLAT or plan.key_levels is None:
            if not plan.volatility_alert:
                self._circuit_breaker.record_no_alert()
            return RiskDecision(plan_id=plan.plan_id, symbol=plan.symbol,
                                approved=True, checks=[], sized_order=None, decided_at=now)

        # 0b. Volatility circuit breaker — update state and check freeze.
        volatility_alert = getattr(plan, "volatility_alert", False)
        if volatility_alert:
            self._circuit_breaker.record_alert(self.limits, now)
        else:
            self._circuit_breaker.record_no_alert()

        if self._circuit_breaker.is_frozen(now):
            freeze_check = RiskCheck(
                name="volatility_circuit_breaker",
                passed=False,
                reason=RejectReason.VOLATILITY_FREEZE,
                detail=(
                    f"{self.limits.volatility_circuit_breaker_count} consecutive volatility alerts; "
                    f"frozen until {self._circuit_breaker.freeze_until}"
                ),
            )
            return RiskDecision(
                plan_id=plan.plan_id, symbol=plan.symbol,
                approved=False, checks=[freeze_check], sized_order=None, decided_at=now,
            )

        side = Side.LONG if plan.bias is Bias.LONG else Side.SHORT
        kl = plan.key_levels

        # 1. Structural sanity of the plan.
        ok_struct = self._valid_geometry(side, kl.entry, kl.stop, kl.targets[0])
        checks.append(RiskCheck(name="plan_geometry", passed=ok_struct,
                                reason=RejectReason.OK if ok_struct else RejectReason.MALFORMED_PLAN,
                                detail="stop/target must sit on correct side of entry"))

        # 2. Stop-distance floor — must be checked *before* sizing to prevent
        #    tiny-denominator position explosions (qty = budget / near-zero risk_ps).
        #    ATR-primary: self-adapting across assets, admits tight structural SMC stops
        #    (~0.2–0.5 ATR), still rejects accidental near-zero stops.
        #    Pct-fallback: used when ATR is not threaded (legacy equity path).
        #    Volatility override: widen the ATR floor by the configured scale factor.
        risk_ps = abs(kl.entry - kl.stop)
        atr_mult = self.limits.min_stop_atr_mult * (
            self.limits.volatility_stop_atr_mult_scale if volatility_alert else 1.0
        )
        if market.atr > 0:
            min_stop = atr_mult * market.atr
            stop_tight = risk_ps < min_stop
            vol_tag = " [VOL-WIDENED]" if volatility_alert else ""
            detail = (f"stop dist {risk_ps:.4f} "
                      f"(min {min_stop:.4f} = {atr_mult:.3f}x ATR {market.atr:.4f}){vol_tag}")
        else:
            stop_dist_pct = risk_ps / kl.entry if kl.entry > 0 else 0.0
            stop_tight = stop_dist_pct < self.limits.min_stop_distance_pct
            detail = (f"stop dist {stop_dist_pct * 100:.2f}% "
                      f"(min {self.limits.min_stop_distance_pct * 100:.2f}%)")
        checks.append(RiskCheck(
            name="stop_distance",
            passed=not stop_tight,
            reason=RejectReason.STOP_TOO_TIGHT if stop_tight else RejectReason.OK,
            detail=detail,
        ))

        # 3. Session open.
        checks.append(RiskCheck(name="session_open", passed=market.session_open,
                                reason=RejectReason.OK if market.session_open else RejectReason.SESSION_CLOSED))

        # 4. Drawdown lock.
        dd_pct = max(0.0, (account.high_water_equity - account.equity) / account.high_water_equity * 100.0)
        dd_ok = dd_pct < self.limits.max_account_drawdown_pct
        checks.append(RiskCheck(name="drawdown_lock", passed=dd_ok,
                                reason=RejectReason.OK if dd_ok else RejectReason.DRAWDOWN_LOCK,
                                detail=f"daily drawdown {dd_pct:.2f}%"))

        # 4. Reward-to-risk (re-checked deterministically, ignoring the LLM's claim).
        rr = kl.reward_to_risk(side is Side.LONG)
        rr_ok = rr >= self.limits.min_reward_to_risk
        checks.append(RiskCheck(name="reward_to_risk", passed=rr_ok,
                                reason=RejectReason.OK if rr_ok else RejectReason.RR_TOO_LOW,
                                detail=f"RR={rr:.2f} (min {self.limits.min_reward_to_risk})"))

        # 5. Short-capability + SSR (asset-class compliance).
        short_ok, short_reason = self._short_compliance(side, market)
        checks.append(RiskCheck(name="short_compliance", passed=short_ok, reason=short_reason))

        # 6. Pattern Day Trader (US equities, sub-$25k).
        pdt_ok, pdt_reason = self._pdt_check(account, market)
        checks.append(RiskCheck(name="pdt", passed=pdt_ok, reason=pdt_reason))

        # ---- size to the MOST BINDING constraint (risk is a ceiling, not a target) ----
        unit_price = kl.entry * market.contract_multiplier
        risk_per_unit = abs(kl.entry - kl.stop) * market.contract_multiplier

        # Volatility alert: enforce 50% position sizing reduction
        effective_risk_pct = min(plan.max_risk_pct, self.limits.max_per_trade_risk_pct)
        if volatility_alert:
            effective_risk_pct *= self.limits.volatility_size_reduction

        max_dollar_risk = account.equity * (effective_risk_pct / 100.0)
        exposure_budget = (
            (self.limits.max_concurrent_exposure_pct / 100.0) * account.equity
            - account.open_exposure_value
        )

        qty_by_risk = floor(max_dollar_risk / risk_per_unit) if risk_per_unit > 0 else 0
        qty_by_exposure = floor(exposure_budget / unit_price) if unit_price > 0 else 0
        qty_by_bp = floor(account.buying_power / unit_price) if unit_price > 0 else 0
        qty = max(0, min(qty_by_risk, qty_by_exposure, qty_by_bp))

        # 7. Per-trade risk cap (the 2% rule). Sizing guarantees <=cap when qty>0;
        #    fails only if a single unit already exceeds the risk budget.
        risk_pct = (qty * risk_per_unit) / account.equity * 100.0 if qty > 0 else 0.0
        checks.append(RiskCheck(name="per_trade_risk", passed=qty_by_risk > 0,
                                reason=RejectReason.OK if qty_by_risk > 0 else RejectReason.RISK_TOO_HIGH,
                                detail=f"sized qty={qty} (risk-cap qty={qty_by_risk}), risk={risk_pct:.2f}%"))

        # 8. Buying power.
        notional = qty * unit_price
        checks.append(RiskCheck(name="buying_power", passed=qty_by_bp > 0,
                                reason=RejectReason.OK if qty_by_bp > 0 else RejectReason.MARGIN_INSUFFICIENT,
                                detail=f"notional={notional:.2f} bp={account.buying_power:.2f} (bp qty={qty_by_bp})"))

        # 9. Concurrent exposure cap.
        proj_exposure_pct = (account.open_exposure_value + notional) / account.equity * 100.0
        checks.append(RiskCheck(name="concurrent_exposure", passed=qty_by_exposure > 0,
                                reason=RejectReason.OK if qty_by_exposure > 0 else RejectReason.EXPOSURE_CAP,
                                detail=f"projected {proj_exposure_pct:.1f}% (exposure-cap qty={qty_by_exposure})"))

        approved = all(c.passed for c in checks)
        sized = None
        if approved:
            sized = SizedOrder(
                symbol=plan.symbol, side=side, qty=qty, entry_price=kl.entry,
                stop_price=kl.stop, take_profit_prices=kl.targets,
                dollar_risk=round(qty * risk_per_unit, 2), reward_to_risk=round(rr, 2),
            )

        return RiskDecision(plan_id=plan.plan_id, symbol=plan.symbol, approved=approved,
                            checks=checks, sized_order=sized, decided_at=now)

    # --------------------------------------------------------------------- #
    @staticmethod
    def _valid_geometry(side: Side, entry: float, stop: float, target: float) -> bool:
        if side is Side.LONG:
            return stop < entry < target
        return target < entry < stop

    @staticmethod
    def _short_compliance(side: Side, market: MarketContext) -> tuple[bool, RejectReason]:
        if side is not Side.SHORT:
            return True, RejectReason.OK
        if market.asset_class is AssetClass.CRYPTO and not market.is_shortable:
            return False, RejectReason.NO_SHORT_SPOT
        if not market.is_shortable:
            return False, RejectReason.NO_SHORT_SPOT
        if market.asset_class is AssetClass.EQUITY and market.ssr_active:
            # SSR doesn't ban shorting outright, but bans shorting on a downtick;
            # conservative gateway blocks market shorts while SSR is active.
            return False, RejectReason.SSR_BLOCK
        return True, RejectReason.OK

    def _pdt_check(self, account: AccountSnapshot, market: MarketContext) -> tuple[bool, RejectReason]:
        if market.asset_class is not AssetClass.EQUITY:
            return True, RejectReason.OK
        if account.equity >= self.limits.pdt_min_equity:
            return True, RejectReason.OK
        if account.day_trade_count_5d >= self.limits.pdt_max_day_trades:
            return False, RejectReason.PDT_BLOCK
        return True, RejectReason.OK

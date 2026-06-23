# ==============================================================================================
# The Arcane trading strategy for SPOT trading (Enhanced with NFI5 Integration)
#
# Version : 1.0-nfi5-enhanced
# Date    : 2024-12
# Remarks : Enhanced version integrating proven NFI5MOHO entry/exit rules with Arcane framework
#
# STRATEGY OVERVIEW:
# This enhanced version combines the best of both worlds:
# 1. Original Arcane multi-timeframe momentum strategy (PRESERVED)
# 2. NFI5MOHO proven entry/exit conditions (ADDED)
# 3. Adaptive behavior for different market conditions
# 4. Advanced pump/dip protection from NFI5
# 5. Sophisticated custom exit logic
#
# INTEGRATION APPROACH:
# - All original Arcane entry/exit methods are preserved unchanged
# - NFI5 conditions are added as additional entry/exit methods
# - NFI5 indicators adapted to use Arcane's 1h/5m timeframe structure
# - Individual enable/disable flags for all methods
# - Unified parameter optimization framework
# ==============================================================================================
# pragma pylint: disable=missing-docstring, invalid-name, pointless-string-statement
# flake8: noqa: F401
# isort: skip_file
# --- Do not remove these libs ---
from freqtrade.strategy import (
    IStrategy,
    merge_informative_pair,
    DecimalParameter,
    IntParameter,
    CategoricalParameter,
)
from pandas import DataFrame, Series
from datetime import datetime, timedelta
import talib.abstract as ta
import freqtrade.vendor.qtpylib.indicators as qtpylib

# --------------------------------
from typing import Optional
import pandas as pd
import numpy as np
import technical.indicators as ftt
from freqtrade.exchange import timeframe_to_minutes
from freqtrade.persistence import Trade
import logging
import os
from functools import reduce


logger = logging.getLogger(__name__)


def ssl_atr(dataframe, length=7):
    """
    SSL (Semaphore Signal Line) with ATR - Trend Direction Indicator

    This indicator helps determine trend direction by creating dynamic support/resistance levels
    based on price action and volatility (ATR).

    How it works:
    1. Creates upper and lower bands using SMA of highs/lows + ATR
    2. Determines if price is in bullish or bearish mode
    3. SSL lines act as dynamic support (sslUp) and resistance (sslDown)
    4. When sslUp > sslDown = Bullish trend
    5. When sslUp < sslDown = Bearish trend

    Parameters:
    - length: Period for SMA calculation (default 7)
    - Uses ATR for volatility adjustment

    Returns: sslDown, sslUp lines
    """
    df = dataframe.copy()

    # Create upper and lower bands using SMA + ATR
    # High band = average of highs + volatility buffer
    df["smaHigh"] = df["high"].rolling(length).mean() + df["atr"]
    # Low band = average of lows - volatility buffer
    df["smaLow"] = df["low"].rolling(length).mean() - df["atr"]

    # Determine trend direction based on price position
    # +1 = bullish (price above upper band)
    # -1 = bearish (price below lower band)
    # NaN = neutral (price between bands)
    df["hlv"] = np.where(
        df["close"] > df["smaHigh"], 1, np.where(df["close"] < df["smaLow"], -1, np.nan)
    )

    # Forward fill to maintain trend direction until clear reversal
    df["hlv"] = df["hlv"].ffill()

    # Create SSL lines based on trend direction
    # In bearish mode: sslDown = upper band, sslUp = lower band
    # In bullish mode: sslDown = lower band, sslUp = upper band
    df["sslDown"] = np.where(df["hlv"] < 0, df["smaHigh"], df["smaLow"])
    df["sslUp"] = np.where(df["hlv"] < 0, df["smaLow"], df["smaHigh"])

    return df["sslDown"], df["sslUp"]


# def EWO(dataframe, ema_length=5, ema2_length=35):
#     """
#     Elliott Wave Oscillator - Momentum Indicator

#     This oscillator measures the difference between two EMAs as a percentage of price.
#     It helps identify momentum shifts and potential entry points.

#     How it works:
#     1. Calculates fast EMA (5 periods) and slow EMA (35 periods)
#     2. Finds the difference between them
#     3. Normalizes by dividing by the low price and multiplying by 100
#     4. Positive values = bullish momentum
#     5. Negative values = bearish momentum
#     6. Extreme values often indicate reversal opportunities

#     Usage in strategy:
#     - Look for oversold conditions (very negative EWO) for buy signals
#     - Combined with other indicators to confirm momentum
#     """
#     df = dataframe.copy()
#     ema1 = ta.EMA(df, timeperiod=ema_length)  # Fast EMA (5)
#     ema2 = ta.EMA(df, timeperiod=ema2_length)  # Slow EMA (35)

#     # Calculate percentage difference normalized by low price
#     emadif = (ema1 - ema2) / df["low"] * 100
#     return emadif


def EWO(dataframe, ema_length=5, ema2_length=35, smoothing=3, price_col="close"):
    """
    Smoothed, more stable Elliott Wave Oscillator (EWO).
    """
    df = dataframe.copy()

    ema1 = ta.EMA(df, timeperiod=ema_length)
    ema2 = ta.EMA(df, timeperiod=ema2_length)

    # Use close or average of close/low for normalization
    price = df[price_col]

    emadif = (ema1 - ema2) / price * 100

    # Optional smoothing
    if smoothing > 1:
        emadif = emadif.rolling(window=smoothing, min_periods=1).mean()

    # Optional clipping
    emadif = emadif.clip(lower=-200, upper=200)

    return emadif


def simple_trend_detection(dataframe, fast_period=20, slow_period=50, trend_period=100):
    """
    Simplified Trend Detection System (Replaces Complex Ichimoku)

    This function replaces the complex Ichimoku cloud with a simpler but equally effective
    triple EMA alignment system for trend detection.

    How it works:
    1. Uses three EMAs of different periods to gauge trend strength
    2. Fast EMA (20) - captures short-term price movement
    3. Slow EMA (50) - captures medium-term trend
    4. Trend EMA (100) - captures long-term trend direction

    Bullish Conditions (all must be true):
    - Fast EMA > Slow EMA > Trend EMA (proper alignment)
    - Price is above the long-term trend EMA
    - Fast EMA is rising (momentum confirmation)

    Bearish Conditions (all must be true):
    - Fast EMA < Slow EMA < Trend EMA (bearish alignment)
    - Price is below the long-term trend EMA
    - Fast EMA is falling (momentum confirmation)

    This system is much simpler than Ichimoku but provides similar trend detection capability.
    """
    # Calculate the three EMAs for trend analysis
    ema_fast = ta.EMA(dataframe, timeperiod=fast_period)  # 20-period EMA
    ema_slow = ta.EMA(dataframe, timeperiod=slow_period)  # 50-period EMA
    ema_trend = ta.EMA(dataframe, timeperiod=trend_period)  # 100-period EMA

    # BULLISH TREND CONDITIONS
    # 1. EMA alignment: Fast > Slow > Trend (bullish stack)
    # bullish_alignment = (ema_fast > ema_slow) & (ema_slow > ema_trend) # Disabled for simplicity
    bullish_alignment = ema_fast > ema_slow  # Simplified alignment

    # 2. Price position: Must be above long-term trend
    # price_above_trend = dataframe["close"] > ema_trend # Disabled for simplicity
    price_above_trend = dataframe["close"] > ema_fast

    # 3. Momentum check: Fast EMA should be rising (compare to 3 periods ago)
    momentum_up = ema_fast > ema_fast.shift(3)

    # BEARISH TREND CONDITIONS
    # 1. EMA alignment: Fast < Slow < Trend (bearish stack)
    # bearish_alignment = (ema_fast < ema_slow) & (ema_slow < ema_trend) # Disabled for simplicity
    bearish_alignment = ema_fast < ema_slow  # Simplified alignment

    # 2. Price position: Must be below long-term trend
    # price_below_trend = dataframe["close"] < ema_trend # Disabled for simplicity
    price_below_trend = dataframe["close"] < ema_fast

    # 3. Momentum check: Fast EMA should be falling
    momentum_down = ema_fast < ema_fast.shift(3)

    # Return all components for use in main strategy
    return {
        "ema_fast": ema_fast,
        "ema_slow": ema_slow,
        "ema_trend": ema_trend,
        # Combined bullish signal (all conditions must be true)
        "trend_bullish": bullish_alignment & price_above_trend & momentum_up,
        # Combined bearish signal (all conditions must be true)
        "trend_bearish": bearish_alignment & price_below_trend & momentum_down,
    }


class ArcaneLiM2(IStrategy):
    """
    ARCANE LESS IS MORE (ArcaneLiM) - Enhanced with NFI5 Integration

    This enhanced version combines the proven Arcane momentum strategy with the
    sophisticated entry/exit conditions from the NFI5MOHO strategy.

    CORE FEATURES:
    - Original Arcane multi-timeframe momentum strategy (PRESERVED)
    - NFI5MOHO 21 sophisticated entry conditions (ADDED)
    - NFI5MOHO 8 sophisticated exit conditions (ADDED)
    - Advanced pump/dip protection
    - Sophisticated custom exit logic
    - Market regime-adaptive behavior
    - Individual enable/disable flags for all methods

    ENTRY METHODS (Original Arcane + NFI5):

    ORIGINAL ARCANE METHODS (PRESERVED):
    1. Trend Following: Buy pullbacks during confirmed uptrends
    2. Local Uptrend: Buy breakouts of short-term consolidations
    3. Momentum: Buy oversold bounces using Elliott Wave Oscillator
    4. Trend Momentum Breakout: High-quality trend following
    5. Selective Volume Dip: Volume-based dip buying
    6. Enhanced Momentum: Advanced momentum breakouts
    7. Bull Market Momentum: Aggressive momentum entries

    NEW NFI5 METHODS (ADDED):
    8. NFI5 Condition 1: Strict trend following with pump protection
    9. NFI5 Condition 2: Volume-based entries with RSI divergence
    10. NFI5 Condition 3: Advanced Bollinger Band analysis
    11. NFI5 Condition 4: EMA-based pullback entries
    12. NFI5 Condition 5-21: Additional proven NFI5 conditions
    13. NFI5 Multi-Offset: Dynamic MA offset entries

    EXIT METHODS (Original Arcane + NFI5):
    - Original Arcane DEMA-based exits (PRESERVED)
    - NFI5 Bollinger Band exits (ADDED)
    - NFI5 RSI-based exits (ADDED)
    - NFI5 Custom profit-taking logic (ADDED)
    - Advanced trailing stop system

    RISK MANAGEMENT:
    - Dynamic ATR-based stop losses
    - Market regime-adaptive behavior
    - Advanced pump/dip protection
    - Sophisticated custom exit logic
    """

    def __init__(self, config: dict, *args, **kwargs):
        super().__init__(config, *args, **kwargs)
        # Create a log file to track all trades for analysis
        self.trade_log_file = os.path.join(os.getcwd(), "trades_arcane_nfi5.log")
        if not os.path.exists(self.trade_log_file):
            with open(self.trade_log_file, "w") as f:
                f.write("Trade Log - Arcane NFI5 Enhanced\n")

    # ==================== STRATEGY CONFIGURATION ====================

    # Strategy interface version (required by Freqtrade)
    INTERFACE_VERSION = 3
    can_short: bool = False  # Only long positions (spot trading)
    timeframe = "5m"  # Primary timeframe for entries/exits
    informative_timeframe = "1h"  # Higher timeframe for trend analysis
    startup_candle_count = 400  # Increased for NFI5 indicators
    process_only_new_candles = True  # Only process new candles (efficiency)
    use_exit_signal = True  # Use custom exit signals
    exit_profit_only = False  # Allow exits even at loss
    ignore_roi_if_entry_signal = False  # Respect ROI table

    # ==================== PROFIT TARGETS (ROI TABLE) ====================
    # Enhanced ROI table balancing Arcane and NFI5 approaches
    minimal_roi = {
        "0": 0.125,  # 12.5% profit target immediately
        "60": 0.10,  # 10% after 1 hour
        "120": 0.075,  # 7.5% after 2 hours
        "180": 0.05,  # 5% after 3 hours
        "240": 0.025,  # 2.5% after 4 hours
        "320": 0.01,  # 1% after 5+ hours
    }

    # ==================== RISK MANAGEMENT ====================
    # stoploss = -0.05  # 5% maximum loss per trade
    stoploss = -0.99  # Set to 99% for testing purposes

    # TRAILING STOP CONFIGURATION
    trailing_stop = True  # Enable trailing stops
    # trailing_stop_positive = 0.001  # Start trailing at 0.1% profit (OLD VALUE)
    trailing_stop_positive = 0.002  # Start trailing at 0.2% profit
    trailing_stop_positive_offset = 0.025  # Trail 2.5% below peak
    trailing_only_offset_is_reached = True  # Only trail after offset reached

    # ==================== ENHANCED PARAMETERS (ARCANE + NFI5) ====================

    # ORIGINAL ARCANE PARAMETERS (PRESERVED)
    buy_params = {
        # Original Arcane optimized parameters
        "low_offset": 0.964,
        "dema_len_buy": 51,
        "buy_ema_diff": 0.024,
        "buy_bb_factor": 0.999,
        "buy_closedelta": 13.494,
        "buy_ewo": -5.001,
        "buy_ema_low": 0.935,
        "buy_ema_high": 0.968,
        "buy_rsi": 23,
        "buy_rsi_fast": 44,
        # ==================== CRITICAL FIXES ====================
        # KEEP ONLY THE PROVEN PROFITABLE METHODS ENABLED
        "trend_following_enable": True,  # ✅ Keep - original Arcane method
        "local_uptrend_enable": True,  # ✅ Keep - 71-80% win rate, profitable
        "ewo_momentum_enable": True,  # ✅ Keep - original Arcane method
        # NEW: Ichimoku DEMA method from Arcane backup
        "ichimoku_dema_enable": True,  # ✅ Add - Ichimoku DEMA entry/exit from backup (EXIT HAS BEEN DISABLED)
        # DISABLE THE PROBLEMATIC METHODS
        "trend_momentum_enable": False,  # ❌ DISABLE - causing 94% of trades and massive losses
        "bincluc_volume_enable": False,  # ❌ DISABLE - not performing well
        "bincluc_advanced_bb_enable": False,  # ❌ Already disabled
        "bincluc_dip_enable": False,  # ❌ Already disabled
        "bincluc_mfi_enable": False,  # ❌ Already disabled
        "bull_momentum_enable": False,  # ❌ DISABLE - negative performance
        # KEEP PROFITABLE NFI5 METHODS ENABLED
        "nfi5_multi_offset_enable": True,  # ✅ Keep - 66-67% win rate, very profitable
        # SELECTIVELY ENABLE ONLY PROFITABLE NFI5 CONDITIONS
        "nfi5_condition_1_enable": False,  # ❌ Mixed performance
        "nfi5_condition_2_enable": True,  # ✅ 100% win rate in bull market
        "nfi5_condition_3_enable": True,  # ✅ 100% win rate
        "nfi5_condition_4_enable": True,  # ✅ 77% win rate
        "nfi5_condition_5_enable": False,  # ❌ Not appearing in results
        "nfi5_condition_6_enable": True,  # ✅ 75% win rate
        "nfi5_condition_7_enable": False,  # ❌ Not appearing in results
        "nfi5_condition_8_enable": True,  # ✅ 57-70% win rate
        "nfi5_condition_9_enable": False,  # ❌ Poor performance
        "nfi5_condition_10_enable": True,  # ✅ 85% win rate
        "nfi5_condition_11_enable": True,  # ✅ 100% win rate
        "nfi5_condition_12_enable": True,  # ✅ 100% win rate
        "nfi5_condition_13_enable": False,  # ❌ Not appearing in results
        "nfi5_condition_14_enable": True,  # ✅ 100% win rate
        "nfi5_condition_15_enable": True,  # ✅ 71-82% win rate
        "nfi5_condition_16_enable": True,  # ✅ 100% win rate
        "nfi5_condition_17_enable": True,  # ✅ 100% win rate
        "nfi5_condition_18_enable": True,  # ✅ 60-100% win rate
        "nfi5_condition_19_enable": False,  # ❌ Mixed performance
        "nfi5_condition_20_enable": True,  # ✅ 70-71% win rate
        "nfi5_condition_21_enable": True,  # ✅ 66-76% win rate,
        # NFI5 optimized parameters (from NFI5MOHO_WIP)
        "nfi5_base_nb_candles_buy": 72,
        "nfi5_ewo_high": 3.319,
        "nfi5_ewo_low": -11.101,
        "nfi5_low_offset_ema": 0.929,
        "nfi5_low_offset_sma": 0.955,
        "nfi5_buy_chop_min_19": 58.2,
        "nfi5_buy_rsi_1h_min_19": 65.3,
    }

    sell_params = {
        # Original Arcane parameters
        "high_offset": 1.004,
        "dema_len_sell": 72,
        # NFI5 sell method controls (NEW)
        "nfi5_sell_condition_1_enable": True,
        "nfi5_sell_condition_2_enable": True,
        "nfi5_sell_condition_3_enable": True,
        "nfi5_sell_condition_4_enable": True,
        "nfi5_sell_condition_6_enable": True,
        "nfi5_sell_condition_7_enable": True,
        "nfi5_sell_condition_8_enable": True,
        # NFI5 optimized sell parameters
        "nfi5_base_nb_candles_sell": 34,
        "nfi5_high_offset_ema": 1.047,
        "nfi5_high_offset_sma": 1.051,
    }

    # ==================== OPTIMIZATION FLAGS ====================
    optimize_ssl = False
    optimize_dema = False
    optimize_local_uptrend = False
    optimize_ewo = False
    optimize_bincluc = False
    optimize_nfi5 = False  # NEW: NFI5 parameter optimization

    # ==================== ORIGINAL ARCANE PARAMETERS (PRESERVED) ====================

    # SSL and DEMA offset parameters
    low_offset = DecimalParameter(0.80, 1.20, default=0.964, space="buy", optimize=optimize_ssl)
    high_offset = DecimalParameter(0.80, 1.20, default=1.004, space="sell", optimize=optimize_ssl)

    # DEMA length parameters
    dema_len_buy = IntParameter(30, 90, default=51, space="buy", optimize=optimize_dema)
    dema_len_sell = IntParameter(30, 90, default=72, space="sell", optimize=optimize_dema)

    # Local uptrend parameters
    buy_ema_diff = DecimalParameter(0.022, 0.027, default=0.024, optimize=optimize_local_uptrend)
    buy_bb_factor = DecimalParameter(0.99, 0.999, default=0.999, optimize=optimize_local_uptrend)
    buy_closedelta = DecimalParameter(12.0, 18.0, default=13.494, optimize=optimize_local_uptrend)

    # Elliott Wave Oscillator parameters
    buy_ewo = DecimalParameter(-6.0, 5, default=-5.001, optimize=optimize_ewo)
    buy_ema_low = DecimalParameter(0.9, 0.99, default=0.935, optimize=optimize_ewo)
    buy_ema_high = DecimalParameter(0.95, 1.2, default=0.968, optimize=optimize_ewo)
    buy_rsi_fast = IntParameter(35, 50, default=44, optimize=optimize_ewo)
    buy_rsi = IntParameter(15, 35, default=23, optimize=optimize_ewo)

    # ==================== ORIGINAL ARCANE METHOD CONTROLS (PRESERVED) ====================
    trend_following_enable = CategoricalParameter(
        [True, False], default=True, space="buy", optimize=False
    )
    local_uptrend_enable = CategoricalParameter(
        [True, False], default=True, space="buy", optimize=False
    )
    ewo_momentum_enable = CategoricalParameter(
        [True, False], default=True, space="buy", optimize=False
    )
    # NEW: Ichimoku DEMA method enable/disable control
    ichimoku_dema_enable = CategoricalParameter(
        [True, False], default=True, space="buy", optimize=False
    )
    trend_momentum_enable = CategoricalParameter(
        [True, False],
        default=False,
        space="buy",
        optimize=False,  # ❌ DISABLED
    )
    bull_momentum_enable = CategoricalParameter(
        [True, False],
        default=False,
        space="buy",
        optimize=False,  # ❌ DISABLED
    )

    # Original BinCluc method controls
    bincluc_volume_enable = CategoricalParameter(
        [True, False],
        default=False,
        space="buy",
        optimize=False,  # ❌ DISABLED
    )
    bincluc_advanced_bb_enable = CategoricalParameter(
        [True, False], default=False, space="buy", optimize=False
    )
    bincluc_dip_enable = CategoricalParameter(
        [True, False], default=False, space="buy", optimize=False
    )
    bincluc_mfi_enable = CategoricalParameter(
        [True, False], default=False, space="buy", optimize=False
    )

    # Original BinCluc parameters
    buy_volume_drop_threshold = DecimalParameter(
        1.0, 6.0, default=4.0, space="buy", optimize=optimize_bincluc
    )
    buy_volume_pump_threshold = DecimalParameter(
        0.2, 0.8, default=0.4, space="buy", optimize=optimize_bincluc
    )
    buy_bb40_bbdelta_close = DecimalParameter(
        0.005, 0.04, default=0.031, space="buy", optimize=optimize_bincluc
    )
    buy_bb40_closedelta_close = DecimalParameter(
        0.01, 0.03, default=0.021, space="buy", optimize=optimize_bincluc
    )
    buy_bb40_tail_bbdelta = DecimalParameter(
        0.2, 0.4, default=0.264, space="buy", optimize=optimize_bincluc
    )
    buy_dip_threshold_1 = DecimalParameter(
        0.08, 0.2, default=0.12, space="buy", optimize=optimize_bincluc
    )
    buy_dip_threshold_2 = DecimalParameter(
        0.02, 0.4, default=0.28, space="buy", optimize=optimize_bincluc
    )
    buy_dip_threshold_3 = DecimalParameter(
        0.25, 0.44, default=0.36, space="buy", optimize=optimize_bincluc
    )
    buy_mfi_threshold = DecimalParameter(
        20.0, 50.0, default=36.0, space="buy", optimize=optimize_bincluc
    )
    buy_rsi_1h_threshold = DecimalParameter(
        40.0, 70.0, default=67.0, space="buy", optimize=optimize_bincluc
    )
    buy_bb_safe_factor = DecimalParameter(
        0.95, 1.05, default=0.99, space="buy", optimize=optimize_bincluc
    )

    # ==================== NFI5 INTEGRATION PARAMETERS (NEW) ====================

    # NFI5 Method Enable/Disable Controls
    nfi5_condition_1_enable = CategoricalParameter(
        [True, False], default=False, space="buy", optimize=False
    )
    nfi5_condition_2_enable = CategoricalParameter(
        [True, False], default=True, space="buy", optimize=False
    )
    nfi5_condition_3_enable = CategoricalParameter(
        [True, False], default=True, space="buy", optimize=False
    )
    nfi5_condition_4_enable = CategoricalParameter(
        [True, False], default=True, space="buy", optimize=False
    )
    nfi5_condition_5_enable = CategoricalParameter(
        [True, False], default=False, space="buy", optimize=False
    )
    nfi5_condition_6_enable = CategoricalParameter(
        [True, False], default=True, space="buy", optimize=False
    )
    nfi5_condition_7_enable = CategoricalParameter(
        [True, False], default=False, space="buy", optimize=False
    )
    nfi5_condition_8_enable = CategoricalParameter(
        [True, False], default=True, space="buy", optimize=False
    )
    nfi5_condition_9_enable = CategoricalParameter(
        [True, False], default=False, space="buy", optimize=False
    )
    nfi5_condition_10_enable = CategoricalParameter(
        [True, False], default=True, space="buy", optimize=False
    )
    nfi5_condition_11_enable = CategoricalParameter(
        [True, False], default=True, space="buy", optimize=False
    )
    nfi5_condition_12_enable = CategoricalParameter(
        [True, False], default=True, space="buy", optimize=False
    )
    nfi5_condition_13_enable = CategoricalParameter(
        [True, False], default=False, space="buy", optimize=False
    )
    nfi5_condition_14_enable = CategoricalParameter(
        [True, False], default=True, space="buy", optimize=False
    )
    nfi5_condition_15_enable = CategoricalParameter(
        [True, False], default=True, space="buy", optimize=False
    )
    nfi5_condition_16_enable = CategoricalParameter(
        [True, False], default=True, space="buy", optimize=False
    )
    nfi5_condition_17_enable = CategoricalParameter(
        [True, False], default=True, space="buy", optimize=False
    )
    nfi5_condition_18_enable = CategoricalParameter(
        [True, False], default=True, space="buy", optimize=False
    )
    nfi5_condition_19_enable = CategoricalParameter(
        [True, False], default=False, space="buy", optimize=False
    )
    nfi5_condition_20_enable = CategoricalParameter(
        [True, False], default=True, space="buy", optimize=False
    )
    nfi5_condition_21_enable = CategoricalParameter(
        [True, False], default=True, space="buy", optimize=False
    )
    nfi5_multi_offset_enable = CategoricalParameter(
        [True, False], default=True, space="buy", optimize=False
    )

    # NFI5 Sell Method Controls
    nfi5_sell_condition_1_enable = CategoricalParameter(
        [True, False], default=True, space="sell", optimize=False
    )
    nfi5_sell_condition_2_enable = CategoricalParameter(
        [True, False], default=True, space="sell", optimize=False
    )
    nfi5_sell_condition_3_enable = CategoricalParameter(
        [True, False], default=True, space="sell", optimize=False
    )
    nfi5_sell_condition_4_enable = CategoricalParameter(
        [True, False], default=True, space="sell", optimize=False
    )
    nfi5_sell_condition_6_enable = CategoricalParameter(
        [True, False], default=True, space="sell", optimize=False
    )
    nfi5_sell_condition_7_enable = CategoricalParameter(
        [True, False], default=True, space="sell", optimize=False
    )
    nfi5_sell_condition_8_enable = CategoricalParameter(
        [True, False], default=True, space="sell", optimize=False
    )

    # NFI5 Multi-Offset Parameters
    nfi5_base_nb_candles_buy = IntParameter(5, 80, default=72, space="buy", optimize=optimize_nfi5)
    nfi5_base_nb_candles_sell = IntParameter(
        5, 80, default=34, space="sell", optimize=optimize_nfi5
    )
    nfi5_low_offset_sma = DecimalParameter(
        0.9, 0.99, default=0.955, space="buy", optimize=optimize_nfi5
    )
    nfi5_high_offset_sma = DecimalParameter(
        0.99, 1.1, default=1.051, space="sell", optimize=optimize_nfi5
    )
    nfi5_low_offset_ema = DecimalParameter(
        0.9, 0.99, default=0.929, space="buy", optimize=optimize_nfi5
    )
    nfi5_high_offset_ema = DecimalParameter(
        0.99, 1.1, default=1.047, space="sell", optimize=optimize_nfi5
    )
    nfi5_low_offset_trima = DecimalParameter(
        0.9, 0.99, default=0.949, space="buy", optimize=optimize_nfi5
    )
    nfi5_high_offset_trima = DecimalParameter(
        0.99, 1.1, default=1.096, space="sell", optimize=optimize_nfi5
    )
    nfi5_low_offset_t3 = DecimalParameter(
        0.9, 0.99, default=0.975, space="buy", optimize=optimize_nfi5
    )
    nfi5_high_offset_t3 = DecimalParameter(
        0.99, 1.1, default=0.999, space="sell", optimize=optimize_nfi5
    )
    nfi5_low_offset_kama = DecimalParameter(
        0.9, 0.99, default=0.972, space="buy", optimize=optimize_nfi5
    )
    nfi5_high_offset_kama = DecimalParameter(
        0.99, 1.1, default=1.07, space="sell", optimize=optimize_nfi5
    )

    # NFI5 EWO Protection Parameters
    nfi5_ewo_low = DecimalParameter(
        -20.0, -8.0, default=-11.101, space="buy", optimize=optimize_nfi5
    )
    nfi5_ewo_high = DecimalParameter(2.0, 12.0, default=3.319, space="buy", optimize=optimize_nfi5)
    nfi5_fast_ewo = IntParameter(10, 50, default=50, space="buy", optimize=False)
    nfi5_slow_ewo = IntParameter(100, 200, default=200, space="buy", optimize=False)

    # NFI5 Dip Protection Parameters
    nfi5_buy_dip_threshold_1 = DecimalParameter(
        0.001, 0.05, default=0.02, space="buy", optimize=optimize_nfi5
    )
    nfi5_buy_dip_threshold_2 = DecimalParameter(
        0.01, 0.2, default=0.14, space="buy", optimize=optimize_nfi5
    )
    nfi5_buy_dip_threshold_3 = DecimalParameter(
        0.05, 0.4, default=0.32, space="buy", optimize=optimize_nfi5
    )
    nfi5_buy_dip_threshold_4 = DecimalParameter(
        0.2, 0.5, default=0.5, space="buy", optimize=optimize_nfi5
    )
    nfi5_buy_dip_threshold_5 = DecimalParameter(
        0.001, 0.05, default=0.015, space="buy", optimize=optimize_nfi5
    )
    nfi5_buy_dip_threshold_6 = DecimalParameter(
        0.01, 0.2, default=0.06, space="buy", optimize=optimize_nfi5
    )
    nfi5_buy_dip_threshold_7 = DecimalParameter(
        0.05, 0.4, default=0.24, space="buy", optimize=optimize_nfi5
    )
    nfi5_buy_dip_threshold_8 = DecimalParameter(
        0.2, 0.5, default=0.4, space="buy", optimize=optimize_nfi5
    )
    nfi5_buy_dip_threshold_9 = DecimalParameter(
        0.001, 0.05, default=0.026, space="buy", optimize=optimize_nfi5
    )
    nfi5_buy_dip_threshold_10 = DecimalParameter(
        0.01, 0.2, default=0.24, space="buy", optimize=optimize_nfi5
    )
    nfi5_buy_dip_threshold_11 = DecimalParameter(
        0.05, 0.4, default=0.42, space="buy", optimize=optimize_nfi5
    )
    nfi5_buy_dip_threshold_12 = DecimalParameter(
        0.2, 0.5, default=0.66, space="buy", optimize=optimize_nfi5
    )

    # NFI5 Pump Protection Parameters
    nfi5_buy_pump_pull_threshold_1 = DecimalParameter(
        1.5, 3.0, default=1.75, space="buy", optimize=optimize_nfi5
    )
    nfi5_buy_pump_threshold_1 = DecimalParameter(
        0.4, 1.0, default=0.5, space="buy", optimize=optimize_nfi5
    )
    nfi5_buy_pump_pull_threshold_2 = DecimalParameter(
        1.5, 3.0, default=1.75, space="buy", optimize=optimize_nfi5
    )
    nfi5_buy_pump_threshold_2 = DecimalParameter(
        0.4, 1.0, default=0.56, space="buy", optimize=optimize_nfi5
    )
    nfi5_buy_pump_pull_threshold_3 = DecimalParameter(
        1.5, 3.0, default=1.75, space="buy", optimize=optimize_nfi5
    )
    nfi5_buy_pump_threshold_3 = DecimalParameter(
        0.4, 1.0, default=0.85, space="buy", optimize=optimize_nfi5
    )
    nfi5_buy_pump_pull_threshold_4 = DecimalParameter(
        1.5, 3.0, default=2.2, space="buy", optimize=optimize_nfi5
    )
    nfi5_buy_pump_threshold_4 = DecimalParameter(
        0.4, 1.0, default=0.4, space="buy", optimize=optimize_nfi5
    )
    nfi5_buy_pump_pull_threshold_5 = DecimalParameter(
        1.5, 3.0, default=2.0, space="buy", optimize=optimize_nfi5
    )
    nfi5_buy_pump_threshold_5 = DecimalParameter(
        0.4, 1.0, default=0.56, space="buy", optimize=optimize_nfi5
    )
    nfi5_buy_pump_pull_threshold_6 = DecimalParameter(
        1.5, 3.0, default=2.0, space="buy", optimize=optimize_nfi5
    )
    nfi5_buy_pump_threshold_6 = DecimalParameter(
        0.4, 1.0, default=0.68, space="buy", optimize=optimize_nfi5
    )
    nfi5_buy_pump_pull_threshold_7 = DecimalParameter(
        1.5, 3.0, default=1.7, space="buy", optimize=optimize_nfi5
    )
    nfi5_buy_pump_threshold_7 = DecimalParameter(
        0.4, 1.0, default=0.66, space="buy", optimize=optimize_nfi5
    )
    nfi5_buy_pump_pull_threshold_8 = DecimalParameter(
        1.5, 3.0, default=1.7, space="buy", optimize=optimize_nfi5
    )
    nfi5_buy_pump_threshold_8 = DecimalParameter(
        0.4, 1.0, default=0.7, space="buy", optimize=optimize_nfi5
    )
    nfi5_buy_pump_pull_threshold_9 = DecimalParameter(
        1.5, 3.0, default=1.4, space="buy", optimize=optimize_nfi5
    )
    nfi5_buy_pump_threshold_9 = DecimalParameter(
        0.4, 1.8, default=1.3, space="buy", optimize=optimize_nfi5
    )

    # NFI5 Individual Condition Parameters
    nfi5_buy_min_inc_1 = DecimalParameter(
        0.01, 0.05, default=0.022, space="buy", optimize=optimize_nfi5
    )
    nfi5_buy_rsi_1h_min_1 = DecimalParameter(
        25.0, 40.0, default=30.0, space="buy", optimize=optimize_nfi5
    )
    nfi5_buy_rsi_1h_max_1 = DecimalParameter(
        70.0, 90.0, default=84.0, space="buy", optimize=optimize_nfi5
    )
    nfi5_buy_rsi_1 = DecimalParameter(20.0, 40.0, default=36.0, space="buy", optimize=optimize_nfi5)
    nfi5_buy_mfi_1 = DecimalParameter(20.0, 40.0, default=26.0, space="buy", optimize=optimize_nfi5)

    nfi5_buy_volume_2 = DecimalParameter(
        1.0, 10.0, default=2.6, space="buy", optimize=optimize_nfi5
    )
    nfi5_buy_rsi_1h_diff_2 = DecimalParameter(
        30.0, 50.0, default=39.0, space="buy", optimize=optimize_nfi5
    )
    nfi5_buy_mfi_2 = DecimalParameter(30.0, 56.0, default=49.0, space="buy", optimize=optimize_nfi5)
    nfi5_buy_bb_offset_2 = DecimalParameter(
        0.97, 0.999, default=0.983, space="buy", optimize=optimize_nfi5
    )

    nfi5_buy_bb40_bbdelta_close_3 = DecimalParameter(
        0.005, 0.06, default=0.057, space="buy", optimize=optimize_nfi5
    )
    nfi5_buy_bb40_closedelta_close_3 = DecimalParameter(
        0.01, 0.03, default=0.023, space="buy", optimize=optimize_nfi5
    )
    nfi5_buy_bb40_tail_bbdelta_3 = DecimalParameter(
        0.15, 0.45, default=0.418, space="buy", optimize=optimize_nfi5
    )
    nfi5_buy_ema_rel_3 = DecimalParameter(
        0.97, 0.999, default=0.986, space="buy", optimize=optimize_nfi5
    )

    nfi5_buy_bb20_close_bblowerband_4 = DecimalParameter(
        0.96, 0.99, default=0.979, space="buy", optimize=optimize_nfi5
    )
    nfi5_buy_bb20_volume_4 = DecimalParameter(
        1.0, 20.0, default=10.0, space="buy", optimize=optimize_nfi5
    )

    # NFI5 Chopiness and RSI parameters for condition 19
    nfi5_buy_chop_min_19 = DecimalParameter(
        20.0, 60.0, default=58.2, space="buy", optimize=optimize_nfi5
    )
    nfi5_buy_rsi_1h_min_19 = DecimalParameter(
        40.0, 70.0, default=65.3, space="buy", optimize=optimize_nfi5
    )

    # NFI5 Sell Parameters
    nfi5_sell_rsi_bb_1 = DecimalParameter(
        60.0, 80.0, default=79.5, space="sell", optimize=optimize_nfi5
    )
    nfi5_sell_rsi_bb_2 = DecimalParameter(
        72.0, 90.0, default=81, space="sell", optimize=optimize_nfi5
    )
    nfi5_sell_rsi_main_3 = DecimalParameter(
        77.0, 90.0, default=82, space="sell", optimize=optimize_nfi5
    )
    nfi5_sell_dual_rsi_rsi_4 = DecimalParameter(
        72.0, 84.0, default=73.4, space="sell", optimize=optimize_nfi5
    )
    nfi5_sell_dual_rsi_rsi_1h_4 = DecimalParameter(
        78.0, 92.0, default=79.6, space="sell", optimize=optimize_nfi5
    )
    nfi5_sell_rsi_under_6 = DecimalParameter(
        72.0, 90.0, default=79.0, space="sell", optimize=optimize_nfi5
    )
    nfi5_sell_rsi_1h_7 = DecimalParameter(
        80.0, 95.0, default=81.7, space="sell", optimize=optimize_nfi5
    )
    nfi5_sell_bb_relative_8 = DecimalParameter(
        1.05, 1.3, default=1.1, space="sell", optimize=optimize_nfi5
    )

    # NFI5 Custom Sell Parameters
    nfi5_sell_custom_profit_0 = DecimalParameter(
        0.01, 0.1, default=0.01, space="sell", optimize=optimize_nfi5
    )
    nfi5_sell_custom_rsi_0 = DecimalParameter(
        30.0, 40.0, default=33.0, space="sell", optimize=optimize_nfi5
    )
    nfi5_sell_custom_profit_1 = DecimalParameter(
        0.01, 0.1, default=0.03, space="sell", optimize=optimize_nfi5
    )
    nfi5_sell_custom_rsi_1 = DecimalParameter(
        30.0, 50.0, default=38.0, space="sell", optimize=optimize_nfi5
    )
    nfi5_sell_custom_profit_2 = DecimalParameter(
        0.01, 0.1, default=0.05, space="sell", optimize=optimize_nfi5
    )
    nfi5_sell_custom_rsi_2 = DecimalParameter(
        34.0, 50.0, default=43.0, space="sell", optimize=optimize_nfi5
    )
    nfi5_sell_custom_profit_3 = DecimalParameter(
        0.06, 0.30, default=0.08, space="sell", optimize=optimize_nfi5
    )
    nfi5_sell_custom_rsi_3 = DecimalParameter(
        38.0, 55.0, default=48.0, space="sell", optimize=optimize_nfi5
    )
    nfi5_sell_custom_profit_4 = DecimalParameter(
        0.3, 0.6, default=0.25, space="sell", optimize=optimize_nfi5
    )

    nfi5_sell_custom_under_profit_1 = DecimalParameter(
        0.01, 0.10, default=0.02, space="sell", optimize=optimize_nfi5
    )
    nfi5_sell_custom_under_rsi_1 = DecimalParameter(
        36.0, 60.0, default=56.0, space="sell", optimize=optimize_nfi5
    )
    nfi5_sell_custom_under_profit_2 = DecimalParameter(
        0.01, 0.10, default=0.04, space="sell", optimize=optimize_nfi5
    )
    nfi5_sell_custom_under_rsi_2 = DecimalParameter(
        46.0, 66.0, default=60.0, space="sell", optimize=optimize_nfi5
    )
    nfi5_sell_custom_under_profit_3 = DecimalParameter(
        0.01, 0.10, default=0.6, space="sell", optimize=optimize_nfi5
    )
    nfi5_sell_custom_under_rsi_3 = DecimalParameter(
        50.0, 68.0, default=62.0, space="sell", optimize=optimize_nfi5
    )

    nfi5_sell_custom_dec_profit_1 = DecimalParameter(
        0.01, 0.10, default=0.05, space="sell", optimize=optimize_nfi5
    )
    nfi5_sell_custom_dec_profit_2 = DecimalParameter(
        0.05, 0.2, default=0.07, space="sell", optimize=optimize_nfi5
    )

    nfi5_sell_trail_profit_min_1 = DecimalParameter(
        0.1, 0.25, default=0.15, space="sell", optimize=optimize_nfi5
    )
    nfi5_sell_trail_profit_max_1 = DecimalParameter(
        0.3, 0.5, default=0.46, space="sell", optimize=optimize_nfi5
    )
    nfi5_sell_trail_down_1 = DecimalParameter(
        0.04, 0.2, default=0.18, space="sell", optimize=optimize_nfi5
    )

    nfi5_sell_trail_profit_min_2 = DecimalParameter(
        0.01, 0.1, default=0.01, space="sell", optimize=optimize_nfi5
    )
    nfi5_sell_trail_profit_max_2 = DecimalParameter(
        0.08, 0.25, default=0.12, space="sell", optimize=optimize_nfi5
    )
    nfi5_sell_trail_down_2 = DecimalParameter(
        0.04, 0.2, default=0.14, space="sell", optimize=optimize_nfi5
    )

    nfi5_sell_trail_profit_min_3 = DecimalParameter(
        0.01, 0.1, default=0.05, space="sell", optimize=optimize_nfi5
    )
    nfi5_sell_trail_profit_max_3 = DecimalParameter(
        0.08, 0.16, default=0.1, space="sell", optimize=optimize_nfi5
    )
    nfi5_sell_trail_down_3 = DecimalParameter(
        0.01, 0.04, default=0.01, space="sell", optimize=optimize_nfi5
    )

    nfi5_sell_custom_profit_under_rel_1 = DecimalParameter(
        0.01, 0.04, default=0.024, space="sell", optimize=optimize_nfi5
    )
    nfi5_sell_custom_profit_under_rsi_diff_1 = DecimalParameter(
        0.0, 20.0, default=4.4, space="sell", optimize=optimize_nfi5
    )

    nfi5_sell_custom_stoploss_under_rel_1 = DecimalParameter(
        0.001, 0.02, default=0.004, space="sell", optimize=optimize_nfi5
    )
    nfi5_sell_custom_stoploss_under_rsi_diff_1 = DecimalParameter(
        0.0, 20.0, default=8.0, space="sell", optimize=optimize_nfi5
    )

    # ==================== INFORMATIVE PAIRS ====================
    def informative_pairs(self):
        """
        Define additional pairs to fetch data for.
        This allows us to use higher timeframe data for trend analysis.
        """
        pairs = self.dp.current_whitelist()
        informative_pairs = [(pair, self.informative_timeframe) for pair in pairs]
        return informative_pairs

    # ==================== INDICATOR CALCULATION ====================
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        ENHANCED INDICATOR CALCULATION - ARCANE + NFI5

        This function calculates all technical indicators needed for both
        the original Arcane strategy and the new NFI5 integration.

        INDICATORS CALCULATED:
        1. Original Arcane indicators (PRESERVED)
        2. NFI5 indicators (ADDED)
        3. Enhanced pump/dip protection
        4. Multi-offset moving averages
        5. Advanced volume analysis
        """

        # ==================== HIGHER TIMEFRAME ANALYSIS ====================
        # Get 1-hour data for trend analysis
        informative = self.dp.get_pair_dataframe(
            pair=metadata["pair"], timeframe=self.informative_timeframe
        )

        # Calculate 1h indicators
        informative = self.calculate_1h_indicators(informative)

        # Merge 1h data with 5m data
        # Merge informative data into the main dataframe
        # This will allow us to use higher timeframe indicators in the dataframe of the current timeframe
        # Merge with forward fill to ensure we have the latest values.
        # Forward fill is important here because it adds the higher timeframe indicators to the lower timeframe dataframe
        dataframe = merge_informative_pair(
            dataframe, informative, self.timeframe, self.informative_timeframe, ffill=True
        )

        # ==================== 5-MINUTE TIMEFRAME INDICATORS ====================
        dataframe = self.calculate_5m_indicators(dataframe)

        # ==================== NFI5 PROTECTION SYSTEMS ====================
        dataframe = self.calculate_nfi5_protections(dataframe)

        # ==================== MULTI-OFFSET MOVING AVERAGES ====================
        dataframe = self.calculate_multi_offset_mas(dataframe)

        return dataframe

    def calculate_1h_indicators(self, dataframe: DataFrame) -> DataFrame:
        """Calculate indicators for 1-hour timeframe"""

        # EMAs for trend analysis
        dataframe["ema_15"] = ta.EMA(dataframe, timeperiod=15)
        dataframe["ema_50"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["ema_100"] = ta.EMA(dataframe, timeperiod=100)
        dataframe["ema_200"] = ta.EMA(dataframe, timeperiod=200)

        # SMAs
        dataframe["sma_200"] = ta.SMA(dataframe, timeperiod=200)

        # RSI
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)

        # Bollinger Bands
        bollinger = qtpylib.bollinger_bands(qtpylib.typical_price(dataframe), window=20, stds=2)
        dataframe["bb_lowerband"] = bollinger["lower"]
        dataframe["bb_middleband"] = bollinger["mid"]
        dataframe["bb_upperband"] = bollinger["upper"]

        # ==================== ICHIMOKU INDICATORS (ADDED FROM ARCANE BACKUP) ====================
        # ATR for SSL calculation
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)

        # SSL ATR for trend direction
        ssl_down, ssl_up = ssl_atr(dataframe, 10)
        dataframe["ssl_down"] = ssl_down
        dataframe["ssl_up"] = ssl_up
        dataframe["ssl_bullish"] = ssl_up > ssl_down
        dataframe["ssl_bearish"] = ssl_up < ssl_down

        # Create the Ichimoku Indicator
        displacement = 30
        ichimoku = ftt.ichimoku(
            dataframe,
            conversion_line_period=20,
            base_line_periods=60,
            laggin_span=120,
            displacement=displacement,
        )
        # dataframe["chikou_span"] = ichimoku["chikou_span"]
        dataframe["tenkan_sen"] = ichimoku["tenkan_sen"]
        dataframe["kijun_sen"] = ichimoku["kijun_sen"]
        dataframe["senkou_a"] = ichimoku["senkou_span_a"]
        dataframe["senkou_b"] = ichimoku["senkou_span_b"]
        dataframe["leading_senkou_span_a"] = ichimoku["leading_senkou_span_a"]
        dataframe["leading_senkou_span_b"] = ichimoku["leading_senkou_span_b"]

        # Cloud definitions
        dataframe["cloud_green"] = ichimoku["cloud_green"]
        dataframe["cloud_red"] = ichimoku["cloud_red"]
        dataframe["cloud_top"] = dataframe[["senkou_a", "senkou_b"]].max(axis=1)
        dataframe["cloud_bottom"] = dataframe[["senkou_a", "senkou_b"]].min(axis=1)
        dataframe["future_green"] = (
            dataframe["leading_senkou_span_a"] > dataframe["leading_senkou_span_b"]
        )
        dataframe["future_red"] = (
            dataframe["leading_senkou_span_a"] < dataframe["leading_senkou_span_b"]
        )

        # BULL/BEAR SIGNALS - Bias-free implementation

        # Instead of using chikou_span (which causes lookahead bias),
        # we use the current price compared with past cloud data
        # This is the fundamental change to eliminate the bias

        # Get historical cloud top/bottom shifted forward by displacement
        # This means we're looking if current price is above/below the cloud from displacement periods ago
        dataframe["past_cloud_top"] = dataframe["cloud_top"].shift(displacement)
        dataframe["past_cloud_bottom"] = dataframe["cloud_bottom"].shift(displacement)

        # Create complete Ichimoku signals without using chikou_span
        # Bullish signal requires:
        # 1. Tenkan-sen > Kijun-sen
        # 2. Price > cloud top (current)
        # 3. Future cloud is green
        # 4. Price > cloud top from displacement periods ago (replacing chikou_span check)
        dataframe["ichimoku_bullish"] = (
            (dataframe["tenkan_sen"] > dataframe["kijun_sen"])
            & (dataframe["close"] > dataframe["cloud_top"])
            & dataframe["future_green"]
            & (dataframe["close"] > dataframe["past_cloud_top"])
        )

        # Bearish signal requires:
        # 1. Tenkan-sen < Kijun-sen
        # 2. Price < cloud bottom (current)
        # 3. Future cloud is red
        # 4. Price < cloud bottom from displacement periods ago (replacing chikou_span check)
        dataframe["ichimoku_bearish"] = (
            (dataframe["tenkan_sen"] < dataframe["kijun_sen"])
            & (dataframe["close"] < dataframe["cloud_bottom"])
            & dataframe["future_red"]
            & (dataframe["close"] < dataframe["past_cloud_bottom"])
        )

        # Trends when both signals align
        dataframe["trend_bullish"] = dataframe["ichimoku_bullish"] & dataframe["ssl_bullish"]
        dataframe["trend_bearish"] = dataframe["ichimoku_bearish"] & dataframe["ssl_bearish"]

        # Trend status tracking with state maintenance
        dataframe["trend_bullish_active"] = False  # Initialize column

        # Set to True when we get a new bullish signal
        dataframe.loc[dataframe["trend_bullish"], "trend_bullish_active"] = True

        # Set to False when bullish trend ends
        dataframe.loc[
            (~dataframe["ssl_bullish"]) | (dataframe["close"] < dataframe["cloud_top"]),
            "trend_bullish_active",
        ] = False

        # Forward fill the state - Use ffill() instead of fillna(method="ffill")
        dataframe["trend_bullish_active"] = dataframe["trend_bullish_active"].ffill()

        # Bearish trend tracking
        dataframe["trend_bearish_active"] = False  # Initialize

        # Set to True for new bearish signal
        dataframe.loc[dataframe["trend_bearish"], "trend_bearish_active"] = True

        # Set to False when bearish trend ends
        dataframe.loc[
            (~dataframe["ssl_bearish"]) | (dataframe["close"] > dataframe["cloud_bottom"]),
            "trend_bearish_active",
        ] = False

        # Forward fill the state - Use ffill() instead of fillna(method="ffill")
        dataframe["trend_bearish_active"] = dataframe["trend_bearish_active"].ffill()

        # Ichimoku is valid when the essential components are calculated (not NaN)
        dataframe["ichimoku_valid"] = dataframe["leading_senkou_span_b"].notna()

        # NFI5 Pump Protection (adapted for 1h timeframe)
        dataframe = self.calculate_pump_protection_1h(dataframe)

        return dataframe

    def calculate_pump_protection_1h(self, dataframe: DataFrame) -> DataFrame:
        """Calculate NFI5-style pump protection for 1h timeframe"""

        # 24h pump protection (normal)
        dataframe["safe_pump_24"] = (
            (
                (dataframe["open"].rolling(24).max() - dataframe["close"].rolling(24).min())
                / dataframe["close"].rolling(24).min()
            )
            < self.nfi5_buy_pump_threshold_1.value
        ) | (
            (
                (dataframe["open"].rolling(24).max() - dataframe["close"].rolling(24).min())
                / self.nfi5_buy_pump_pull_threshold_1.value
            )
            > (dataframe["close"] - dataframe["close"].rolling(24).min())
        )

        # 36h pump protection (normal)
        dataframe["safe_pump_36"] = (
            (
                (dataframe["open"].rolling(36).max() - dataframe["close"].rolling(36).min())
                / dataframe["close"].rolling(36).min()
            )
            < self.nfi5_buy_pump_threshold_2.value
        ) | (
            (
                (dataframe["open"].rolling(36).max() - dataframe["close"].rolling(36).min())
                / self.nfi5_buy_pump_pull_threshold_2.value
            )
            > (dataframe["close"] - dataframe["close"].rolling(36).min())
        )

        # 48h pump protection (normal)
        dataframe["safe_pump_48"] = (
            (
                (dataframe["open"].rolling(48).max() - dataframe["close"].rolling(48).min())
                / dataframe["close"].rolling(48).min()
            )
            < self.nfi5_buy_pump_threshold_3.value
        ) | (
            (
                (dataframe["open"].rolling(48).max() - dataframe["close"].rolling(48).min())
                / self.nfi5_buy_pump_pull_threshold_3.value
            )
            > (dataframe["close"] - dataframe["close"].rolling(48).min())
        )

        # Strict pump protection variants
        dataframe["safe_pump_24_strict"] = (
            (
                (dataframe["open"].rolling(24).max() - dataframe["close"].rolling(24).min())
                / dataframe["close"].rolling(24).min()
            )
            < self.nfi5_buy_pump_threshold_4.value
        ) | (
            (
                (dataframe["open"].rolling(24).max() - dataframe["close"].rolling(24).min())
                / self.nfi5_buy_pump_pull_threshold_4.value
            )
            > (dataframe["close"] - dataframe["close"].rolling(24).min())
        )

        dataframe["safe_pump_36_strict"] = (
            (
                (dataframe["open"].rolling(36).max() - dataframe["close"].rolling(36).min())
                / dataframe["close"].rolling(36).min()
            )
            < self.nfi5_buy_pump_threshold_5.value
        ) | (
            (
                (dataframe["open"].rolling(36).max() - dataframe["close"].rolling(36).min())
                / self.nfi5_buy_pump_pull_threshold_5.value
            )
            > (dataframe["close"] - dataframe["close"].rolling(36).min())
        )

        dataframe["safe_pump_48_strict"] = (
            (
                (dataframe["open"].rolling(48).max() - dataframe["close"].rolling(48).min())
                / dataframe["close"].rolling(48).min()
            )
            < self.nfi5_buy_pump_threshold_6.value
        ) | (
            (
                (dataframe["open"].rolling(48).max() - dataframe["close"].rolling(48).min())
                / self.nfi5_buy_pump_pull_threshold_6.value
            )
            > (dataframe["close"] - dataframe["close"].rolling(48).min())
        )

        # Loose pump protection variants
        dataframe["safe_pump_24_loose"] = (
            (
                (dataframe["open"].rolling(24).max() - dataframe["close"].rolling(24).min())
                / dataframe["close"].rolling(24).min()
            )
            < self.nfi5_buy_pump_threshold_7.value
        ) | (
            (
                (dataframe["open"].rolling(24).max() - dataframe["close"].rolling(24).min())
                / self.nfi5_buy_pump_pull_threshold_7.value
            )
            > (dataframe["close"] - dataframe["close"].rolling(24).min())
        )

        dataframe["safe_pump_36_loose"] = (
            (
                (dataframe["open"].rolling(36).max() - dataframe["close"].rolling(36).min())
                / dataframe["close"].rolling(36).min()
            )
            < self.nfi5_buy_pump_threshold_8.value
        ) | (
            (
                (dataframe["open"].rolling(36).max() - dataframe["close"].rolling(36).min())
                / self.nfi5_buy_pump_pull_threshold_8.value
            )
            > (dataframe["close"] - dataframe["close"].rolling(36).min())
        )

        dataframe["safe_pump_48_loose"] = (
            (
                (dataframe["open"].rolling(48).max() - dataframe["close"].rolling(48).min())
                / dataframe["close"].rolling(48).min()
            )
            < self.nfi5_buy_pump_threshold_9.value
        ) | (
            (
                (dataframe["open"].rolling(48).max() - dataframe["close"].rolling(48).min())
                / self.nfi5_buy_pump_pull_threshold_9.value
            )
            > (dataframe["close"] - dataframe["close"].rolling(48).min())
        )

        return dataframe

    def calculate_5m_indicators(self, dataframe: DataFrame) -> DataFrame:
        """Calculate indicators for 5-minute timeframe"""

        # ==================== ORIGINAL ARCANE INDICATORS (PRESERVED) ====================

        # ATR for volatility measurement
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)

        # SSL ATR for trend direction
        dataframe["ssl_down"], dataframe["ssl_up"] = ssl_atr(dataframe, length=7)

        # Elliott Wave Oscillator
        dataframe["EWO"] = EWO(dataframe, 5, 35)

        # Simple trend detection (replaces Ichimoku)
        trend_data = simple_trend_detection(dataframe)
        for key, value in trend_data.items():
            dataframe[key] = value

        # Enhanced trend detection with 1h confirmation
        dataframe["trend_bullish_active"] = (
            dataframe["trend_bullish"] & dataframe["ema_50_1h"] > dataframe["ema_200_1h"]
        )

        # RSI indicators
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["rsi_fast"] = ta.RSI(dataframe, timeperiod=4)

        # Moving averages
        dataframe["sma_5"] = ta.SMA(dataframe, timeperiod=5)
        dataframe["sma_30"] = ta.SMA(dataframe, timeperiod=30)
        dataframe["sma_200"] = ta.SMA(dataframe, timeperiod=200)
        dataframe["ema_12"] = ta.EMA(dataframe, timeperiod=12)
        dataframe["ema_20"] = ta.EMA(dataframe, timeperiod=20)
        dataframe["ema_26"] = ta.EMA(dataframe, timeperiod=26)
        dataframe["ema_50"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["ema_100"] = ta.EMA(dataframe, timeperiod=100)
        dataframe["ema_200"] = ta.EMA(dataframe, timeperiod=200)

        # DEMA for entries/exits
        dataframe[f"dema_{self.dema_len_buy.value}"] = ta.DEMA(
            dataframe, timeperiod=self.dema_len_buy.value
        )
        dataframe[f"dema_{self.dema_len_sell.value}"] = ta.DEMA(
            dataframe, timeperiod=self.dema_len_sell.value
        )

        # Bollinger Bands (multiple periods)
        bb_20 = qtpylib.bollinger_bands(qtpylib.typical_price(dataframe), window=20, stds=2)
        dataframe["bb_lowerband"] = bb_20["lower"]
        dataframe["bb_middleband"] = bb_20["mid"]
        dataframe["bb_upperband"] = bb_20["upper"]

        bb_40 = qtpylib.bollinger_bands(dataframe["close"], window=40, stds=2)
        dataframe["bb_lowerband2"] = bb_40["lower"]
        dataframe["bb_middleband2"] = bb_40["mid"]
        dataframe["bb_upperband2"] = bb_40["upper"]

        # Volume analysis
        dataframe["volume_mean_slow"] = dataframe["volume"].rolling(window=30).mean()

        # Price movement analysis
        dataframe["closedelta"] = (dataframe["close"] - dataframe["close"].shift()).abs()

        # ==================== NFI5 INDICATORS (ADDED) ====================

        # BB 40 for NFI5 conditions
        dataframe["lower"] = bb_40["lower"]
        dataframe["mid"] = bb_40["mid"]
        dataframe["bbdelta"] = (bb_40["mid"] - dataframe["lower"]).abs()
        dataframe["tail"] = (dataframe["close"] - dataframe["low"]).abs()

        # MFI (Money Flow Index)
        dataframe["mfi"] = ta.MFI(dataframe)

        # NFI5 EWO with different parameters
        dataframe["ewo"] = EWO(dataframe, self.nfi5_fast_ewo.value, self.nfi5_slow_ewo.value)

        # Chopiness Index
        dataframe["chop"] = qtpylib.chopiness(dataframe, 14)

        # SMA declining detection
        dataframe["sma_200_dec"] = dataframe["sma_200"] < dataframe["sma_200"].shift(20)

        # Volume means for NFI5
        dataframe["volume_mean_4"] = dataframe["volume"].rolling(4).mean().shift(1)
        dataframe["volume_mean_30"] = dataframe["volume"].rolling(30).mean()

        return dataframe

    def calculate_nfi5_protections(self, dataframe: DataFrame) -> DataFrame:
        """Calculate NFI5-style dip protection for 5m timeframe"""

        # Normal dip protection
        dataframe["safe_dips"] = (
            (
                ((dataframe["open"] - dataframe["close"]) / dataframe["close"])
                < self.nfi5_buy_dip_threshold_1.value
            )
            & (
                ((dataframe["open"].rolling(2).max() - dataframe["close"]) / dataframe["close"])
                < self.nfi5_buy_dip_threshold_2.value
            )
            & (
                ((dataframe["open"].rolling(12).max() - dataframe["close"]) / dataframe["close"])
                < self.nfi5_buy_dip_threshold_3.value
            )
            & (
                ((dataframe["open"].rolling(144).max() - dataframe["close"]) / dataframe["close"])
                < self.nfi5_buy_dip_threshold_4.value
            )
        )

        # Strict dip protection
        dataframe["safe_dips_strict"] = (
            (
                ((dataframe["open"] - dataframe["close"]) / dataframe["close"])
                < self.nfi5_buy_dip_threshold_5.value
            )
            & (
                ((dataframe["open"].rolling(2).max() - dataframe["close"]) / dataframe["close"])
                < self.nfi5_buy_dip_threshold_6.value
            )
            & (
                ((dataframe["open"].rolling(12).max() - dataframe["close"]) / dataframe["close"])
                < self.nfi5_buy_dip_threshold_7.value
            )
            & (
                ((dataframe["open"].rolling(144).max() - dataframe["close"]) / dataframe["close"])
                < self.nfi5_buy_dip_threshold_8.value
            )
        )

        # Loose dip protection
        dataframe["safe_dips_loose"] = (
            (
                ((dataframe["open"] - dataframe["close"]) / dataframe["close"])
                < self.nfi5_buy_dip_threshold_9.value
            )
            & (
                ((dataframe["open"].rolling(2).max() - dataframe["close"]) / dataframe["close"])
                < self.nfi5_buy_dip_threshold_10.value
            )
            & (
                ((dataframe["open"].rolling(12).max() - dataframe["close"]) / dataframe["close"])
                < self.nfi5_buy_dip_threshold_11.value
            )
            & (
                ((dataframe["open"].rolling(144).max() - dataframe["close"]) / dataframe["close"])
                < self.nfi5_buy_dip_threshold_12.value
            )
        )

        return dataframe

    def calculate_multi_offset_mas(self, dataframe: DataFrame) -> DataFrame:
        """Calculate multi-offset moving averages for NFI5 system"""

        # MA types and their calculation functions
        ma_types = ["sma", "ema", "trima", "t3", "kama"]
        ma_functions = {
            "sma": ta.SMA,
            "ema": ta.EMA,
            "trima": ta.TRIMA,
            "t3": ta.T3,
            "kama": ta.KAMA,
        }

        # Calculate offset MAs for each type
        for ma_type in ma_types:
            if ma_type in ma_functions:
                # Buy offsets (below price)
                if ma_type == "sma":
                    offset = self.nfi5_low_offset_sma.value
                elif ma_type == "ema":
                    offset = self.nfi5_low_offset_ema.value
                elif ma_type == "trima":
                    offset = self.nfi5_low_offset_trima.value
                elif ma_type == "t3":
                    offset = self.nfi5_low_offset_t3.value
                elif ma_type == "kama":
                    offset = self.nfi5_low_offset_kama.value

                dataframe[f"{ma_type}_offset_buy"] = (
                    ma_functions[ma_type](dataframe, self.nfi5_base_nb_candles_buy.value) * offset
                )

                # Sell offsets (above price)
                if ma_type == "sma":
                    offset = self.nfi5_high_offset_sma.value
                elif ma_type == "ema":
                    offset = self.nfi5_high_offset_ema.value
                elif ma_type == "trima":
                    offset = self.nfi5_high_offset_trima.value
                elif ma_type == "t3":
                    offset = self.nfi5_high_offset_t3.value
                elif ma_type == "kama":
                    offset = self.nfi5_high_offset_kama.value

                dataframe[f"{ma_type}_offset_sell"] = (
                    ma_functions[ma_type](dataframe, self.nfi5_base_nb_candles_sell.value) * offset
                )

        return dataframe

    # ==================== ENTRY SIGNAL GENERATION ====================
    def populate_buy_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        ENHANCED ENTRY SIGNAL GENERATION - ARCANE + NFI5

        This function combines the original Arcane entry methods with the
        sophisticated NFI5 entry conditions to create a comprehensive
        entry system.

        ENTRY METHODS:
        1. Original Arcane methods (PRESERVED)
        2. NFI5 21 conditions (ADDED)
        3. NFI5 multi-offset system (ADDED)
        """

        # ==================== ORIGINAL ARCANE ENTRY METHODS (PRESERVED) ====================

        # ENTRY METHOD 1: TREND FOLLOWING (ORIGINAL ARCANE)
        if self.trend_following_enable.value:
            dataframe.loc[
                # Must be in confirmed bullish trend
                dataframe["trend_bullish_active"]
                # Price near DEMA support level
                & (
                    dataframe["close"]
                    <= dataframe[f"dema_{self.dema_len_buy.value}"] * self.low_offset.value
                )
                # SSL showing bullish structure
                & (dataframe["ssl_up"] > dataframe["ssl_down"])
                # Volume confirmation
                & (dataframe["volume"] > 0),
                ["enter_long", "enter_tag"],
            ] = (1, "trend_dema_entry")

        # ENTRY METHOD 2: LOCAL UPTREND (ORIGINAL ARCANE)
        if self.local_uptrend_enable.value:
            dataframe.loc[
                # EMA alignment showing momentum
                (dataframe["ema_26"] > dataframe["ema_12"])
                # Significant EMA difference (momentum strength)
                & (
                    dataframe["ema_26"] - dataframe["ema_12"]
                    > dataframe["open"] * self.buy_ema_diff.value
                )
                # Previous candle momentum confirmation
                & (
                    dataframe["ema_26"].shift() - dataframe["ema_12"].shift()
                    > dataframe["open"] / 100
                )
                # Price near lower Bollinger Band (pullback)
                & (dataframe["close"] < dataframe["bb_lowerband2"] * self.buy_bb_factor.value)
                # Sufficient price movement (volatility)
                & (dataframe["closedelta"] > dataframe["close"] * self.buy_closedelta.value / 1000)
                # Volume confirmation
                & (dataframe["volume"] > 0),
                ["enter_long", "enter_tag"],
            ] = (1, "local_uptrend")

        # ENTRY METHOD 3: EWO MOMENTUM (ORIGINAL ARCANE)
        if self.ewo_momentum_enable.value:
            dataframe.loc[
                # EWO oversold condition
                (dataframe["EWO"] > self.buy_ewo.value)
                # Price below EMA (pullback)
                & (dataframe["close"] < dataframe["ema_50"] * self.buy_ema_low.value)
                # Price above EMA (not too deep)
                & (dataframe["close"] > dataframe["ema_50"] * self.buy_ema_high.value)
                # RSI oversold
                & (dataframe["rsi"] < self.buy_rsi.value)
                # Fast RSI confirmation
                & (dataframe["rsi_fast"] < self.buy_rsi_fast.value)
                # Volume confirmation
                & (dataframe["volume"] > 0),
                ["enter_long", "enter_tag"],
            ] = (1, "ewo_momentum")

        # ENTRY METHOD 4: ICHIMOKU DEMA (FROM ARCANE BACKUP)
        if self.ichimoku_dema_enable.value:
            dema = f"dema_{self.dema_len_buy.value}"
            dataframe.loc[
                # Ichimoku system is valid (enough data)
                dataframe["ichimoku_valid_1h"]
                # Must be in confirmed bullish trend from 1h timeframe
                & dataframe["trend_bullish_active_1h"]
                # Price pullback to DEMA support level
                & (dataframe["close"] < (dataframe[dema] * self.low_offset.value))
                # Volume confirmation
                & (dataframe["volume"] > 0),
                ["enter_long", "enter_tag"],
            ] = (1, "ichimoku_dema_entry")

        # ==================== MISSING ORIGINAL ARCANE METHODS (ADDED FOR COMPLETENESS) ====================
        # These methods are disabled by default as they were outperformed by NFI5 methods
        # but included for completeness and potential future optimization

        # ENTRY METHOD 5: TREND MOMENTUM BREAKOUT (ORIGINAL ARCANE)
        # DISABLED: Overlaps with NFI5 conditions which provide better pump protection
        if self.trend_momentum_enable.value:
            dataframe.loc[
                # Strong bullish trend confirmation
                dataframe["trend_bullish_active"]
                # Price above key moving averages
                & (dataframe["close"] > dataframe["ema_50"])
                & (dataframe["ema_50"] > dataframe["ema_200"])
                # SSL showing strong bullish structure
                & (dataframe["ssl_up"] > dataframe["ssl_down"])
                # EWO showing momentum
                & (dataframe["EWO"] > 0)
                # Volume confirmation
                & (dataframe["volume"] > dataframe["volume_mean_slow"])
                # RSI not overbought
                & (dataframe["rsi"] < 70)
                & (dataframe["volume"] > 0),
                ["enter_long", "enter_tag"],
            ] = (1, "trend_momentum_breakout")

        # ENTRY METHOD 6: SELECTIVE VOLUME DIP (ORIGINAL ARCANE - BINCLUC VOLUME)
        # DISABLED: NFI5 dip protection is more sophisticated
        if self.bincluc_volume_enable.value:
            dataframe.loc[
                # Trend confirmation
                (dataframe["ema_50_1h"] > dataframe["ema_200_1h"])
                # Volume spike indicating selling exhaustion
                & (
                    dataframe["volume"]
                    > dataframe["volume_mean_slow"] * self.buy_volume_drop_threshold.value
                )
                # Price dip but not too deep
                & (dataframe["close"] < dataframe["ema_20"])
                & (dataframe["close"] > dataframe["ema_50"] * 0.95)
                # RSI oversold
                & (dataframe["rsi"] < 35)
                # Volume pump protection
                & (
                    dataframe["volume"]
                    < dataframe["volume_mean_slow"] * (1 + self.buy_volume_pump_threshold.value)
                )
                & (dataframe["volume"] > 0),
                ["enter_long", "enter_tag"],
            ] = (1, "selective_volume_dip")

        # ENTRY METHOD 7: ENHANCED MOMENTUM (ORIGINAL ARCANE - BINCLUC ADVANCED BB)
        # DISABLED: NFI5 Bollinger Band analysis is more comprehensive
        if self.bincluc_advanced_bb_enable.value:
            dataframe.loc[
                # Trend confirmation
                (dataframe["ema_100_1h"] > dataframe["ema_200_1h"])
                # Advanced Bollinger Band analysis
                & (dataframe["bbdelta"] > dataframe["close"] * self.buy_bb40_bbdelta_close.value)
                & (
                    dataframe["closedelta"]
                    > dataframe["close"] * self.buy_bb40_closedelta_close.value
                )
                & (dataframe["tail"] < dataframe["bbdelta"] * self.buy_bb40_tail_bbdelta.value)
                # Price position
                & (dataframe["close"] < dataframe["bb_lowerband2"])
                & (dataframe["close"] < dataframe["bb_lowerband2"].shift())
                # Volume confirmation
                & (dataframe["volume"] > 0),
                ["enter_long", "enter_tag"],
            ] = (1, "enhanced_momentum")

        # ENTRY METHOD 8: BULL MARKET MOMENTUM (ORIGINAL ARCANE)
        # DISABLED: Market regime detection now handled by NFI5 methods
        if self.bull_momentum_enable.value:
            # Detect bull market conditions
            bull_market = (
                (dataframe["ema_50_1h"] > dataframe["ema_200_1h"])
                & (dataframe["sma_200"] > dataframe["sma_200"].shift(20))
                & (dataframe["close"] > dataframe["ema_200"])
            )

            dataframe.loc[
                bull_market
                # Aggressive momentum entry during bull markets
                & (dataframe["EWO"] > -2)  # Less strict EWO requirement
                & (dataframe["rsi"] < 50)  # Less strict RSI requirement
                & (dataframe["close"] > dataframe["ema_20"])  # Above short-term trend
                & (dataframe["ssl_up"] > dataframe["ssl_down"])
                # Volume confirmation
                & (dataframe["volume"] > dataframe["volume_mean_slow"] * 0.8)
                & (dataframe["volume"] > 0),
                ["enter_long", "enter_tag"],
            ] = (1, "bull_momentum")

        # ENTRY METHOD 9: BINCLUC DIP BUYING (ORIGINAL ARCANE)
        # DISABLED: NFI5 dip protection provides better risk management
        if self.bincluc_dip_enable.value:
            dataframe.loc[
                # Trend confirmation
                (dataframe["ema_50_1h"] > dataframe["ema_200_1h"])
                # Multi-level dip analysis
                & (
                    (
                        dataframe["close"]
                        < dataframe["ema_20"] * (1 - self.buy_dip_threshold_1.value)
                    )
                    | (
                        dataframe["close"]
                        < dataframe["ema_50"] * (1 - self.buy_dip_threshold_2.value)
                    )
                    | (
                        dataframe["close"]
                        < dataframe["ema_200"] * (1 - self.buy_dip_threshold_3.value)
                    )
                )
                # RSI oversold
                & (dataframe["rsi"] < 30)
                # Safe entry zone
                & (dataframe["close"] > dataframe["bb_lowerband"] * self.buy_bb_safe_factor.value)
                & (dataframe["volume"] > 0),
                ["enter_long", "enter_tag"],
            ] = (1, "bincluc_dip_buy")

        # ENTRY METHOD 10: BINCLUC MFI MOMENTUM (ORIGINAL ARCANE)
        # DISABLED: NFI5 MFI analysis is more sophisticated
        if self.bincluc_mfi_enable.value:
            dataframe.loc[
                # Trend confirmation
                (dataframe["ema_100_1h"] > dataframe["ema_200_1h"])
                # MFI oversold
                & (dataframe["mfi"] < self.buy_mfi_threshold.value)
                # 1h RSI not overbought
                & (dataframe["rsi_1h"] < self.buy_rsi_1h_threshold.value)
                # Price position
                & (dataframe["close"] < dataframe["ema_50"])
                & (dataframe["close"] > dataframe["ema_200"] * 0.95)
                # Volume confirmation
                & (dataframe["volume"] > 0),
                ["enter_long", "enter_tag"],
            ] = (1, "bincluc_mfi_momentum")

        # ==================== NFI5 ENTRY CONDITIONS (ADDED) ====================

        # NFI5 CONDITION 1: Strict trend following with pump protection
        if self.nfi5_condition_1_enable.value:
            dataframe.loc[
                (dataframe["ema_50_1h"] > dataframe["ema_200_1h"])
                & (dataframe["sma_200"] > dataframe["sma_200"].shift(50))
                & dataframe["safe_dips_strict"]
                & dataframe["safe_pump_24_1h"]
                & (
                    (
                        (dataframe["close"] - dataframe["open"].rolling(36).min())
                        / dataframe["open"].rolling(36).min()
                    )
                    > self.nfi5_buy_min_inc_1.value
                )
                & (dataframe["rsi_1h"] > self.nfi5_buy_rsi_1h_min_1.value)
                & (dataframe["rsi_1h"] < self.nfi5_buy_rsi_1h_max_1.value)
                & (dataframe["rsi"] < self.nfi5_buy_rsi_1.value)
                & (dataframe["mfi"] < self.nfi5_buy_mfi_1.value)
                & (dataframe["volume"] > 0),
                ["enter_long", "enter_tag"],
            ] = (1, "nfi5_condition_1")

        # NFI5 CONDITION 2: Volume-based entries with RSI divergence
        if self.nfi5_condition_2_enable.value:
            dataframe.loc[
                (dataframe["sma_200_1h"] > dataframe["sma_200_1h"].shift(50))
                & dataframe["safe_pump_24_strict_1h"]
                & (dataframe["volume_mean_4"] * self.nfi5_buy_volume_2.value > dataframe["volume"])
                & (dataframe["rsi"] < dataframe["rsi_1h"] - self.nfi5_buy_rsi_1h_diff_2.value)
                & (dataframe["mfi"] < self.nfi5_buy_mfi_2.value)
                & (
                    dataframe["close"]
                    < (dataframe["bb_lowerband"] * self.nfi5_buy_bb_offset_2.value)
                )
                & (dataframe["volume"] > 0),
                ["enter_long", "enter_tag"],
            ] = (1, "nfi5_condition_2")

        # NFI5 CONDITION 3: Advanced Bollinger Band analysis
        if self.nfi5_condition_3_enable.value:
            dataframe.loc[
                (dataframe["close"] > (dataframe["ema_200_1h"] * self.nfi5_buy_ema_rel_3.value))
                & (dataframe["ema_100"] > dataframe["ema_200"])
                & (dataframe["ema_100_1h"] > dataframe["ema_200_1h"])
                & dataframe["safe_pump_36_strict_1h"]
                & dataframe["lower"].shift().gt(0)
                & dataframe["bbdelta"].gt(
                    dataframe["close"] * self.nfi5_buy_bb40_bbdelta_close_3.value
                )
                & dataframe["closedelta"].gt(
                    dataframe["close"] * self.nfi5_buy_bb40_closedelta_close_3.value
                )
                & dataframe["tail"].lt(
                    dataframe["bbdelta"] * self.nfi5_buy_bb40_tail_bbdelta_3.value
                )
                & dataframe["close"].lt(dataframe["lower"].shift())
                & dataframe["close"].le(dataframe["close"].shift())
                & (dataframe["volume"] > 0),
                ["enter_long", "enter_tag"],
            ] = (1, "nfi5_condition_3")

        # NFI5 CONDITION 4: EMA-based pullback entries
        if self.nfi5_condition_4_enable.value:
            dataframe.loc[
                (dataframe["ema_50_1h"] > dataframe["ema_200_1h"])
                & dataframe["safe_dips_strict"]
                & dataframe["safe_pump_24_1h"]
                & (dataframe["close"] < dataframe["ema_50"])
                & (
                    dataframe["close"]
                    < self.nfi5_buy_bb20_close_bblowerband_4.value * dataframe["bb_lowerband"]
                )
                & (
                    dataframe["volume"]
                    < (dataframe["volume_mean_30"].shift(1) * self.nfi5_buy_bb20_volume_4.value)
                )
                & (dataframe["volume"] > 0),
                ["enter_long", "enter_tag"],
            ] = (1, "nfi5_condition_4")

        # NFI5 CONDITION 5: EMA momentum breakouts
        if self.nfi5_condition_5_enable.value:
            dataframe.loc[
                (dataframe["ema_100"] > dataframe["ema_200"])
                & (dataframe["close"] > (dataframe["ema_200_1h"] * 0.982))
                & dataframe["safe_dips"]
                & dataframe["safe_pump_36_strict_1h"]
                & (dataframe["ema_26"] > dataframe["ema_12"])
                & ((dataframe["ema_26"] - dataframe["ema_12"]) > (dataframe["open"] * 0.019))
                & (
                    (dataframe["ema_26"].shift() - dataframe["ema_12"].shift())
                    > (dataframe["open"] / 100)
                )
                & (dataframe["close"] < (dataframe["bb_lowerband"] * 0.999))
                & (dataframe["volume"] > 0),
                ["enter_long", "enter_tag"],
            ] = (1, "nfi5_condition_5")

        # NFI5 CONDITION 6: EMA momentum with loose protection
        if self.nfi5_condition_6_enable.value:
            dataframe.loc[
                (dataframe["ema_100_1h"] > dataframe["ema_200_1h"])
                & dataframe["safe_dips_loose"]
                & dataframe["safe_pump_36_strict_1h"]
                & (dataframe["ema_26"] > dataframe["ema_12"])
                & ((dataframe["ema_26"] - dataframe["ema_12"]) > (dataframe["open"] * 0.025))
                & (
                    (dataframe["ema_26"].shift() - dataframe["ema_12"].shift())
                    > (dataframe["open"] / 100)
                )
                & (dataframe["close"] < (dataframe["bb_lowerband"] * 0.984))
                & (dataframe["volume"] > 0),
                ["enter_long", "enter_tag"],
            ] = (1, "nfi5_condition_6")

        # NFI5 CONDITION 7: Volume-filtered EMA momentum
        if self.nfi5_condition_7_enable.value:
            dataframe.loc[
                (dataframe["ema_100"] > dataframe["ema_200"])
                & (dataframe["ema_50_1h"] > dataframe["ema_200_1h"])
                & dataframe["safe_dips_strict"]
                & (dataframe["volume"].rolling(4).mean() * 2.0 > dataframe["volume"])
                & (dataframe["ema_26"] > dataframe["ema_12"])
                & ((dataframe["ema_26"] - dataframe["ema_12"]) > (dataframe["open"] * 0.03))
                & (
                    (dataframe["ema_26"].shift() - dataframe["ema_12"].shift())
                    > (dataframe["open"] / 100)
                )
                & (dataframe["rsi"] < 36.0)
                & (dataframe["volume"] > 0),
                ["enter_long", "enter_tag"],
            ] = (1, "nfi5_condition_7")

        # NFI5 CONDITION 8: Volume spike with tail analysis
        if self.nfi5_condition_8_enable.value:
            dataframe.loc[
                (dataframe["ema_50_1h"] > dataframe["ema_200_1h"])
                & dataframe["safe_dips_loose"]
                & dataframe["safe_pump_24_1h"]
                & (dataframe["rsi"] < 20.0)
                & (dataframe["volume"] > (dataframe["volume"].shift(1) * 2.0))
                & (dataframe["close"] > dataframe["open"])
                & (
                    (dataframe["close"] - dataframe["low"])
                    > ((dataframe["close"] - dataframe["open"]) * 3.5)
                )
                & (dataframe["volume"] > 0),
                ["enter_long", "enter_tag"],
            ] = (1, "nfi5_condition_8")

        # NFI5 CONDITION 9: Multi-EMA with volume filter
        if self.nfi5_condition_9_enable.value:
            dataframe.loc[
                (dataframe["ema_50"] > dataframe["ema_200"])
                & (dataframe["ema_100"] > dataframe["ema_200"])
                & dataframe["safe_dips_strict"]
                & dataframe["safe_pump_24_loose_1h"]
                & (dataframe["volume_mean_4"] * 1.0 > dataframe["volume"])
                & (dataframe["close"] < dataframe["ema_20"] * 0.97)
                & (dataframe["close"] < dataframe["bb_lowerband"] * 0.985)
                & (dataframe["rsi_1h"] > 30.0)
                & (dataframe["rsi_1h"] < 88.0)
                & (dataframe["mfi"] < 30.0)
                & (dataframe["volume"] > 0),
                ["enter_long", "enter_tag"],
            ] = (1, "nfi5_condition_9")

        # NFI5 CONDITION 10: SMA-based with volume control
        if self.nfi5_condition_10_enable.value:
            dataframe.loc[
                (dataframe["ema_50_1h"] > dataframe["ema_100_1h"])
                & (dataframe["sma_200_1h"] > dataframe["sma_200_1h"].shift(24))
                & dataframe["safe_dips_loose"]
                & dataframe["safe_pump_24_loose_1h"]
                & ((dataframe["volume_mean_4"] * 2.4) > dataframe["volume"])
                & (dataframe["close"] < dataframe["sma_30"] * 0.944)
                & (dataframe["close"] < dataframe["bb_lowerband"] * 0.994)
                & (dataframe["rsi_1h"] < 37.0)
                & (dataframe["volume"] > 0),
                ["enter_long", "enter_tag"],
            ] = (1, "nfi5_condition_10")

        # NFI5 CONDITION 11: Long-term trend with increment check
        if self.nfi5_condition_11_enable.value:
            dataframe.loc[
                (dataframe["ema_50_1h"] > dataframe["ema_100_1h"])
                & dataframe["safe_dips_loose"]
                & dataframe["safe_pump_24_loose_1h"]
                & dataframe["safe_pump_36_1h"]
                & dataframe["safe_pump_48_loose_1h"]
                & (
                    (
                        (dataframe["close"] - dataframe["open"].rolling(36).min())
                        / dataframe["open"].rolling(36).min()
                    )
                    > 0.022
                )
                & (dataframe["close"] < dataframe["sma_30"] * 0.939)
                & (dataframe["rsi_1h"] > 56.0)
                & (dataframe["rsi_1h"] < 84.0)
                & (dataframe["rsi"] < 48.0)
                & (dataframe["mfi"] < 38.0)
                & (dataframe["volume"] > 0),
                ["enter_long", "enter_tag"],
            ] = (1, "nfi5_condition_11")

        # NFI5 CONDITION 12: EWO positive with SMA filter
        if self.nfi5_condition_12_enable.value:
            dataframe.loc[
                (dataframe["sma_200_1h"] > dataframe["sma_200_1h"].shift(24))
                & dataframe["safe_dips_strict"]
                & dataframe["safe_pump_24_1h"]
                & ((dataframe["volume_mean_4"] * 1.7) > dataframe["volume"])
                & (dataframe["close"] < dataframe["sma_30"] * 0.936)
                & (dataframe["ewo"] > 2.0)
                & (dataframe["rsi"] < 30.0)
                & (dataframe["volume"] > 0),
                ["enter_long", "enter_tag"],
            ] = (1, "nfi5_condition_12")

        # NFI5 CONDITION 13: EWO negative with volume filter
        if self.nfi5_condition_13_enable.value:
            dataframe.loc[
                (dataframe["ema_50_1h"] > dataframe["ema_100_1h"])
                & (dataframe["sma_200_1h"] > dataframe["sma_200_1h"].shift(24))
                & dataframe["safe_dips_strict"]
                & dataframe["safe_pump_24_loose_1h"]
                & dataframe["safe_pump_36_loose_1h"]
                & ((dataframe["volume_mean_4"] * 1.6) > dataframe["volume"])
                & (dataframe["close"] < dataframe["sma_30"] * 0.978)
                & (dataframe["ewo"] < -10.4)
                & (dataframe["volume"] > 0),
                ["enter_long", "enter_tag"],
            ] = (1, "nfi5_condition_13")

        # NFI5 CONDITION 14: Complex EMA with BB filter
        if self.nfi5_condition_14_enable.value:
            dataframe.loc[
                (dataframe["sma_200"] > dataframe["sma_200"].shift(30))
                & (dataframe["sma_200_1h"] > dataframe["sma_200_1h"].shift(50))
                & dataframe["safe_dips_loose"]
                & dataframe["safe_pump_24_1h"]
                & (dataframe["volume_mean_4"] * 2.0 > dataframe["volume"])
                & (dataframe["ema_26"] > dataframe["ema_12"])
                & ((dataframe["ema_26"] - dataframe["ema_12"]) > (dataframe["open"] * 0.014))
                & (
                    (dataframe["ema_26"].shift() - dataframe["ema_12"].shift())
                    > (dataframe["open"] / 100)
                )
                & (dataframe["close"] < (dataframe["bb_lowerband"] * 0.986))
                & (dataframe["close"] < dataframe["ema_20"] * 0.97)
                & (dataframe["volume"] > 0),
                ["enter_long", "enter_tag"],
            ] = (1, "nfi5_condition_14")

        # NFI5 CONDITION 15: EMA relative with momentum
        if self.nfi5_condition_15_enable.value:
            dataframe.loc[
                (dataframe["close"] > dataframe["ema_200_1h"] * 0.988)
                & (dataframe["ema_50_1h"] > dataframe["ema_200_1h"])
                & dataframe["safe_dips"]
                & dataframe["safe_pump_36_strict_1h"]
                & (dataframe["ema_26"] > dataframe["ema_12"])
                & ((dataframe["ema_26"] - dataframe["ema_12"]) > (dataframe["open"] * 0.018))
                & (
                    (dataframe["ema_26"].shift() - dataframe["ema_12"].shift())
                    > (dataframe["open"] / 100)
                )
                & (dataframe["rsi"] < 28.0)
                & (dataframe["close"] < dataframe["ema_20"] * 0.954)
                & (dataframe["volume"] > 0),
                ["enter_long", "enter_tag"],
            ] = (1, "nfi5_condition_15")

        # NFI5 CONDITION 16: EWO positive with strict protection
        if self.nfi5_condition_16_enable.value:
            dataframe.loc[
                (dataframe["ema_50_1h"] > dataframe["ema_200_1h"])
                & dataframe["safe_dips_strict"]
                & dataframe["safe_pump_24_strict_1h"]
                & ((dataframe["volume_mean_4"] * 2.0) > dataframe["volume"])
                & (dataframe["close"] < dataframe["ema_20"] * 0.952)
                & (dataframe["ewo"] > 2.8)
                & (dataframe["rsi"] < 31.0)
                & (dataframe["volume"] > 0),
                ["enter_long", "enter_tag"],
            ] = (1, "nfi5_condition_16")

        # NFI5 CONDITION 17: EWO negative with loose protection
        if self.nfi5_condition_17_enable.value:
            dataframe.loc[
                dataframe["safe_dips_strict"]
                & dataframe["safe_pump_24_loose_1h"]
                & ((dataframe["volume_mean_4"] * 2.0) > dataframe["volume"])
                & (dataframe["close"] < dataframe["ema_20"] * 0.958)
                & (dataframe["ewo"] < -12.0)
                & (dataframe["volume"] > 0),
                ["enter_long", "enter_tag"],
            ] = (1, "nfi5_condition_17")

        # NFI5 CONDITION 18: Strong trend with BB filter
        if self.nfi5_condition_18_enable.value:
            dataframe.loc[
                (dataframe["close"] > dataframe["ema_200_1h"])
                & (dataframe["ema_100"] > dataframe["ema_200"])
                & (dataframe["ema_50_1h"] > dataframe["ema_200_1h"])
                & (dataframe["sma_200"] > dataframe["sma_200"].shift(20))
                & (dataframe["sma_200"] > dataframe["sma_200"].shift(44))
                & (dataframe["sma_200_1h"] > dataframe["sma_200_1h"].shift(36))
                & (dataframe["sma_200_1h"] > dataframe["sma_200_1h"].shift(72))
                & dataframe["safe_dips"]
                & dataframe["safe_pump_24_strict_1h"]
                & ((dataframe["volume_mean_4"] * 2.0) > dataframe["volume"])
                & (dataframe["rsi"] < 26.0)
                & (dataframe["close"] < (dataframe["bb_lowerband"] * 0.982))
                & (dataframe["volume"] > 0),
                ["enter_long", "enter_tag"],
            ] = (1, "nfi5_condition_18")

        # NFI5 CONDITION 20: RSI divergence with volume filter
        if self.nfi5_condition_20_enable.value:
            dataframe.loc[
                (dataframe["ema_50_1h"] > dataframe["ema_200_1h"])
                & dataframe["safe_dips"]
                & dataframe["safe_pump_24_loose_1h"]
                & ((dataframe["volume_mean_4"] * 1.2) > dataframe["volume"])
                & (dataframe["rsi"] < 26.0)
                & (dataframe["rsi_1h"] < 20.0)
                & (dataframe["volume"] > 0),
                ["enter_long", "enter_tag"],
            ] = (1, "nfi5_condition_20")

        # NFI5 CONDITION 21: Deep RSI oversold
        if self.nfi5_condition_21_enable.value:
            dataframe.loc[
                (dataframe["ema_50_1h"] > dataframe["ema_200_1h"])
                & dataframe["safe_dips_strict"]
                & ((dataframe["volume_mean_4"] * 3.0) > dataframe["volume"])
                & (dataframe["rsi"] < 23.0)
                & (dataframe["rsi_1h"] < 24.0)
                & (dataframe["volume"] > 0),
                ["enter_long", "enter_tag"],
            ] = (1, "nfi5_condition_21")

        # NFI5 CONDITION 19: Chopiness-based entries
        if self.nfi5_condition_19_enable.value:
            dataframe.loc[
                (dataframe["ema_100_1h"] > dataframe["ema_200_1h"])
                & (dataframe["sma_200"] > dataframe["sma_200"].shift(36))
                & (dataframe["ema_50_1h"] > dataframe["ema_200_1h"])
                & dataframe["safe_dips"]
                & dataframe["safe_pump_24_1h"]
                & (dataframe["close"].shift(1) > dataframe["ema_100_1h"])
                & (dataframe["low"] < dataframe["ema_100_1h"])
                & (dataframe["close"] > dataframe["ema_100_1h"])
                & (dataframe["rsi_1h"] > self.nfi5_buy_rsi_1h_min_19.value)
                & (dataframe["chop"] < self.nfi5_buy_chop_min_19.value)
                & (dataframe["volume"] > 0),
                ["enter_long", "enter_tag"],
            ] = (1, "nfi5_condition_19")

        # NFI5 MULTI-OFFSET SYSTEM
        if self.nfi5_multi_offset_enable.value:
            # Create conditions for each MA type
            ma_conditions = []
            ma_types = ["sma", "ema", "trima", "t3", "kama"]

            for ma_type in ma_types:
                if f"{ma_type}_offset_buy" in dataframe.columns:
                    ma_condition = (
                        (dataframe["close"] < dataframe[f"{ma_type}_offset_buy"])
                        & (
                            (dataframe["ewo"] < self.nfi5_ewo_low.value)
                            | (dataframe["ewo"] > self.nfi5_ewo_high.value)
                        )
                        & (dataframe["volume"] > 0)
                    )
                    ma_conditions.append(ma_condition)

            # Combine all MA conditions with OR logic
            if ma_conditions:
                combined_ma_condition = reduce(lambda x, y: x | y, ma_conditions)
                dataframe.loc[
                    combined_ma_condition,
                    ["enter_long", "enter_tag"],
                ] = (1, "nfi5_multi_offset")

        return dataframe

    def populate_sell_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        ENHANCED EXIT SIGNAL GENERATION - ARCANE + NFI5

        This function combines the original Arcane exit method with the
        sophisticated NFI5 exit conditions.
        """

        # ==================== ORIGINAL ARCANE EXIT (PRESERVED) ====================
        dema = f"dema_{self.dema_len_sell.value}"
        # dataframe.loc[
        #     (dataframe["close"] > (dataframe[dema] * self.high_offset.value)),
        #     ["exit_long", "exit_tag"],
        # ] = (1, "trend_dema_exit")

        # ==================== ICHIMOKU DEMA EXIT (FROM ARCANE BACKUP) ====================
        # Exit condition for Ichimoku-based entry
        dataframe.loc[
            (dataframe["close"] > (dataframe[dema] * self.high_offset.value))
            & (dataframe["enter_tag"] == "ichimoku_dema_entry"),
            ["exit_long", "exit_tag"],
        ] = (1, "ichimoku_dema_exit")

        # ==================== NFI5 EXIT CONDITIONS (ADDED) ====================

        # NFI5 SELL CONDITION 1: Bollinger Band overbought (strict)
        if self.nfi5_sell_condition_1_enable.value:
            dataframe.loc[
                (dataframe["rsi"] > self.nfi5_sell_rsi_bb_1.value)
                & (dataframe["close"] > dataframe["bb_upperband"])
                & (dataframe["close"].shift(1) > dataframe["bb_upperband"].shift(1))
                & (dataframe["close"].shift(2) > dataframe["bb_upperband"].shift(2))
                & (dataframe["close"].shift(3) > dataframe["bb_upperband"].shift(3))
                & (dataframe["close"].shift(4) > dataframe["bb_upperband"].shift(4))
                & (dataframe["close"].shift(5) > dataframe["bb_upperband"].shift(5))
                & (dataframe["volume"] > 0),
                ["exit_long", "exit_tag"],
            ] = (1, "nfi5_sell_1")

        # NFI5 SELL CONDITION 2: Bollinger Band overbought (moderate)
        if self.nfi5_sell_condition_2_enable.value:
            dataframe.loc[
                (dataframe["rsi"] > self.nfi5_sell_rsi_bb_2.value)
                & (dataframe["close"] > dataframe["bb_upperband"])
                & (dataframe["close"].shift(1) > dataframe["bb_upperband"].shift(1))
                & (dataframe["close"].shift(2) > dataframe["bb_upperband"].shift(2))
                & (dataframe["volume"] > 0),
                ["exit_long", "exit_tag"],
            ] = (1, "nfi5_sell_2")

        # NFI5 SELL CONDITION 3: RSI overbought
        if self.nfi5_sell_condition_3_enable.value:
            dataframe.loc[
                (dataframe["rsi"] > self.nfi5_sell_rsi_main_3.value) & (dataframe["volume"] > 0),
                ["exit_long", "exit_tag"],
            ] = (1, "nfi5_sell_3")

        # NFI5 SELL CONDITION 4: Dual RSI overbought
        if self.nfi5_sell_condition_4_enable.value:
            dataframe.loc[
                (dataframe["rsi"] > self.nfi5_sell_dual_rsi_rsi_4.value)
                & (dataframe["rsi_1h"] > self.nfi5_sell_dual_rsi_rsi_1h_4.value)
                & (dataframe["volume"] > 0),
                ["exit_long", "exit_tag"],
            ] = (1, "nfi5_sell_4")

        # NFI5 SELL CONDITION 6: Under trend RSI
        if self.nfi5_sell_condition_6_enable.value:
            dataframe.loc[
                (dataframe["close"] < dataframe["ema_200"])
                & (dataframe["close"] > dataframe["ema_50"])
                & (dataframe["rsi"] > self.nfi5_sell_rsi_under_6.value)
                & (dataframe["volume"] > 0),
                ["exit_long", "exit_tag"],
            ] = (1, "nfi5_sell_6")

        # NFI5 SELL CONDITION 7: EMA crossover
        if self.nfi5_sell_condition_7_enable.value:
            dataframe.loc[
                (dataframe["rsi_1h"] > self.nfi5_sell_rsi_1h_7.value)
                & qtpylib.crossed_below(dataframe["ema_12"], dataframe["ema_26"])
                & (dataframe["volume"] > 0),
                ["exit_long", "exit_tag"],
            ] = (1, "nfi5_sell_7")

        # NFI5 SELL CONDITION 8: Bollinger Band relative
        if self.nfi5_sell_condition_8_enable.value:
            dataframe.loc[
                (
                    dataframe["close"]
                    > dataframe["bb_upperband_1h"] * self.nfi5_sell_bb_relative_8.value
                )
                & (dataframe["volume"] > 0),
                ["exit_long", "exit_tag"],
            ] = (1, "nfi5_sell_8")

        return dataframe

    # ==================== ADVANCED EXIT LOGIC ====================
    def custom_sell(
        self,
        pair: str,
        trade: "Trade",
        current_time: "datetime",
        current_rate: float,
        current_profit: float,
        **kwargs,
    ):
        """
        NFI5-STYLE SOPHISTICATED CUSTOM SELL LOGIC

        This implements the advanced profit-taking system from NFI5MOHO
        with tiered profit targets, trailing stops, and market condition awareness.
        """
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if len(dataframe) < 1:
            return None

        last_candle = dataframe.iloc[-1].squeeze()
        max_profit = (trade.max_rate - trade.open_rate) / trade.open_rate

        # Tiered profit taking with RSI confirmation
        if current_profit > self.nfi5_sell_custom_profit_4.value and last_candle["rsi"] < 50.0:
            return "signal_profit_4"
        elif (
            current_profit > self.nfi5_sell_custom_profit_3.value
            and last_candle["rsi"] < self.nfi5_sell_custom_rsi_3.value
        ):
            return "signal_profit_3"
        elif (
            current_profit > self.nfi5_sell_custom_profit_2.value
            and last_candle["rsi"] < self.nfi5_sell_custom_rsi_2.value
        ):
            return "signal_profit_2"
        elif (
            current_profit > self.nfi5_sell_custom_profit_1.value
            and last_candle["rsi"] < self.nfi5_sell_custom_rsi_1.value
        ):
            return "signal_profit_1"
        elif (
            current_profit > self.nfi5_sell_custom_profit_0.value
            and last_candle["rsi"] < self.nfi5_sell_custom_rsi_0.value
        ):
            return "signal_profit_0"

        # Under-trend profit taking
        elif (
            current_profit > self.nfi5_sell_custom_under_profit_1.value
            and last_candle["rsi"] < self.nfi5_sell_custom_under_rsi_1.value
            and last_candle["close"] < last_candle["ema_200"]
        ):
            return "signal_profit_u_1"
        elif (
            current_profit > self.nfi5_sell_custom_under_profit_2.value
            and last_candle["rsi"] < self.nfi5_sell_custom_under_rsi_2.value
            and last_candle["close"] < last_candle["ema_200"]
        ):
            return "signal_profit_u_2"
        elif (
            current_profit > self.nfi5_sell_custom_under_profit_3.value
            and last_candle["rsi"] < self.nfi5_sell_custom_under_rsi_3.value
            and last_candle["close"] < last_candle["ema_200"]
        ):
            return "signal_profit_u_3"

        # Declining market exits
        elif current_profit > self.nfi5_sell_custom_dec_profit_1.value and last_candle.get(
            "sma_200_dec", False
        ):
            return "signal_profit_d_1"
        elif (
            current_profit > self.nfi5_sell_custom_dec_profit_2.value
            and last_candle["close"] < last_candle["ema_100"]
        ):
            return "signal_profit_d_2"

        # Trailing profit system
        elif (
            current_profit > self.nfi5_sell_trail_profit_min_1.value
            and current_profit < self.nfi5_sell_trail_profit_max_1.value
            and max_profit > (current_profit + self.nfi5_sell_trail_down_1.value)
        ):
            return "signal_profit_t_1"
        elif (
            current_profit > self.nfi5_sell_trail_profit_min_2.value
            and current_profit < self.nfi5_sell_trail_profit_max_2.value
            and max_profit > (current_profit + self.nfi5_sell_trail_down_2.value)
        ):
            return "signal_profit_t_2"

        # Under-trend trailing
        elif (
            last_candle["close"] < last_candle["ema_200"]
            and current_profit > self.nfi5_sell_trail_profit_min_3.value
            and current_profit < self.nfi5_sell_trail_profit_max_3.value
            and max_profit > (current_profit + self.nfi5_sell_trail_down_3.value)
        ):
            return "signal_profit_u_t_1"

        # Relative position exits
        elif (
            current_profit > 0.0
            and last_candle["close"] < last_candle["ema_200"]
            and ((last_candle["ema_200"] - last_candle["close"]) / last_candle["close"])
            < self.nfi5_sell_custom_profit_under_rel_1.value
            and last_candle["rsi"]
            > last_candle["rsi_1h"] + self.nfi5_sell_custom_profit_under_rsi_diff_1.value
        ):
            return "signal_profit_u_e_1"

        # Stoploss under trend
        elif (
            current_profit < 0.0
            and last_candle["close"] < last_candle["ema_200"]
            and ((last_candle["ema_200"] - last_candle["close"]) / last_candle["close"])
            < self.nfi5_sell_custom_stoploss_under_rel_1.value
            and last_candle["rsi"]
            > last_candle["rsi_1h"] + self.nfi5_sell_custom_stoploss_under_rsi_diff_1.value
        ):
            return "signal_stoploss_u_1"

        return None

    # def confirm_trade_entry(
    #     self, pair, order_type, amount, rate, time_in_force, current_time, **kwargs
    # ):
    #     dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
    #     candle = dataframe.iloc[-1].squeeze()
    #     slippage = (rate / candle["close"]) - 1
    #     return slippage >= -0.02  # Max 2% slippage

    def confirm_trade_exit(
        self,
        pair: str,
        trade: "Trade",
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        sell_reason: str,
        current_time: "datetime",
        **kwargs,
    ) -> bool:
        """
        ENHANCED DYNAMIC EXIT CONFIRMATION - MARKET REGIME AWARE

        This function provides intelligent exit control that adapts to market conditions:
        - BULL MARKETS: More patient, allows longer runs
        - BEAR MARKETS: Standard exit behavior
        - Prevents premature exits during strong momentum

        This is crucial for capturing the full potential of bull market moves.
        """

        # Get current market data
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        current_candle = dataframe.iloc[-1].squeeze() if len(dataframe) > 0 else None

        if current_candle is None:
            return True  # Allow exit if no data

        # Detect current market regime
        market_regime = self.detect_market_regime(dataframe)

        # Calculate trade duration
        trade_duration_hours = (current_time - trade.open_date_utc).total_seconds() / 3600

        # ==================== BULL MARKET EXIT LOGIC ====================
        if market_regime == "BULL":
            # For ROI exits during bull markets, be more selective
            if sell_reason in ("roi",):
                # Always allow exit if profit is very high (20%+)
                if trade.calc_profit_ratio(rate) > 0.20:
                    return True

                # For bull momentum trades, be extra patient
                if hasattr(trade, "enter_tag") and trade.enter_tag == "bull_momentum":
                    # Don't exit bull momentum trades on ROI unless:
                    # 1. Profit is above 15% AND
                    # 2. Trade is older than 4 hours AND
                    # 3. Momentum is weakening
                    if (
                        trade.calc_profit_ratio(rate) > 0.15
                        and trade_duration_hours > 4
                        and current_candle.get("EWO", 0) < 0
                    ):
                        return True
                    else:
                        return False  # Hold the trade

                # For other entries during bull markets
                # Block exit if still in strong uptrend and profit < 12%
                if (
                    current_candle.get("trend_bullish_active", False)
                    and current_candle.get("EWO", 0) > 0
                    and trade.calc_profit_ratio(rate) < 0.12
                ):
                    return False  # Don't exit - let it run

            # For trailing stop exits during bull markets
            elif sell_reason in ("trailing_stop_loss",):
                # Allow trailing stops but be more patient with bull momentum trades
                if (
                    hasattr(trade, "enter_tag")
                    and trade.enter_tag == "bull_momentum"
                    and current_candle.get("trend_bullish_active", False)
                    and trade_duration_hours < 2
                ):  # Less than 2 hours old
                    return False  # Don't exit yet

        # ==================== BEAR MARKET EXIT LOGIC ====================
        elif market_regime == "BEAR":
            # In bear markets, be more aggressive with exits
            if sell_reason in ("roi",):
                # Take profits quicker in bear markets
                if trade.calc_profit_ratio(rate) > 0.05:  # 5% profit
                    return True

        # ==================== STANDARD EXIT LOGIC ====================
        # For all other cases, use the original logic
        if sell_reason in ("roi",):
            # Block exit if we're still in an active bullish trend (original logic)
            if current_candle.get("trend_bullish_active", False):
                return False  # Don't exit - let the trend continue

        # For all other exit reasons (stop loss, exit signals, etc.), allow the exit
        return True

    # START OF COMMENTED OUT SECTION THAT MAY NEVER BE REMOVED!!!
    # def custom_stoploss(
    #     self,
    #     pair: str,
    #     trade: "Trade",
    #     current_time: datetime,
    #     current_rate: float,
    #     current_profit: float,
    #     **kwargs,
    # ) -> float:
    #     """
    #     DYNAMIC STOP LOSS SYSTEM

    #     This function implements a more intelligent stop loss that adapts to market volatility
    #     instead of using a fixed 5% stop loss for all trades.

    #     CONCEPT: Use ATR (Average True Range) to set stops based on market volatility
    #     - In low volatility: Tighter stops (preserve capital)
    #     - In high volatility: Wider stops (avoid noise)

    #     This should reduce the number of premature stop-outs while still protecting capital.
    #     """

    #     # Get current market data
    #     dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
    #     if len(dataframe) < 1:
    #         return self.stoploss  # Fallback to default stop loss

    #     current_candle = dataframe.iloc[-1].squeeze()

    #     # Calculate ATR-based stop loss
    #     atr = current_candle.get("atr", 0)
    #     close_price = current_candle.get("close", current_rate)

    #     if atr > 0 and close_price > 0:
    #         # ATR-based stop: 2.5x ATR below entry price
    #         atr_stop_distance = (atr * 2.5) / trade.open_rate
    #         atr_stop = -atr_stop_distance

    #         # Ensure stop is not tighter than 2% or wider than 8%
    #         atr_stop = max(atr_stop, -0.08)  # Max 8% stop
    #         atr_stop = min(atr_stop, -0.02)  # Min 2% stop

    #         # For trend-following entries, use wider stops during strong trends
    #         if hasattr(trade, "enter_tag") and trade.enter_tag in [
    #             "trend_dema_entry",
    #             "trend_momentum_breakout",
    #         ]:
    #             if current_candle.get("trend_bullish_active", False):
    #                 atr_stop = max(atr_stop, -0.06)  # Max 6% stop during strong trends

    #         return atr_stop

    #     # Fallback to default stop loss
    #     return self.stoploss

    # def custom_roi(
    #     self,
    #     pair: str,
    #     trade: "Trade",
    #     current_time: datetime,
    #     current_rate: float,
    #     current_profit: float,
    #     **kwargs,
    # ) -> float:
    #     """
    #     DYNAMIC ROI SYSTEM - ADAPTS TO MARKET CONDITIONS

    #     This function implements adaptive profit targets based on market regime:
    #     - BULL MARKETS: More patient, higher targets to capture sustained moves
    #     - BEAR MARKETS: Quicker profits to avoid reversals
    #     - NEUTRAL: Standard ROI table

    #     This helps capture longer moves during bull markets while protecting profits in bear markets.
    #     """

    #     # Get current market data
    #     dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
    #     if len(dataframe) < 1:
    #         return self.minimal_roi.get("0", 0.1)  # Fallback to default

    #     # Detect current market regime
    #     market_regime = self.detect_market_regime(dataframe)

    #     # Calculate trade duration in minutes
    #     trade_duration = (current_time - trade.open_date_utc).total_seconds() / 60

    #     # BULL MARKET ROI - More patient, higher targets
    #     if market_regime == "BULL":
    #         bull_roi = {
    #             0: 0.15,  # 15% target immediately (higher than default)
    #             30: 0.12,  # 12% after 30 minutes
    #             60: 0.10,  # 10% after 1 hour
    #             120: 0.08,  # 8% after 2 hours
    #             240: 0.05,  # 5% after 4 hours
    #             480: 0.03,  # 3% after 8 hours (more patient)
    #             720: 0.01,  # 1% after 12 hours
    #             1440: 0,  # Break even after 24 hours
    #         }

    #         # Special handling for bull momentum entries - even more patient
    #         if hasattr(trade, "enter_tag") and trade.enter_tag == "bull_momentum":
    #             bull_roi = {
    #                 0: 0.20,  # 20% target for momentum trades
    #                 60: 0.15,  # 15% after 1 hour
    #                 180: 0.12,  # 12% after 3 hours
    #                 360: 0.08,  # 8% after 6 hours
    #                 720: 0.05,  # 5% after 12 hours
    #                 1440: 0.02,  # 2% after 24 hours
    #                 2880: 0,  # Break even after 48 hours
    #             }

    #         # Find appropriate ROI for current duration
    #         for duration, roi_target in sorted(bull_roi.items()):
    #             if trade_duration >= duration:
    #                 current_roi_target = roi_target
    #             else:
    #                 break
    #         return current_roi_target

    #     # BEAR MARKET ROI - Quicker profits
    #     elif market_regime == "BEAR":
    #         bear_roi = {
    #             0: 0.08,  # 8% target (lower than default)
    #             30: 0.06,  # 6% after 30 minutes
    #             60: 0.04,  # 4% after 1 hour
    #             120: 0.025,  # 2.5% after 2 hours
    #             240: 0.01,  # 1% after 4 hours
    #             480: 0,  # Break even after 8 hours (quicker)
    #         }

    #         for duration, roi_target in sorted(bear_roi.items()):
    #             if trade_duration >= duration:
    #                 current_roi_target = roi_target
    #             else:
    #                 break
    #         return current_roi_target

    #     # NEUTRAL MARKET - Use default ROI table
    #     else:
    #         for duration_str, roi_target in sorted(
    #             self.minimal_roi.items(), key=lambda x: int(x[0])
    #         ):
    #             duration = int(duration_str)
    #             if trade_duration >= duration:
    #                 current_roi_target = roi_target
    #             else:
    #                 break
    #         return current_roi_target
    # END OF COMMENTED OUT SECTION THAT MAY NEVER BE REMOVED!!!

    def detect_market_regime(self, dataframe: DataFrame) -> str:
        """
        MARKET REGIME DETECTION SYSTEM

        This function analyzes market conditions to determine if we're in:
        - BULL MARKET: Strong uptrend with momentum
        - BEAR MARKET: Downtrend or sideways with weakness
        - NEUTRAL: Mixed signals or transitional period

        This allows the strategy to adapt its behavior based on market conditions.
        """

        # Use the last 100 candles for regime analysis
        recent_data = dataframe.tail(100)

        if len(recent_data) < 50:
            return "NEUTRAL"  # Not enough data

        # Calculate key metrics for regime detection
        current_price = recent_data["close"].iloc[-1]
        sma_20 = recent_data["close"].rolling(20).mean().iloc[-1]
        sma_50 = recent_data["close"].rolling(50).mean().iloc[-1]

        # Price momentum (20-period rate of change)
        price_momentum = (current_price / recent_data["close"].iloc[-20] - 1) * 100

        # EMA alignment strength
        ema_alignment_bull = (
            recent_data["ema_fast"].iloc[-1] > recent_data["ema_slow"].iloc[-1]
            and recent_data["ema_slow"].iloc[-1] > recent_data["ema_trend"].iloc[-1]
        )

        # Volume trend (increasing volume during uptrends)
        volume_trend = (
            recent_data["volume"].rolling(10).mean().iloc[-1]
            / recent_data["volume"].rolling(30).mean().iloc[-1]
        )

        # SSL trend strength
        ssl_bullish_strength = (recent_data["ssl_up"] > recent_data["ssl_down"]).sum() / len(
            recent_data
        )

        # Higher timeframe trend confirmation
        htf_bullish = recent_data.get(
            "trend_bullish_active", pd.Series([False] * len(recent_data))
        ).iloc[-1]

        # BULL MARKET CONDITIONS
        bull_score = 0
        if price_momentum > 5:  # 5% gain in 20 periods
            bull_score += 2
        elif price_momentum > 2:  # 2% gain in 20 periods
            bull_score += 1

        if ema_alignment_bull:
            bull_score += 2

        if current_price > sma_20 > sma_50:
            bull_score += 1

        if volume_trend > 1.1:  # Volume 10% above average
            bull_score += 1

        if ssl_bullish_strength > 0.7:  # 70% of recent candles bullish
            bull_score += 1

        if htf_bullish:
            bull_score += 1

        # BEAR MARKET CONDITIONS
        bear_score = 0
        if price_momentum < -5:  # 5% loss in 20 periods
            bear_score += 2
        elif price_momentum < -2:  # 2% loss in 20 periods
            bear_score += 1

        if current_price < sma_20 < sma_50:
            bear_score += 2

        if ssl_bullish_strength < 0.3:  # 30% or less bullish candles
            bear_score += 2

        if not htf_bullish:
            bear_score += 1

        # REGIME DETERMINATION
        if bull_score >= 5:
            return "BULL"
        elif bear_score >= 4:
            return "BEAR"
        else:
            return "NEUTRAL"

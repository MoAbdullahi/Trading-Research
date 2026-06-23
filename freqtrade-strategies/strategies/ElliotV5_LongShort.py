"""
ElliotV5_LongShort
==================
Short-enabled futures variant of ElliotV5_SMA_ninja.

The original strategy is a long-only mean-reversion system: it BUYS dips that
poke below an EMA (in a strong up-trend per the Elliot Wave Oscillator, or when
deeply oversold) and SELLS when price rallies back above a slower EMA.

This version keeps that long logic and adds a SYMMETRIC short side:
  - ENTER SHORT when price spikes ABOVE the EMA in a strong down-trend
    (EWO strongly negative) or when strongly overbought.
  - EXIT SHORT (cover) when price falls back below the lower EMA.

Goal: test whether allowing the strategy to trade the DOWNSIDE adds a real
edge over the long-only spot/futures versions, especially given the ~26%
market drop over the backtest window.

can_short = True, so it must run in futures mode. Leverage via FT_LEVERAGE
(default 1x for a fair like-for-like comparison against spot).
"""
import os
from functools import reduce

import numpy as np  # noqa: F401
from pandas import DataFrame
import talib.abstract as ta

from freqtrade.strategy import IStrategy, DecimalParameter, IntParameter


def EWO(dataframe, ema_length=5, ema2_length=35):
    df = dataframe.copy()
    ema1 = ta.SMA(df, timeperiod=ema_length)
    ema2 = ta.SMA(df, timeperiod=ema2_length)
    return (ema1 - ema2) / df['close'] * 100


class ElliotV5_LongShort(IStrategy):
    INTERFACE_VERSION = 3

    # Futures, both directions
    can_short: bool = True

    minimal_roi = {"0": 0.215, "40": 0.132, "87": 0.086, "201": 0.03}
    stoploss = -0.189

    base_nb_candles_buy = IntParameter(5, 80, default=17, space='buy', optimize=True)
    base_nb_candles_sell = IntParameter(5, 80, default=49, space='sell', optimize=True)
    low_offset = DecimalParameter(0.9, 0.99, default=0.978, space='buy', optimize=True)
    high_offset = DecimalParameter(0.99, 1.1, default=1.019, space='sell', optimize=True)

    fast_ewo = 50
    slow_ewo = 200
    ewo_low = DecimalParameter(-20.0, -8.0, default=-17.457, space='buy', optimize=True)
    ewo_high = DecimalParameter(2.0, 12.0, default=3.34, space='buy', optimize=True)
    rsi_buy = IntParameter(30, 70, default=65, space='buy', optimize=True)

    trailing_stop = True
    trailing_stop_positive = 0.005
    trailing_stop_positive_offset = 0.03
    trailing_only_offset_is_reached = True

    use_exit_signal = True
    exit_profit_only = False
    exit_profit_offset = 0.01
    ignore_roi_if_entry_signal = True

    timeframe = '5m'
    process_only_new_candles = True
    startup_candle_count = 400

    use_custom_stoploss = False

    def leverage(self, pair, current_time, current_rate, proposed_leverage,
                 max_leverage, side, **kwargs) -> float:
        try:
            lev = float(os.environ.get("FT_LEVERAGE", "1"))
        except (TypeError, ValueError):
            lev = 1.0
        return max(1.0, min(lev, max_leverage))

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        for val in self.base_nb_candles_buy.range:
            dataframe[f'ma_buy_{val}'] = ta.EMA(dataframe, timeperiod=val)
        for val in self.base_nb_candles_sell.range:
            dataframe[f'ma_sell_{val}'] = ta.EMA(dataframe, timeperiod=val)
        dataframe['EWO'] = EWO(dataframe, self.fast_ewo, self.slow_ewo)
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        ma_buy = dataframe[f'ma_buy_{self.base_nb_candles_buy.value}']
        ma_sell = dataframe[f'ma_sell_{self.base_nb_candles_sell.value}']

        # ---- LONG: buy dips below EMA (original logic) ----
        long_conditions = [
            (dataframe['close'] < (ma_buy * self.low_offset.value)) &
            (dataframe['EWO'] > self.ewo_high.value) &
            (dataframe['rsi'] < self.rsi_buy.value) &
            (dataframe['volume'] > 0),

            (dataframe['close'] < (ma_buy * self.low_offset.value)) &
            (dataframe['EWO'] < self.ewo_low.value) &
            (dataframe['volume'] > 0),
        ]
        dataframe.loc[reduce(lambda x, y: x | y, long_conditions), 'enter_long'] = 1

        # ---- SHORT: sell rallies above EMA (mirror image) ----
        short_conditions = [
            (dataframe['close'] > (ma_sell * self.high_offset.value)) &
            (dataframe['EWO'] < -self.ewo_high.value) &
            (dataframe['rsi'] > (100 - self.rsi_buy.value)) &
            (dataframe['volume'] > 0),

            (dataframe['close'] > (ma_sell * self.high_offset.value)) &
            (dataframe['EWO'] > -self.ewo_low.value) &
            (dataframe['volume'] > 0),
        ]
        dataframe.loc[reduce(lambda x, y: x | y, short_conditions), 'enter_short'] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        ma_buy = dataframe[f'ma_buy_{self.base_nb_candles_buy.value}']
        ma_sell = dataframe[f'ma_sell_{self.base_nb_candles_sell.value}']

        # exit long when price rallies above slow EMA (original)
        dataframe.loc[
            (dataframe['close'] > (ma_sell * self.high_offset.value)) &
            (dataframe['volume'] > 0),
            'exit_long'] = 1

        # exit short (cover) when price drops below fast EMA (mirror)
        dataframe.loc[
            (dataframe['close'] < (ma_buy * self.low_offset.value)) &
            (dataframe['volume'] > 0),
            'exit_short'] = 1
        return dataframe

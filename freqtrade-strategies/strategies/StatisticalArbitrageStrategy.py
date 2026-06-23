# statistical_arbitrage_strategy.py
import logging
from freqtrade.strategy.interface import IStrategy
from freqtrade.strategy import DecimalParameter
from pandas import DataFrame
import requests
from pycoingecko import CoinGeckoAPI

logger = logging.getLogger(__name__)

class StatisticalArbitrageStrategy(IStrategy):
    # Optimize parameters
    buy_threshold = DecimalParameter(0.01, 0.1, default=0.05, space="buy", optimize=True)
    sell_threshold = DecimalParameter(0.01, 0.1, default=0.05, space="sell", optimize=True)
    minimal_roi = {
        "0": 0.1,
        "30": 0.05,
        "60": 0.01
    }
    stoploss = -0.1
    timeframe = "5m"

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        # Fetch top 50 pairs by market cap
        self.top_pairs = self.get_top_50_pairs()

    def get_top_50_pairs(self):
        cg = CoinGeckoAPI()
        markets = cg.get_coins_markets(vs_currency="usd", order="market_cap_desc", per_page=50, page=1)
        top_pairs = [f"{coin['symbol'].upper()}/USDT" for coin in markets if coin['symbol'] != 'usdt']
        return top_pairs

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Fetch on-chain data (example: Bitcoin exchange inflows)
        btc_inflows = self.get_btc_exchange_inflows()
        dataframe['btc_inflows'] = btc_inflows

        # Fetch social media sentiment (example: Twitter mentions)
        sentiment_score = self.get_social_sentiment(metadata['pair'])
        dataframe['sentiment_score'] = sentiment_score

        return dataframe

    def populate_buy_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe['btc_inflows'] < self.buy_threshold.value) &  # Low exchange inflows
                (dataframe['sentiment_score'] > 0.7)  # Positive sentiment
            ),
            'buy'] = 1
        return dataframe

    def populate_sell_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe['btc_inflows'] > self.sell_threshold.value) |  # High exchange inflows
                (dataframe['sentiment_score'] < 0.3)  # Negative sentiment
            ),
            'sell'] = 1
        return dataframe

    def get_btc_exchange_inflows(self) -> float:
        # Example: Fetch Bitcoin exchange inflows from Glassnode or similar API
        url = "https://api.glassnode.com/v1/metrics/transactions/transfers_volume_exchanges_in"
        params = {
            "api_key": "your_glassnode_api_key",
            "asset": "BTC",
            "interval": "24h"
        }
        response = requests.get(url, params=params)
        if response.status_code == 200:
            return float(response.json()[-1]['v'])  # Latest inflow value
        return 0.0

    def get_social_sentiment(self, pair: str) -> float:
        # Example: Fetch sentiment score from social media APIs (e.g., Lunarcrush, TheTIE)
        url = "https://api.lunarcrush.com/v2"
        params = {
            "data": "feeds",
            "symbol": pair.split('/')[0],
            "interval": "day",
            "key": "your_lunarcrush_api_key"
        }
        response = requests.get(url, params=params)
        if response.status_code == 200:
            return float(response.json()['data'][0]['sentiment_score'])  # Latest sentiment score
        return 0.5  # Neutral sentiment if API fails
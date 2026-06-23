"""Typed configuration loaded from environment / .env.

Secrets never live in code. ALPACA_USE_PAPER toggles paper vs live so the same
binary can be promoted through environments without code changes.
"""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Alpaca (US equities, primary venue for phase 1) ---
    alpaca_api_key: str = Field(default="", alias="ALPACA_API_KEY")
    alpaca_secret_key: str = Field(default="", alias="ALPACA_SECRET_KEY")
    alpaca_use_paper: bool = Field(default=True, alias="ALPACA_USE_PAPER")

    # --- OANDA (forex + gold) — phase 4 ---
    oanda_api_token: str = Field(default="", alias="OANDA_API_TOKEN")
    oanda_account_id: str = Field(default="", alias="OANDA_ACCOUNT_ID")
    oanda_environment: str = Field(default="practice", alias="OANDA_ENVIRONMENT")

    # --- Crypto exchange via CCXT — phase 4 ---
    crypto_exchange: str = Field(default="binance", alias="CRYPTO_EXCHANGE")
    crypto_api_key: str = Field(default="", alias="CRYPTO_API_KEY")
    crypto_secret_key: str = Field(default="", alias="CRYPTO_SECRET_KEY")

    # --- LLM providers ---
    reasoning_model: str = Field(default="claude-opus-4-8", alias="REASONING_MODEL")
    fast_model: str = Field(default="claude-haiku-4-5-20251001", alias="FAST_MODEL")
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")

    # --- Persistence ---
    postgres_dsn: str = Field(
        default="postgresql://localhost:5432/trading", alias="POSTGRES_DSN"
    )

    # --- Global risk parameters (the gateway reads these) ---
    max_per_trade_risk_pct: float = Field(default=2.0, alias="MAX_PER_TRADE_RISK_PCT")
    min_reward_to_risk: float = Field(default=2.0, alias="MIN_REWARD_TO_RISK")
    max_concurrent_exposure_pct: float = Field(default=30.0, alias="MAX_CONCURRENT_EXPOSURE_PCT")
    max_account_drawdown_pct: float = Field(default=6.0, alias="MAX_ACCOUNT_DRAWDOWN_PCT")
    consensus_threshold: int = Field(default=3, alias="CONSENSUS_THRESHOLD")
    orchestrator_max_turns: int = Field(default=4, alias="ORCHESTRATOR_MAX_TURNS")


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings

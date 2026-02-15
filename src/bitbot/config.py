"""Type-safe configuration loaded from YAML + .env secrets."""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ExchangeConfig(BaseModel):
    name: str = "binance"
    trading_pair: str = "BTCUSDT"
    mode: str = "paper"


class StrategyConfig(BaseModel):
    check_interval_seconds: int = 60
    primary_timeframe: str = "15m"
    trend_timeframe: str = "4h"
    indicator_period: int = 200


class SignalsConfig(BaseModel):
    dip_mild_pct: float = 3.0
    dip_moderate_pct: float = 5.0
    dip_major_pct: float = 10.0
    rsi_oversold: int = 30
    rsi_extremely_oversold: int = 20
    rsi_period: int = 14
    ma_short_period: int = 20
    ma_long_period: int = 200
    bollinger_period: int = 20
    bollinger_std: float = 2.0
    volume_decline_threshold: float = 0.8


class ScoringConfig(BaseModel):
    buy_threshold: int = 60
    small_buy_range: list[int] = Field(default=[60, 74])
    medium_buy_range: list[int] = Field(default=[75, 84])
    large_buy_range: list[int] = Field(default=[85, 100])
    small_buy_pct: float = 0.05
    medium_buy_pct: float = 0.10
    large_buy_pct: float = 0.20


class DCAConfig(BaseModel):
    tranches: int = 3
    min_interval_minutes: int = 10
    max_interval_minutes: int = 60


class SellingConfig(BaseModel):
    profit_target_pct: float = 5.0
    trailing_stop_pct: float = 1.0
    time_exit_days: int = 7


class RiskConfig(BaseModel):
    max_position_pct: float = 0.20
    max_total_exposure_pct: float = 0.70
    stop_loss_pct: float = 5.0
    max_daily_loss_pct: float = 3.0
    max_drawdown_pct: float = 10.0
    cooldown_after_stoploss_hours: int = 4
    sentiment_block_hours: int = 12


class LLMConfig(BaseModel):
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-5-20250929"
    trigger_threshold: int = 40
    max_calls_per_hour: int = 10


class NewsConfig(BaseModel):
    provider: str = "cryptopanic"
    max_headlines: int = 10


class FeesConfig(BaseModel):
    maker_pct: float = 0.10
    taker_pct: float = 0.10
    estimated_slippage_pct: float = 0.05


class CapitalConfig(BaseModel):
    initial_usdt: float = 1000.0


class Settings(BaseSettings):
    """Root settings — secrets from .env, everything else from YAML."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Secrets (from .env)
    binance_api_key: str = ""
    binance_api_secret: str = ""
    anthropic_api_key: str = ""
    cryptopanic_api_key: str = ""

    # Config sections (from YAML)
    exchange: ExchangeConfig = ExchangeConfig()
    strategy: StrategyConfig = StrategyConfig()
    signals: SignalsConfig = SignalsConfig()
    scoring: ScoringConfig = ScoringConfig()
    dca: DCAConfig = DCAConfig()
    selling: SellingConfig = SellingConfig()
    risk: RiskConfig = RiskConfig()
    llm: LLMConfig = LLMConfig()
    news: NewsConfig = NewsConfig()
    fees: FeesConfig = FeesConfig()
    capital: CapitalConfig = CapitalConfig()


def load_settings(config_path: Path | None = None) -> Settings:
    """Load settings from YAML config file with .env overlay for secrets.

    Args:
        config_path: Path to settings.yaml. If None, uses config/settings.yaml.

    Returns:
        Fully validated Settings instance.
    """
    if config_path is None:
        config_path = Path("config/settings.yaml")

    yaml_data: dict = {}
    if config_path.exists():
        with open(config_path) as f:
            yaml_data = yaml.safe_load(f) or {}

    return Settings(**yaml_data)

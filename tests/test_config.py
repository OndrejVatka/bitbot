"""Tests for the config system."""

import tempfile
from pathlib import Path

import yaml

from bitbot.config import Settings, load_settings


class TestLoadSettings:
    """Test YAML + .env config loading."""

    def test_defaults_without_yaml(self) -> None:
        """Settings should have sane defaults even without a YAML file."""
        settings = load_settings(Path("/nonexistent/settings.yaml"))

        assert settings.exchange.trading_pair == "BTCUSDT"
        assert settings.exchange.mode == "paper"
        assert settings.strategy.primary_timeframe == "15m"
        assert settings.strategy.trend_timeframe == "4h"
        assert settings.selling.profit_target_pct == 5.0
        assert settings.risk.stop_loss_pct == 5.0
        assert settings.llm.model == "claude-sonnet-4-5-20250929"

    def test_loads_from_yaml(self, tmp_path: Path) -> None:
        """Settings should load values from a YAML file."""
        config = {
            "exchange": {"trading_pair": "ETHUSDT", "mode": "live"},
            "capital": {"initial_usdt": 500.0},
            "signals": {"rsi_period": 21},
        }
        yaml_path = tmp_path / "settings.yaml"
        yaml_path.write_text(yaml.dump(config))

        settings = load_settings(yaml_path)

        assert settings.exchange.trading_pair == "ETHUSDT"
        assert settings.exchange.mode == "live"
        assert settings.capital.initial_usdt == 500.0
        assert settings.signals.rsi_period == 21
        # Non-overridden values keep defaults
        assert settings.strategy.primary_timeframe == "15m"

    def test_real_config_file(self) -> None:
        """The actual config/settings.yaml should load without errors."""
        settings = load_settings(Path("config/settings.yaml"))

        assert settings.exchange.trading_pair == "BTCUSDT"
        assert settings.strategy.primary_timeframe == "15m"
        assert settings.scoring.buy_threshold == 60

    def test_scoring_ranges(self) -> None:
        """Scoring buy ranges should be properly structured."""
        settings = load_settings(Path("/nonexistent.yaml"))

        assert settings.scoring.small_buy_range == [60, 74]
        assert settings.scoring.medium_buy_range == [75, 84]
        assert settings.scoring.large_buy_range == [85, 100]

    def test_empty_yaml_file(self, tmp_path: Path) -> None:
        """An empty YAML file should still produce valid defaults."""
        yaml_path = tmp_path / "empty.yaml"
        yaml_path.write_text("")

        settings = load_settings(yaml_path)
        assert settings.exchange.trading_pair == "BTCUSDT"

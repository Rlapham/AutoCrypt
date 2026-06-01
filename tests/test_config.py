"""Smoke tests for config + package import (no network, no secrets)."""

from __future__ import annotations

from autocrypt import __version__
from autocrypt.config import AppEnv, Settings


def test_version() -> None:
    assert __version__ == "0.1.0"


def test_default_settings_safe() -> None:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    # Default runtime must never be `live` (live is a RED transition).
    assert s.app_env == AppEnv.backtest
    # DuckDB url is auto-derived and points under the data dir.
    assert s.db_url.startswith("duckdb:///")
    assert s.duckdb_path.name == "autocrypt.duckdb"


def test_has_reports_unset_credentials() -> None:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.has("bitquery_api_key") is False

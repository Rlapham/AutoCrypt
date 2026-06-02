"""Typed configuration loaded from environment variables (and `.env`).

Secrets live ONLY in the environment / `.env` (git-ignored) and are read here.
Never hardcode keys; never log secret values. See CLAUDE.md §3 (RED) and §4.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root = two levels up from this file (src/autocrypt/config.py -> repo root).
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = REPO_ROOT / "data"


class AppEnv(str, Enum):
    """Runtime mode. `live` is a RED transition and is never set autonomously."""

    backtest = "backtest"
    paper = "paper"
    live = "live"


class Settings(BaseSettings):
    """Process-wide settings. Instantiate via `get_settings()`."""

    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Runtime ──
    app_env: AppEnv = AppEnv.backtest
    log_level: str = "INFO"

    # ── Provider API keys (read-only; optional — free tiers may not need all) ──
    bitquery_api_key: SecretStr | None = None
    flipside_api_key: SecretStr | None = None  # free Community tier (Data API)
    dune_api_key: SecretStr | None = None  # free tier (2,500 credits/mo) — cross-check
    birdeye_api_key: SecretStr | None = None
    dexpaprika_api_key: SecretStr | None = None
    geckoterminal_api_key: SecretStr | None = None
    coingecko_api_key: SecretStr | None = None
    nansen_api_key: SecretStr | None = None
    arkham_api_key: SecretStr | None = None

    # ── Solana RPC (read-only for Phases 1-4) ──
    solana_rpc_url: str | None = None
    solana_rpc_api_key: SecretStr | None = None

    # ── Local data store ──
    data_dir: Path = DEFAULT_DATA_DIR
    db_url: str = Field(default="")  # filled in validator if empty

    def model_post_init(self, __context: object) -> None:
        # Default DuckDB path lives under the data dir unless overridden.
        if not self.db_url:
            object.__setattr__(self, "db_url", f"duckdb:///{self.data_dir / 'autocrypt.duckdb'}")

    @property
    def duckdb_path(self) -> Path:
        """Filesystem path to the DuckDB file (parsed from db_url)."""
        prefix = "duckdb:///"
        if self.db_url.startswith(prefix):
            return Path(self.db_url[len(prefix) :])
        return self.data_dir / "autocrypt.duckdb"

    def has(self, key_attr: str) -> bool:
        """True if the named SecretStr/str credential is set and non-empty."""
        val = getattr(self, key_attr, None)
        if isinstance(val, SecretStr):
            return bool(val.get_secret_value())
        return bool(val)


_settings: Settings | None = None


def get_settings(reload: bool = False) -> Settings:
    """Return the process-wide Settings singleton (lazily constructed)."""
    global _settings
    if _settings is None or reload:
        _settings = Settings()
    return _settings

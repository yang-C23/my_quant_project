from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables and .env."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    data_root: Path = Path("~/quant_data")
    tdx_home: Path = Path("/tdx")
    tdx_zip: Path | None = None
    pg_dsn: str = Field(default="", validation_alias="QUANT_DB_DSN")
    etl_workers: int = 20

    @field_validator("data_root", "tdx_home", "tdx_zip", mode="after")
    @classmethod
    def expand_path(cls, value: Path | None) -> Path | None:
        """Expand user home markers without requiring the path to exist."""
        return value.expanduser() if value is not None else None

    @property
    def mirror_dir(self) -> Path:
        """Directory containing the local TDX mirror."""
        return self.data_root / "tdx_mirror"

    @property
    def staging_dir(self) -> Path:
        """Directory containing Parquet staging data."""
        return self.active_data_dir / "staging"

    @property
    def active_data_dir(self) -> Path:
        """Resolve the atomic snapshot pointer, retaining legacy compatibility."""
        from quant.data.snapshots import SnapshotStore

        store = SnapshotStore(self.data_root)
        current = store.current()
        return store.path(current) if current else self.data_root

    @property
    def qlib_cn_daily_uri(self) -> Path:
        """Directory containing qlib China daily data."""
        return self.active_data_dir / "qlib" / "cn_daily"

    @property
    def qlib_us_daily_uri(self) -> Path:
        """Directory containing qlib US daily data."""
        return self.data_root / "qlib" / "us_daily"

    @property
    def mlruns_uri(self) -> Path:
        """Directory containing local mlflow tracking runs."""
        return self.data_root / "mlruns"

    @property
    def archive_dir(self) -> Path:
        """Directory containing archived exports and dumps."""
        return self.data_root / "archive"


@lru_cache
def get_settings() -> Settings:
    """Return cached runtime settings."""
    return Settings()


def load_config(config_path: str | Path) -> dict:
    """Load a YAML or JSON config file as a mapping."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")

    suffix = path.suffix.lower()
    content = path.read_text(encoding="utf-8")

    if suffix in {".yml", ".yaml"}:
        data = yaml.safe_load(content) or {}
    elif suffix == ".json":
        data = json.loads(content) if content.strip() else {}
    else:
        raise ValueError("Config must be .yaml, .yml, or .json")

    if not isinstance(data, dict):
        raise ValueError("Config root must be a mapping object")
    return data

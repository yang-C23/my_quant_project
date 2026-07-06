from __future__ import annotations

from pathlib import Path

from quant.config import Settings, get_settings


def teardown_function() -> None:
    get_settings.cache_clear()


def test_settings_uses_environment_overrides(monkeypatch, tmp_path: Path) -> None:
    data_root = tmp_path / "quant_data"
    tdx_home = tmp_path / "tdx"

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATA_ROOT", str(data_root))
    monkeypatch.setenv("TDX_HOME", str(tdx_home))
    monkeypatch.setenv("QUANT_DB_DSN", "dbname=test_quant")
    monkeypatch.setenv("ETL_WORKERS", "7")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.data_root == data_root
    assert settings.tdx_home == tdx_home
    assert settings.pg_dsn == "dbname=test_quant"
    assert settings.etl_workers == 7
    assert settings.mirror_dir == data_root / "tdx_mirror"
    assert settings.staging_dir == data_root / "staging"
    assert settings.qlib_cn_daily_uri == data_root / "qlib" / "cn_daily"
    assert settings.qlib_us_daily_uri == data_root / "qlib" / "us_daily"
    assert settings.archive_dir == data_root / "archive"


def test_settings_defaults_work_without_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATA_ROOT", raising=False)
    monkeypatch.delenv("TDX_HOME", raising=False)
    monkeypatch.delenv("QUANT_DB_DSN", raising=False)
    monkeypatch.delenv("ETL_WORKERS", raising=False)

    settings = Settings()

    assert settings.data_root == Path("~/quant_data").expanduser()
    assert settings.tdx_home == Path("/tdx")
    assert settings.pg_dsn == ""
    assert settings.etl_workers == 20


def test_settings_expands_user_home(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("DATA_ROOT", "~/custom_quant_data")
    monkeypatch.setenv("TDX_HOME", "~/tdx_home")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.data_root == tmp_path / "custom_quant_data"
    assert settings.tdx_home == tmp_path / "tdx_home"

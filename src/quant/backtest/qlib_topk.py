"""Qlib TopkDropout baseline backtest runner."""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd

from quant.config import get_settings, load_config
from quant.data.api import get_ohlcv, init_qlib
from quant.data.symbols import to_qlib
from quant.indicators.amv import amv
from quant.research.amv_timing import build_variant_signal
from quant.signals.factors import compute_factor_frame, to_factor

BacktestKind = Literal["signal", "factor"]
RegimeKind = Literal["amv_immediate"]

EXPERIMENT_NAME = "topk_baseline"
REPORT_DIR = Path("backtest_results/backtest")
_REGIME_WARMUP_BDAYS = 200
_INDEX_NAMES = ["datetime", "instrument"]
_CONFIG_KEYS = {
    "name",
    "kind",
    "score",
    "start",
    "end",
    "universe",
    "topk",
    "n_drop",
    "benchmark",
    "exchange",
    "regime",
}
_UNIVERSE_KEYS = {"source", "exclude_boards", "at"}
_EXCHANGE_KEYS = {"open_cost", "close_cost", "min_cost", "limit_threshold"}
_REGIME_KEYS = {"kind", "index", "k", "buy_th", "sell_th"}


@dataclass(frozen=True)
class UniverseConfig:
    """Symbol universe loaded from staging metadata."""

    source: str = "list_symbols"
    exclude_boards: tuple[str, ...] = ("star", "b")
    at: str | None = None

    def label(self) -> str:
        """Return a stable, human-readable universe label."""
        excluded = ",".join(self.exclude_boards) if self.exclude_boards else "none"
        return f"{self.source}(exclude_boards={excluded}, at={self.at})"


@dataclass(frozen=True)
class ExchangeConfig:
    """Qlib exchange cost and limit parameters."""

    open_cost: float = 0.0005
    close_cost: float = 0.0015
    min_cost: float = 5.0
    limit_threshold: float = 0.095

    def to_kwargs(self) -> dict[str, float]:
        """Return kwargs accepted by qlib's Exchange constructor."""
        return {
            "open_cost": self.open_cost,
            "close_cost": self.close_cost,
            "min_cost": self.min_cost,
            "limit_threshold": self.limit_threshold,
        }


@dataclass(frozen=True)
class RegimeConfig:
    """Optional portfolio-level AMV timing overlay configuration."""

    kind: RegimeKind
    index: str
    k: float
    buy_th: float
    sell_th: float


@dataclass(frozen=True)
class TopkConfig:
    """Validated TopkDropout baseline configuration."""

    name: str
    kind: BacktestKind
    score: str
    start: str
    end: str
    universe: UniverseConfig = UniverseConfig()
    topk: int = 50
    n_drop: int = 5
    benchmark: str = "sh000001"
    exchange: ExchangeConfig = ExchangeConfig()
    regime: RegimeConfig | None = None


@dataclass(frozen=True)
class TopkResult:
    """Result paths and metrics from a TopkDropout qlib backtest."""

    metrics: dict[str, float]
    report_paths: dict[str, Path]
    mlflow_run_id: str


def _unknown_keys(raw: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError(f"unknown {label} config keys: {unknown}")


def _date_str(value: Any, field: str) -> str:
    if value is None:
        raise ValueError(f"{field} is required")
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _positive_int(value: Any, field: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"{field} must be positive")
    return parsed


def _float_value(value: Any, field: str) -> float:
    parsed = float(value)
    if not np.isfinite(parsed):
        raise ValueError(f"{field} must be finite")
    return parsed


def _required_value(raw: Mapping[str, Any], key: str, label: str) -> Any:
    value = raw.get(key)
    if value is None:
        raise ValueError(f"{label}.{key} is required")
    return value


def _parse_universe(raw: Any) -> UniverseConfig:
    if raw is None:
        return UniverseConfig()
    if isinstance(raw, str):
        if raw != "all":
            raise ValueError("universe string must be 'all'")
        return UniverseConfig()
    if not isinstance(raw, Mapping):
        raise ValueError("universe must be a mapping, 'all', or omitted")

    _unknown_keys(raw, _UNIVERSE_KEYS, "universe")
    source = str(raw.get("source", "list_symbols"))
    if source != "list_symbols":
        raise ValueError("only universe.source=list_symbols is supported")
    exclude_boards = tuple(str(item) for item in raw.get("exclude_boards", ("star", "b")))
    at_raw = raw.get("at")
    at = None if at_raw is None else _date_str(at_raw, "universe.at")
    return UniverseConfig(source=source, exclude_boards=exclude_boards, at=at)


def _parse_exchange(raw: Any) -> ExchangeConfig:
    if raw is None:
        return ExchangeConfig()
    if not isinstance(raw, Mapping):
        raise ValueError("exchange must be a mapping")

    _unknown_keys(raw, _EXCHANGE_KEYS, "exchange")
    default = ExchangeConfig()
    return ExchangeConfig(
        open_cost=_float_value(raw.get("open_cost", default.open_cost), "exchange.open_cost"),
        close_cost=_float_value(raw.get("close_cost", default.close_cost), "exchange.close_cost"),
        min_cost=_float_value(raw.get("min_cost", default.min_cost), "exchange.min_cost"),
        limit_threshold=_float_value(
            raw.get("limit_threshold", default.limit_threshold), "exchange.limit_threshold"
        ),
    )


def _parse_regime(raw: Any) -> RegimeConfig | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError("regime must be a mapping")

    _unknown_keys(raw, _REGIME_KEYS, "regime")
    kind = str(_required_value(raw, "kind", "regime")).strip()
    if kind != "amv_immediate":
        raise ValueError("only regime.kind=amv_immediate is supported")

    index = str(_required_value(raw, "index", "regime")).strip()
    if not index:
        raise ValueError("regime.index is required")

    return RegimeConfig(
        kind="amv_immediate",
        index=index,
        k=_float_value(_required_value(raw, "k", "regime"), "regime.k"),
        buy_th=_float_value(_required_value(raw, "buy_th", "regime"), "regime.buy_th"),
        sell_th=_float_value(_required_value(raw, "sell_th", "regime"), "regime.sell_th"),
    )


def parse_topk_config(raw: Mapping[str, Any]) -> TopkConfig:
    """Validate a raw mapping loaded from the Topk YAML config."""
    _unknown_keys(raw, _CONFIG_KEYS, "topk")

    name = str(raw.get("name") or "").strip()
    if not name:
        raise ValueError("name is required")

    kind = str(raw.get("kind") or "").strip()
    if kind not in {"signal", "factor"}:
        raise ValueError("kind must be 'signal' or 'factor'")
    parsed_kind: BacktestKind = "signal" if kind == "signal" else "factor"

    score = str(raw.get("score") or "").strip()
    if not score:
        raise ValueError("score is required")

    start = _date_str(raw.get("start"), "start")
    end = _date_str(raw.get("end"), "end")
    if pd.Timestamp(start) > pd.Timestamp(end):
        raise ValueError("start must be <= end")

    topk = _positive_int(raw.get("topk", 50), "topk")
    n_drop = _positive_int(raw.get("n_drop", 5), "n_drop")
    if n_drop > topk:
        raise ValueError("n_drop must be <= topk")

    benchmark = str(raw.get("benchmark", "sh000001")).strip()
    if not benchmark:
        raise ValueError("benchmark is required")

    return TopkConfig(
        name=name,
        kind=parsed_kind,
        score=score,
        start=start,
        end=end,
        universe=_parse_universe(raw.get("universe")),
        topk=topk,
        n_drop=n_drop,
        benchmark=benchmark,
        exchange=_parse_exchange(raw.get("exchange")),
        regime=_parse_regime(raw.get("regime")),
    )


def load_topk_config(config_path: str | Path) -> TopkConfig:
    """Load and validate a TopkDropout YAML or JSON config."""
    return parse_topk_config(load_config(config_path))


def resolve_universe(config: UniverseConfig) -> list[str]:
    """Resolve the configured all-market staging universe."""
    from quant.data.universe import list_symbols

    symbols = list_symbols(exclude_boards=set(config.exclude_boards), at=config.at)
    if not symbols:
        raise ValueError(f"universe resolved to zero symbols: {config.label()}")
    return symbols


def _empty_score(name: str) -> pd.Series:
    index = pd.MultiIndex.from_arrays(
        [pd.DatetimeIndex([], name="datetime"), pd.Index([], name="instrument")],
        names=_INDEX_NAMES,
    )
    return pd.Series(index=index, dtype=float, name=name)


def signal_frame_to_series(frame: pd.DataFrame, name: str) -> pd.Series:
    """Encode a boolean signal frame as a qlib score Series of 1.0 and 0.0."""
    required = {"symbol", "date", "sig"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"signal frame missing columns: {missing}")
    if frame.empty:
        return _empty_score(name)

    out = frame.loc[:, ["symbol", "date", "sig"]].copy()
    out["datetime"] = pd.to_datetime(out["date"])
    out["instrument"] = out["symbol"].map(to_qlib)
    out[name] = out["sig"].fillna(False).astype(bool).astype(float)
    return out.set_index(_INDEX_NAMES)[name].sort_index()


def factor_frame_to_series(frame: pd.DataFrame, name: str) -> pd.Series:
    """Encode a continuous factor frame as a qlib score Series."""
    required = {"symbol", "date", "factor"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"factor frame missing columns: {missing}")
    if frame.empty:
        return _empty_score(name)

    out = frame.loc[:, ["symbol", "date", "factor"]].dropna(subset=["factor"]).copy()
    if out.empty:
        return _empty_score(name)
    out["datetime"] = pd.to_datetime(out["date"])
    out["instrument"] = out["symbol"].map(to_qlib)
    out[name] = out["factor"].astype(float)
    return out.set_index(_INDEX_NAMES)[name].sort_index()


def build_score_series(config: TopkConfig, symbols: Sequence[str]) -> pd.Series:
    """Build the qlib signal Series for the configured registry entry."""
    if config.kind == "signal":
        return to_factor(config.score, symbols, config.start, config.end)

    frame = compute_factor_frame(config.score, symbols, config.start, config.end)
    return factor_frame_to_series(frame, config.score)


def build_exchange_kwargs(config: TopkConfig) -> dict[str, float]:
    """Return exchange kwargs passed to qlib backtest_daily."""
    return config.exchange.to_kwargs()


def build_regime_series(config: RegimeConfig, start: str, end: str) -> pd.Series:
    """Build the configured AMV regime over the requested report window."""
    if config.kind != "amv_immediate":
        raise ValueError(f"unsupported regime kind: {config.kind}")

    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    load_start = (start_ts - pd.tseries.offsets.BDay(_REGIME_WARMUP_BDAYS)).strftime("%Y-%m-%d")
    index_df = get_ohlcv(
        config.index,
        start=load_start,
        end=end,
        adjust="qfq",
        fields=("open", "high", "low", "close", "volume", "amount"),
    ).sort_index()
    amv_df = amv(index_df, k=config.k)
    signal = build_variant_signal(
        amv_df,
        index_df["close"],
        buy_th=config.buy_th,
        sell_th=config.sell_th,
        variant="immediate",
    )
    regime = signal["regime"].astype("int8").sort_index()
    return regime.loc[(regime.index >= start_ts) & (regime.index <= end_ts)]


def apply_regime_overlay(
    report: pd.DataFrame,
    regime: pd.Series,
    *,
    open_cost: float,
    close_cost: float,
) -> pd.DataFrame:
    """Apply t signal -> t+1 portfolio exposure and open/close costs to a report."""
    required = {"return", "cost"}
    missing = sorted(required - set(report.columns))
    if missing:
        raise ValueError(f"qlib report missing columns: {missing}")

    open_cost_value = float(open_cost)
    close_cost_value = float(close_cost)
    if not np.isfinite(open_cost_value) or not np.isfinite(close_cost_value):
        raise ValueError("open_cost and close_cost must be finite")

    regime_values = regime.dropna().astype(int)
    invalid = sorted(set(regime_values.unique()) - {0, 1})
    if invalid:
        raise ValueError(f"regime must contain only 0/1 values, got {invalid}")

    out = report.copy()
    position = regime_values.reindex(out.index).ffill().fillna(0).shift(1).fillna(0).astype(float)
    position_change = position.diff().fillna(position)
    open_fee = position_change.eq(1.0).astype(float) * open_cost_value
    close_fee = position_change.eq(-1.0).astype(float) * close_cost_value

    out["position"] = position
    out["overlay_return"] = out["return"].astype(float) * position
    out["overlay_cost"] = out["cost"].astype(float) * position + open_fee + close_fee
    return out


def _switched_report(report: pd.DataFrame) -> pd.DataFrame:
    switched = report.copy()
    switched["return"] = switched["overlay_return"].astype(float)
    switched["cost"] = switched["overlay_cost"].astype(float)
    switched["turnover"] = switched["turnover"].astype(float) * switched["position"].astype(float)
    return switched


def _run_qlib_backtest(config: TopkConfig, score: pd.Series) -> pd.DataFrame:
    if score.empty:
        raise ValueError("score Series is empty")

    random.seed(0)
    np.random.seed(0)
    init_qlib()

    from qlib.contrib.evaluate import backtest_daily
    from qlib.contrib.strategy import TopkDropoutStrategy

    strategy = TopkDropoutStrategy(
        signal=score,
        topk=config.topk,
        n_drop=config.n_drop,
        method_sell="bottom",
        method_buy="top",
    )
    report, _positions = backtest_daily(
        start_time=config.start,
        end_time=config.end,
        strategy=strategy,
        benchmark=to_qlib(config.benchmark),
        exchange_kwargs=build_exchange_kwargs(config),
    )
    return report.sort_index()


def extract_metrics(report: pd.DataFrame) -> dict[str, float]:
    """Extract qlib-native risk and turnover metrics from the daily report."""
    required = {"return", "bench", "cost", "turnover"}
    missing = sorted(required - set(report.columns))
    if missing:
        raise ValueError(f"qlib report missing columns: {missing}")

    from qlib.contrib.evaluate import risk_analysis

    net_return = report["return"].astype(float) - report["cost"].astype(float)
    excess_wo_cost = report["return"].astype(float) - report["bench"].astype(float)
    excess_with_cost = excess_wo_cost - report["cost"].astype(float)

    portfolio_risk = risk_analysis(net_return.dropna(), freq="day")["risk"]
    excess_wo_risk = risk_analysis(excess_wo_cost.dropna(), freq="day")["risk"]
    excess_with_risk = risk_analysis(excess_with_cost.dropna(), freq="day")["risk"]

    return {
        "annualized_return": float(portfolio_risk["annualized_return"]),
        "information_ratio": float(excess_with_risk["information_ratio"]),
        "max_drawdown": float(portfolio_risk["max_drawdown"]),
        "turnover_mean": float(report["turnover"].astype(float).mean()),
        "excess_return_wo_cost": float(excess_wo_risk["annualized_return"]),
        "excess_return_with_cost": float(excess_with_risk["annualized_return"]),
    }


def _overlay_metrics(report: pd.DataFrame) -> dict[str, float]:
    base = extract_metrics(report)
    switched = extract_metrics(_switched_report(report))
    position = report["position"].astype(float)
    switches = position.diff().abs().fillna(0).sum()

    metrics = {f"base_{key}": value for key, value in base.items()}
    metrics.update({f"switched_{key}": value for key, value in switched.items()})
    metrics["switched_exposure"] = float(position.mean())
    metrics["switches"] = float(switches)
    return metrics


def _mlflow_params(
    config: TopkConfig, config_path: Path, symbol_count: int
) -> dict[str, str | int | float]:
    params: dict[str, str | int | float] = {
        "config_path": str(config_path),
        "name": config.name,
        "kind": config.kind,
        "score": config.score,
        "start": config.start,
        "end": config.end,
        "universe": config.universe.label(),
        "universe.source": config.universe.source,
        "universe.exclude_boards": ",".join(config.universe.exclude_boards),
        "universe.at": config.universe.at or "",
        "universe.symbol_count": symbol_count,
        "topk": config.topk,
        "n_drop": config.n_drop,
        "benchmark": config.benchmark,
    }
    for key, value in config.exchange.to_kwargs().items():
        params[f"exchange.{key}"] = value
    if config.regime is not None:
        params.update(
            {
                "regime.kind": config.regime.kind,
                "regime.index": config.regime.index,
                "regime.k": config.regime.k,
                "regime.buy_th": config.regime.buy_th,
                "regime.sell_th": config.regime.sell_th,
            }
        )
    return params


def _format_metrics(metrics: Mapping[str, float]) -> str:
    frame = pd.DataFrame([metrics]).T.reset_index()
    frame.columns = ["metric", "value"]
    return frame.to_markdown(index=False, floatfmt=".12g")


def _format_overlay_comparison(metrics: Mapping[str, float]) -> str:
    metric_names = [key.removeprefix("base_") for key in metrics if key.startswith("base_")]
    rows = [
        {
            "metric": name,
            "base": metrics[f"base_{name}"],
            "switched": metrics[f"switched_{name}"],
        }
        for name in metric_names
    ]
    return pd.DataFrame(rows).to_markdown(index=False, floatfmt=".12g")


def _write_reports(
    config: TopkConfig,
    report: pd.DataFrame,
    metrics: Mapping[str, float],
    mlflow_run_id: str,
    symbol_count: int,
) -> dict[str, Path]:
    output_dir = REPORT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    report_csv = output_dir / f"{config.name}_report.csv"
    metrics_csv = output_dir / f"{config.name}_metrics.csv"
    md_path = output_dir / f"{config.name}_summary.md"

    report.to_csv(report_csv, index_label="datetime")
    pd.DataFrame([metrics]).to_csv(metrics_csv, index=False)

    exchange = config.exchange
    lines = [
        f"# {config.name} TopkDropout baseline",
        "",
        f"- mlflow_run_id: {mlflow_run_id}",
        f"- kind: {config.kind}",
        f"- score: {config.score}",
        f"- window: {config.start} to {config.end}",
        f"- universe: {config.universe.label()} ({symbol_count} symbols)",
        f"- topk/n_drop: {config.topk}/{config.n_drop}",
        f"- benchmark: {config.benchmark}",
        (
            "- exchange: "
            f"open_cost={exchange.open_cost}, close_cost={exchange.close_cost}, "
            f"min_cost={exchange.min_cost}, limit_threshold={exchange.limit_threshold}"
        ),
    ]
    if config.regime is not None:
        regime = config.regime
        lines.extend(
            [
                (
                    "- regime: "
                    f"kind={regime.kind}, index={regime.index}, k={regime.k}, "
                    f"buy_th={regime.buy_th}, sell_th={regime.sell_th}"
                ),
                (
                    "- overlay: Tier2 overlay 近似（一步全仓切换 + "
                    "开/平仓单边计费），Tier3 以 backtrader 为准"
                ),
            ]
        )
    lines.extend(["", "## Metrics", "", _format_metrics(metrics)])
    if config.regime is not None:
        lines.extend(["", "## Base vs Switched", "", _format_overlay_comparison(metrics)])
    lines.extend(
        [
            "",
            "## Qlib Report",
            "",
            f"- raw_report_csv: {report_csv}",
            f"- metrics_csv: {metrics_csv}",
        ]
    )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"csv": report_csv, "metrics_csv": metrics_csv, "md": md_path}


def _record_mlflow_and_reports(
    config: TopkConfig,
    config_path: Path,
    report: pd.DataFrame,
    metrics: dict[str, float],
    symbol_count: int,
) -> tuple[str, dict[str, Path]]:
    import mlflow

    settings = get_settings()
    settings.mlruns_uri.mkdir(parents=True, exist_ok=True)
    mlflow.set_tracking_uri(str(settings.mlruns_uri))
    mlflow.set_experiment(EXPERIMENT_NAME)

    with mlflow.start_run(run_name=config.name) as run:
        mlflow_run_id = run.info.run_id
        mlflow.log_params(_mlflow_params(config, config_path, symbol_count))
        mlflow.log_metrics(metrics)
        report_paths = _write_reports(config, report, metrics, mlflow_run_id, symbol_count)
        for path in report_paths.values():
            mlflow.log_artifact(str(path))

    return mlflow_run_id, report_paths


def run_topk_backtest(config_path: str | Path) -> TopkResult:
    """Run config -> registry score -> TopkDropout backtest -> mlflow + reports."""
    path = Path(config_path)
    config = load_topk_config(path)
    symbols = resolve_universe(config.universe)
    score = build_score_series(config, symbols)
    report = _run_qlib_backtest(config, score)
    if config.regime is None:
        metrics = extract_metrics(report)
    else:
        regime = build_regime_series(config.regime, config.start, config.end)
        report = apply_regime_overlay(
            report,
            regime,
            open_cost=config.exchange.open_cost,
            close_cost=config.exchange.close_cost,
        )
        metrics = _overlay_metrics(report)
    mlflow_run_id, report_paths = _record_mlflow_and_reports(
        config, path, report, metrics, len(symbols)
    )
    return TopkResult(metrics=metrics, report_paths=report_paths, mlflow_run_id=mlflow_run_id)

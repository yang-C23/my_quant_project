from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import pandas as pd

LOGGER = logging.getLogger("data_quality")


class DataQualityChecker:
    def __init__(
        self,
        data_dir: str | Path,
        max_daily_return: float = 0.20,
        min_price: float = 0.01,
        max_price: float = 10000.0,
    ):
        self.data_dir = Path(data_dir)
        self.raw_dir = self.data_dir / "raw_price"
        self.factor_dir = self.data_dir / "adj_factor"
        self.max_daily_return = max_daily_return
        self.min_price = min_price
        self.max_price = max_price

    def load_raw_data(self, symbol: str) -> pd.DataFrame:
        csv_path = self.raw_dir / f"{symbol}.csv"
        if not csv_path.exists():
            raise FileNotFoundError(f"Raw data file not found: {csv_path}")

        df = pd.read_csv(csv_path)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        return df

    def load_factor_data(self, symbol: str) -> pd.DataFrame:
        csv_path = self.factor_dir / f"{symbol}.csv"
        if not csv_path.exists():
            raise FileNotFoundError(f"Adj factor file not found: {csv_path}")

        df = pd.read_csv(csv_path)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

        if "factor" not in df.columns:
            raise ValueError(f"Missing 'factor' column in {csv_path}")
        df["factor"] = pd.to_numeric(df["factor"], errors="coerce")

        return df

    def check_price_validity(self, df: pd.DataFrame) -> pd.DataFrame:
        issues = pd.DataFrame(index=df.index)
        issues["negative_price"] = (
            (df["close"] <= 0)
            | (df["open"] <= 0)
            | (df["high"] <= 0)
            | (df["low"] <= 0)
        )
        issues["price_out_of_range"] = (
            (df["close"] < self.min_price) | (df["close"] > self.max_price)
        )
        issues["ohlc_invalid"] = (
            (df["high"] < df["low"])
            | (df["high"] < df["open"])
            | (df["high"] < df["close"])
            | (df["low"] > df["open"])
            | (df["low"] > df["close"])
        )

        returns = df["close"].pct_change()
        issues["extreme_return"] = (returns.abs() > self.max_daily_return) & returns.notna()

        return issues

    def detect_suspension(self, df: pd.DataFrame) -> pd.Series:
        zero_volume = df["volume"] == 0
        flat_price = (
            (df["open"] == df["close"])
            & (df["close"] == df["high"])
            & (df["high"] == df["low"])
        )
        return zero_volume | flat_price

    def detect_limit_price(self, df: pd.DataFrame) -> Tuple[pd.Series, pd.Series]:
        returns = df["close"].pct_change()
        upper_limit = (returns > 0.099) & (returns < 0.101)
        lower_limit = (returns < -0.099) & (returns > -0.101)
        return upper_limit, lower_limit

    def handle_outliers(
        self,
        df: pd.DataFrame,
        columns: list[str] | None = None,
        method: str = "clip",
        std_threshold: float = 5.0,
    ) -> pd.DataFrame:
        df = df.copy()
        columns = columns or ["close", "volume"]

        for col in columns:
            if col not in df.columns:
                continue

            mean = df[col].mean()
            std = df[col].std()
            lower_bound = mean - std_threshold * std
            upper_bound = mean + std_threshold * std

            if method == "clip":
                df[col] = df[col].clip(lower=lower_bound, upper=upper_bound)
            elif method == "remove":
                outliers = (df[col] < lower_bound) | (df[col] > upper_bound)
                df.loc[outliers, col] = np.nan

        return df

    def fill_missing_values(self, df: pd.DataFrame, method: str = "ffill") -> pd.DataFrame:
        df = df.copy()
        if method == "ffill":
            return df.fillna(method="ffill")
        if method == "bfill":
            return df.fillna(method="bfill")
        if method == "interpolate":
            return df.interpolate(method="linear")
        return df

    def process_stock(
        self,
        symbol: str,
        remove_suspension: bool = True,
        mark_limit_price: bool = True,
        handle_outliers: bool = True,
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        LOGGER.info("Processing %s", symbol)

        raw_df = self.load_raw_data(symbol)
        factor_df = self.load_factor_data(symbol)
        original_len = len(raw_df)

        issues = self.check_price_validity(raw_df)
        invalid_rows = issues.any(axis=1)

        if invalid_rows.sum() > 0:
            raw_df = raw_df[~invalid_rows].copy()

        raw_df["is_suspended"] = self.detect_suspension(raw_df)
        if remove_suspension:
            raw_df = raw_df[~raw_df["is_suspended"]].copy()

        if mark_limit_price:
            upper_limit, lower_limit = self.detect_limit_price(raw_df)
            raw_df["is_upper_limit"] = upper_limit
            raw_df["is_lower_limit"] = lower_limit

        if handle_outliers:
            raw_df = self.handle_outliers(raw_df, columns=["close", "volume"], method="clip")

        raw_df = self.fill_missing_values(raw_df, method="ffill")
        raw_df = raw_df.reset_index(drop=True)

        merged = pd.merge(raw_df, factor_df, on="date", how="left")
        merged["factor"] = merged["factor"].ffill().bfill()
        merged = merged.dropna(subset=["factor"]).reset_index(drop=True)
        raw_df = merged.drop(columns=["factor"])
        factor_df = merged[["date", "factor"]].copy()

        final_len = len(raw_df)
        removed_pct = (original_len - final_len) / original_len * 100 if original_len else 0
        LOGGER.info("%s done: %d -> %d (%.2f%% removed)", symbol, original_len, final_len, removed_pct)

        return raw_df, factor_df

    def generate_quality_report(self, symbol: str) -> dict:
        df = self.load_raw_data(symbol)
        report = {
            "symbol": symbol,
            "total_rows": len(df),
            "date_range": {
                "start": df["date"].min().strftime("%Y-%m-%d"),
                "end": df["date"].max().strftime("%Y-%m-%d"),
            },
            "missing_values": {},
            "price_issues": {},
            "suspension_days": 0,
            "limit_price_days": {},
        }

        for col in ["open", "high", "low", "close", "volume"]:
            missing = df[col].isna().sum()
            report["missing_values"][col] = {
                "count": int(missing),
                "percentage": float(missing / len(df) * 100),
            }

        issues = self.check_price_validity(df)
        for issue_type in issues.columns:
            count = issues[issue_type].sum()
            report["price_issues"][issue_type] = {
                "count": int(count),
                "percentage": float(count / len(df) * 100),
            }

        suspension = self.detect_suspension(df)
        report["suspension_days"] = int(suspension.sum())

        upper_limit, lower_limit = self.detect_limit_price(df)
        report["limit_price_days"] = {
            "upper_limit": int(upper_limit.sum()),
            "lower_limit": int(lower_limit.sum()),
        }

        return report


def batch_process_stocks(
    symbols: list[str],
    data_dir: str | Path,
    output_dir: Optional[str | Path] = None,
    remove_suspension: bool = True,
    mark_limit_price: bool = True,
    handle_outliers: bool = True,
    generate_adj_price: bool = True,
) -> dict[str, dict[str, pd.DataFrame]]:
    checker = DataQualityChecker(data_dir=data_dir)
    results = {}

    for symbol in symbols:
        try:
            clean_raw, clean_factor = checker.process_stock(
                symbol,
                remove_suspension=remove_suspension,
                mark_limit_price=mark_limit_price,
                handle_outliers=handle_outliers,
            )
            results[symbol] = {"raw": clean_raw, "factor": clean_factor}

            if output_dir:
                output_dir_path = Path(output_dir)
                raw_dir = output_dir_path / "raw_price"
                factor_dir = output_dir_path / "adj_factor"
                adj_dir = output_dir_path / "adj_price"
                raw_dir.mkdir(parents=True, exist_ok=True)
                factor_dir.mkdir(parents=True, exist_ok=True)
                if generate_adj_price:
                    adj_dir.mkdir(parents=True, exist_ok=True)
                raw_path = raw_dir / f"{symbol}.csv"
                factor_path = factor_dir / f"{symbol}.csv"
                clean_raw.to_csv(raw_path, index=False)
                clean_factor.to_csv(factor_path, index=False)

                if generate_adj_price and not clean_factor.empty:
                    merged = pd.merge(clean_raw, clean_factor, on="date", how="left")
                    merged["factor"] = merged["factor"].ffill().bfill()
                    merged = merged.dropna(subset=["factor"]).reset_index(drop=True)
                    if not merged.empty:
                        last_factor = merged["factor"].iloc[-1]
                        adj = merged.copy()
                        for col in ["open", "high", "low", "close"]:
                            adj[col] = adj[col] * last_factor / adj["factor"]
                        adj = adj.drop(columns=["factor"]).reset_index(drop=True)
                        adj_path = adj_dir / f"{symbol}.csv"
                        adj.to_csv(adj_path, index=False)
        except Exception as exc:
            LOGGER.error("Process %s failed: %s", symbol, exc)

    return results

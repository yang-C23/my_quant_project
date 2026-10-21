"""Prespecified cash-pool experiments; unavailable hypotheses remain registered."""

from __future__ import annotations

from dataclasses import asdict

import pandas as pd

from quant.longterm.cash_pool import PoolPolicy
from quant.longterm.stages import StageSpec


def pool_registry(config: dict) -> list[dict]:
    """Vary one dimension at a time; do not optimize after seeing returns."""
    output = []
    default = asdict(PoolPolicy(**config["funding"], exit="none"))
    stage = asdict(StageSpec(**config["stages"]))
    primary = config["primary_valuation"]

    def add(identifier: str, *, scope: str = "all", **changes: object) -> None:
        policy = default | changes.pop("policy", {})
        stages = stage | changes.pop("stages", {})
        PoolPolicy(**policy)
        StageSpec(**stages)
        output.append(
            {"id": identifier, "scope": scope, "policy": policy, "stages": stages, **changes}
        )

    for name in ("lump_sum", "dca", "kdj", "kdj_core50"):
        add(f"legacy_{name}", engine="legacy", legacy=name)
    for fraction in config["cash_controls"]["equity_contribution_fractions"]:
        add(
            f"cash_control_equity{fraction:g}",
            engine="pool",
            policy={"entry": "never", "core_fraction": fraction},
        )
    for entry in config["primary_entries"]:
        for core in config["core_fractions"]:
            add(
                f"pool_{entry}_core{core:g}",
                engine="pool",
                policy={"entry": entry, "core_fraction": core},
            )
    for entry in config["valuation_entries"]:
        for exit_style in config["valuation_exits"]:
            for core in (0, 0.5):
                add(
                    f"pool_{entry}_pe10_{exit_style}_core{core:g}",
                    engine="pool",
                    policy={"entry": entry, "exit": exit_style, "core_fraction": core},
                    metric=primary["metric"],
                    window=primary["window"],
                )
    for metric in config["valuation_metrics"]:
        for window in config["valuation_windows"]:
            if (metric, window) == (primary["metric"], primary["window"]):
                continue
            add(
                f"temperature_{metric}_{window}",
                engine="pool",
                policy={"entry": "valuation", "exit": "valuation_time"},
                metric=metric,
                window=window,
            )
    for entry in ("unconditional", "pressure", "stabilized", "relief"):
        for count in config["batch_counts"]:
            if count != config["funding"]["tranches"]:
                add(
                    f"batches_{entry}_{count}",
                    engine="pool",
                    policy={"entry": entry, "tranches": count},
                )
    for entry in ("pressure", "stabilized", "relief"):
        for extra in config["operational_event_tranches"]:
            add(
                f"extra_{entry}_{extra}",
                engine="pool",
                policy={"entry": entry, "event_tranches": extra},
            )
    for entry in config["technical_exit"]["entries"]:
        add(
            f"recovery_exit_{entry}",
            engine="pool",
            policy={"entry": entry, "exit": "recovery_time"},
        )
    for parameter, values in config["parameter_neighbors"].items():
        for value in values:
            for entry in ("pressure", "stabilized", "relief"):
                # Confirmation/relief settings cannot alter the immediate entry.
                if parameter in {"confirmation", "relief_fraction"} and entry == "pressure":
                    continue
                if parameter == "relief_fraction" and entry == "stabilized":
                    continue
                add(
                    f"neighbor_{entry}_{parameter}_{value}",
                    scope="neighbor",
                    engine="pool",
                    policy={"entry": entry},
                    stages={parameter: value},
                )
    for parameter, values in config["valuation_neighbors"].items():
        for value in values:
            add(
                f"neighbor_valuation_{parameter}_{value}",
                scope="neighbor",
                engine="pool",
                policy={"entry": "valuation", "exit": "valuation_time", parameter: value},
                metric="pe",
                window=10,
            )
    add(
        "dynamic_deep_valuation",
        engine="pool",
        policy={
            "entry": "valuation",
            "exit": "valuation_time",
            "dynamic_deep_threshold": config["dynamic_deep_threshold"],
        },
        metric="pe",
        window=10,
    )
    for parameter, values in config["sensitivity"].items():
        if parameter == "supplemental_release_extra_sessions":
            continue
        for value in values:
            for entry in ("unconditional", "stabilized"):
                changes = {"entry": entry}
                if parameter == "monthly_ratio":
                    changes["monthly"] = config["funding"]["initial"] * value
                elif parameter == "initial":
                    changes["initial"] = value
                    changes["monthly"] = value * (
                        config["funding"]["monthly"] / config["funding"]["initial"]
                    )
                add(
                    f"sensitivity_{entry}_{parameter}_{value}",
                    scope="neighbor",
                    engine="pool",
                    policy=changes,
                    execution_override={parameter: value}
                    if parameter in {"commission_rate", "slippage_bps"}
                    else {},
                    availability_delay=value
                    if parameter == "supplemental_release_extra_sessions"
                    else 0,
                )
    # Release assumptions require factor-dependent paired comparisons.
    for entry in ("vix_relief", "margin_relief", "position_relief"):
        for delay in config["sensitivity"]["supplemental_release_extra_sessions"]:
            add(
                f"release_delay_{entry}_{delay}",
                scope="neighbor",
                engine="pool",
                policy={"entry": entry},
                availability_delay=delay,
            )
    for entry, field, values in (
        ("margin_relief", "finra_lag_months", config["supplemental"]["finra_release_lag_months"]),
        ("position_relief", "cftc_lag_days", config["supplemental"]["cftc_release_lag_days"]),
    ):
        for lag in values[1:]:
            add(
                f"release_assumption_{entry}_{lag}",
                engine="pool",
                policy={"entry": entry},
                supplemental_lags={field: lag},
            )
    for entry in ("unconditional", "pressure", "stabilized", "relief"):
        add(
            f"cash_dividends_{entry}",
            engine="pool",
            policy={"entry": entry, "reinvest_dividends": False},
            assets=list(config["corporate_action_sources"]),
        )
    for lag in config["shiller_exploration"]["observation_lag_months"]:
        for entry in config["valuation_entries"]:
            for exit_style in config["valuation_exits"]:
                add(
                    f"shiller_lag{lag}_{entry}_pe10_{exit_style}",
                    engine="pool",
                    policy={"entry": entry, "exit": exit_style},
                    metric="pe",
                    window=10,
                    valuation_source="shiller_proxy",
                    observation_lag_months=lag,
                    assets=config["shiller_exploration"]["assets"],
                )
        for metric in config["shiller_exploration"]["metrics"]:
            for window in config["valuation_windows"]:
                if (metric, window) == ("pe", 10):
                    continue
                add(
                    f"shiller_lag{lag}_temperature_{metric}_{window}",
                    engine="pool",
                    policy={"entry": "valuation", "exit": "valuation_time"},
                    metric=metric,
                    window=window,
                    valuation_source="shiller_proxy",
                    observation_lag_months=lag,
                    assets=config["shiller_exploration"]["assets"],
                )
    if len({row["id"] for row in output}) != len(output):
        raise ValueError("duplicate experiment identifiers")
    return output


def pool_windows(
    dates: pd.DatetimeIndex, config: dict, *, calendar: pd.DatetimeIndex | None = None
) -> list[dict]:
    """Keep missing-factor intervals inside the funding and comparison calendar.

    `dates` bounds the interval after initial factor readiness. A later gap must
    not silently move a five-year account start forward by several years. When a
    separate calendar is provided, the strategy waits in cash during that gap.
    """
    if len(dates) < 60:
        return []
    first, last = dates[0], dates[-1]
    if calendar is not None:
        if (
            not calendar.is_unique
            or not calendar.is_monotonic_increasing
            or len(dates.difference(calendar))
        ):
            raise ValueError("availability dates must belong to the unique trading calendar")
        dates = calendar[(calendar >= first) & (calendar <= last)]
    out = []

    def add(identifier: str, start: pd.Timestamp, end: pd.Timestamp, phase: str) -> None:
        usable = dates[(dates >= start) & (dates <= end)]
        if (
            phase == "overlapping_retrospective"
            and len(usable)
            and ((usable[0] - start).days > 14 or (end - usable[-1]).days > 14)
        ):
            # Fail closed if a caller supplies only sparse factor observations.
            # Never label a truncated interval as the requested five/ten years.
            raise ValueError("rolling window lost its calendar; supply the full trading calendar")
        if len(usable) >= 60:
            out.append(
                {
                    "id": identifier,
                    "start": str(usable[0].date()),
                    "end": str(usable[-1].date()),
                    "phase": phase,
                }
            )

    add("full", first, last, "retrospective_descriptive")
    common = pd.Timestamp(config["validation"]["common_start"])
    if first <= common:
        add("common_since_2016", common, last, "common_calendar")
    splits = config["validation"]["chronological_split"]
    if len(splits) != 3 or abs(sum(splits) - 1) > 1e-10 or min(splits) <= 0:
        raise ValueError("three positive chronological fractions summing to one required")
    a, b = [int(len(dates) * fraction) for fraction in (splits[0], sum(splits[:2]))]
    for name, lo, hi in (("train", 0, a), ("validation", a, b), ("test", b, len(dates))):
        add(f"retrospective_{name}", dates[lo], dates[hi - 1], "retrospective_seen_history")
    for years in config["validation"]["rolling_years"]:
        end, n = last, 0
        while end - pd.DateOffset(years=years) >= first:
            start = end - pd.DateOffset(years=years)
            label = f"latest_{years}y" if n == 0 else f"rolling_{years}y_{end.date()}"
            add(label, start, end, "overlapping_retrospective")
            end -= pd.DateOffset(years=config["validation"]["rolling_step_years"])
            n += 1
    return out

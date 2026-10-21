"""Complete window summaries and clustered event comparisons, without winner selection."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from quant.data.snapshots import sha256_file, write_json
from quant.etl.restart import code_revision


CORE_EXPERIMENTS = [
    "legacy_lump_sum",
    "legacy_dca",
    "pool_unconditional_core0",
    "pool_pressure_core0",
    "pool_stabilized_core0",
    "pool_relief_core0",
    "pool_stabilized_core0.25",
    "pool_stabilized_core0.5",
    "cash_control_equity0.5",
    "pool_kdj_core0",
    "pool_vix_relief_core0",
    "pool_margin_relief_core0",
    "pool_position_relief_core0",
    "recovery_exit_stabilized",
]


def daily_artifact(source: Path, record: dict | pd.Series) -> Path:
    """Resolve an explicitly adjudicated case without changing the frozen study."""
    corrected = record.get("corrected_artifact_directory")
    directory = (
        Path(corrected) if isinstance(corrected, str) else source / record["result_directory"]
    )
    return directory / "daily.parquet"


def apply_calendar_corrections(
    source: Path, results: pd.DataFrame, corrections: Path
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Replace only checksum-bound original cases; retain superseded rows in the report."""
    registration = json.loads((corrections / "registration.json").read_text())
    if registration["source_registration_sha256"] != sha256_file(source / "registration.json"):
        raise ValueError("corrections belong to another registered study")
    for name, expected in json.loads((corrections / "payloads.json").read_text()).items():
        if sha256_file(corrections / name) != expected:
            raise ValueError(f"correction checksum failure: {name}")
    changes = pd.read_parquet(corrections / "results.parquet")
    keys = ["asset", "experiment", "window"]
    updated = results.set_index(keys)
    if not updated.index.is_unique or changes.duplicated(keys).any():
        raise ValueError("correction identity must be unique")
    old = []
    for change in changes.to_dict("records"):
        key = tuple(change[k] for k in keys)
        if key not in updated.index:
            raise ValueError("correction cannot add an unregistered case")
        before = updated.loc[key].to_dict()
        record_path = source / before["result_directory"] / "record.json"
        if sha256_file(record_path) != change["superseded_record_sha256"]:
            raise ValueError("superseded case checksum mismatch")
        if change["status"] != "computed" or not change["independent_ledger_verified"]:
            raise ValueError("correction requires verified financial reconstruction")
        old.append(dict(zip(keys, key, strict=True)) | before)
        change["corrected_artifact_directory"] = str(corrections / change["result_directory"])
        for column, value in change.items():
            if column in keys:
                continue
            if column not in updated:
                updated[column] = pd.Series(index=updated.index, dtype=object)
            updated.at[key, column] = value
    return updated.reset_index(), pd.DataFrame(old)


def recovery_episodes(nav: pd.Series) -> pd.DataFrame:
    """Calendar time below each high, preserving still-open losses as censored.

    An initial unit NAV of one exists immediately before the first transaction.
    The first date represents that funding instant if costs immediately create
    a loss. A new cash contribution cannot itself create a high in this series.
    """
    if (
        nav.empty
        or not nav.index.is_unique
        or not nav.index.is_monotonic_increasing
        or not np.isfinite(nav).all()
        or (nav <= 0).any()
    ):
        raise ValueError("positive finite NAV on unique increasing dates required")
    peak, peak_date, initial_peak = 1.0, nav.index[0], True
    active = None
    rows = []
    for date, value in nav.items():
        if value < peak * (1 - 1e-12):
            if active is None:
                active = {
                    "peak_date": str(peak_date.date()),
                    "initial_funding_peak": initial_peak,
                    "trough_date": str(date.date()),
                    "max_drawdown": float(value / peak - 1),
                    "underwater_sessions": 0,
                }
            active["underwater_sessions"] += 1
            if value / peak - 1 < active["max_drawdown"]:
                active["max_drawdown"] = float(value / peak - 1)
                active["trough_date"] = str(date.date())
            continue
        if active is not None:
            rows.append(
                active
                | {
                    "recovery_date": str(date.date()),
                    "observed_until": str(date.date()),
                    "elapsed_calendar_days": (date - peak_date).days,
                    "censored": False,
                }
            )
            active = None
        peak, peak_date, initial_peak = float(value), date, False
    if active is not None:
        rows.append(
            active
            | {
                "recovery_date": None,
                "observed_until": str(nav.index[-1].date()),
                "elapsed_calendar_days": (nav.index[-1] - peak_date).days,
                "censored": True,
            }
        )
    return pd.DataFrame(rows)


def recovery_diagnostics(source: Path, results: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Measure every drawdown, not only the single deepest episode."""
    summaries, episodes = [], []
    for record in results.to_dict("records"):
        daily = pd.read_parquet(daily_artifact(source, record))
        identified = recovery_episodes(daily.twr_nav)
        identity = {k: record[k] for k in ("asset", "experiment", "window", "start", "end")}
        if identified.empty:
            summary = {
                "longest_observed_underwater_days": 0,
                "longest_completed_recovery_days": 0,
                "open_underwater_days": 0,
                "open_drawdown": False,
                "underwater_session_fraction": 0.0,
                "drawdown_episodes": 0,
            }
        else:
            complete = identified[~identified.censored]
            open_loss = identified[identified.censored]
            summary = {
                "longest_observed_underwater_days": int(identified.elapsed_calendar_days.max()),
                "longest_completed_recovery_days": int(complete.elapsed_calendar_days.max())
                if len(complete)
                else None,
                "open_underwater_days": int(open_loss.elapsed_calendar_days.max())
                if len(open_loss)
                else 0,
                "open_drawdown": bool(len(open_loss)),
                "underwater_session_fraction": identified.underwater_sessions.sum() / len(daily),
                "drawdown_episodes": len(identified),
            }
            episodes.append(identified.assign(**identity))
        summaries.append(
            identity
            | summary
            | {
                key: record[key]
                for key in (
                    "longest_capital_shortfall_days",
                    "capital_shortfall_unrecovered",
                    "max_loss_vs_contributions",
                    "below_contributions_at_12m",
                    "below_contributions_at_24m",
                    "initial_wait_days",
                    "initial_wait_censored",
                )
            }
        )
    return (
        pd.DataFrame(summaries),
        pd.concat(episodes, ignore_index=True) if episodes else pd.DataFrame(),
    )


def crisis_labels(dates: pd.Series, gap_days: int) -> pd.Series:
    """Consecutive stress dates within the gap belong to the same dependent cluster."""
    ordered = pd.to_datetime(dates).drop_duplicates().sort_values()
    labels = ordered.diff().dt.days.gt(gap_days).cumsum()
    mapping = dict(zip(ordered, labels, strict=True))
    return pd.to_datetime(dates).map(mapping).astype(int)


def clustered_event_comparisons(
    events: pd.DataFrame, config: dict
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compare every event on the immediate-entry calendar, including non-entry cash.

    Missing factors and incomplete future windows remain missing. Inference uses
    equal-weight crisis means; overlapping individual events are not independent.
    Fewer than three crises do not receive a numerical confidence interval.
    """
    summaries, leave_out = [], []
    rng = np.random.default_rng(config["bootstrap_seed"])
    for asset, source in events.groupby("asset", sort=True):
        source = source.copy()
        source["crisis"] = crisis_labels(source.event_date, config["crisis_gap_days"])
        pressure = source[source.stage.eq("pressure")].set_index("event_id")
        for stage, group in source[~source.stage.eq("pressure")].groupby("stage", sort=True):
            group = group.set_index("event_id")
            for horizon in config["horizons"]:
                column = f"event_horizon_return_{horizon}"
                if column not in group or column not in pressure:
                    continue
                difference = group[column] - pressure[column].reindex(group.index)
                paired = pd.DataFrame({"delta": difference, "crisis": group.crisis}).dropna()
                clusters = paired.groupby("crisis").delta.mean()
                row = {
                    "asset": asset,
                    "stage": stage,
                    "horizon_sessions": horizon,
                    "registered_events": len(group),
                    "paired_events": len(paired),
                    "crisis_clusters": len(clusters),
                    "entered_events": int(group.status.eq("entered").sum()),
                    "no_confirmation_events": int(
                        group.status.eq("no_confirmation_in_window").sum()
                    ),
                    "factor_missing_events": int(group.status.eq("factor_unavailable").sum()),
                    "equal_crisis_mean_delta": float(clusters.mean()) if len(clusters) else None,
                    "event_weighted_mean_delta": float(difference.mean())
                    if difference.notna().any()
                    else None,
                    "ci_low": None,
                    "ci_high": None,
                    "interval_status": "fewer_than_three_crises"
                    if len(clusters) < 3
                    else "exploratory_cluster_bootstrap",
                }
                if len(clusters) >= 3:
                    samples = rng.choice(
                        clusters.to_numpy(),
                        size=(config["bootstrap_repetitions"], len(clusters)),
                        replace=True,
                    ).mean(axis=1)
                    row["ci_low"], row["ci_high"] = np.quantile(samples, [0.025, 0.975]).tolist()
                summaries.append(row)
                if len(clusters) >= 2:
                    for omitted in clusters.index:
                        leave_out.append(
                            {
                                "asset": asset,
                                "stage": stage,
                                "horizon_sessions": horizon,
                                "omitted_crisis": int(omitted),
                                "remaining_crisis_mean_delta": float(clusters.drop(omitted).mean()),
                                "remaining_clusters": len(clusters) - 1,
                            }
                        )
    return pd.DataFrame(summaries), pd.DataFrame(leave_out)


def validate_window_horizons(results: pd.DataFrame) -> None:
    """Reject annual-window labels whose actual calendar interval was shortened."""
    windows = results[
        results.status.eq("computed")
        & results.window.fillna("").str.match(r"(?:latest|rolling)_\d+y")
    ]
    for row in windows.to_dict("records"):
        years = int(row["window"].split("_")[1].removesuffix("y"))
        start, end = pd.Timestamp(row["start"]), pd.Timestamp(row["end"])
        expected = end - pd.DateOffset(years=years)
        if pd.isna(start) or pd.isna(end) or abs((start - expected).days) > 14:
            raise ValueError(
                f"incorrect calendar horizon: {row.get('asset')}/"
                f"{row.get('experiment')}/{row['window']} {start}..{end}"
            )


def window_summary(results: pd.DataFrame) -> pd.DataFrame:
    """Separate five-, ten- and fifteen-year windows and retain adverse outcomes."""
    validate_window_horizons(results)
    windows = results[
        results.status.eq("computed")
        & results.window.fillna("").str.startswith(("latest_", "rolling_"))
    ].copy()
    if windows.empty:
        return pd.DataFrame()
    windows["horizon_years"] = windows.window.str.extract(r"_(\d+)y", expand=False).astype(int)
    windows["loss"] = windows.ending_profit < 0
    windows["drawdown_exceeds_30pct"] = windows.max_drawdown < -0.30
    windows["wait_longer_than_24m"] = windows.initial_wait_days > 730.485
    return (
        windows.groupby(["asset", "experiment", "horizon_years"], sort=True)
        .agg(
            windows=("ending_wealth", "size"),
            worst_annualized=("annualized_return", "min"),
            median_annualized=("annualized_return", "median"),
            best_annualized=("annualized_return", "max"),
            median_xirr=("xirr", "median"),
            worst_drawdown=("max_drawdown", "min"),
            median_drawdown=("max_drawdown", "median"),
            longest_shortfall_days=("longest_capital_shortfall_days", "max"),
            median_shortfall_days=("longest_capital_shortfall_days", "median"),
            unrecovered_shortfall_fraction=("capital_shortfall_unrecovered", "mean"),
            below_contributions_at_12m_fraction=("below_contributions_at_12m", "mean"),
            below_contributions_at_24m_fraction=("below_contributions_at_24m", "mean"),
            loss_window_fraction=("loss", "mean"),
            drawdown_over_30pct_fraction=("drawdown_exceeds_30pct", "mean"),
            no_tactical_entry_fraction=("initial_wait_censored", "mean"),
            wait_over_24m_fraction=("wait_longer_than_24m", "mean"),
            median_initial_tactical_wait_days=("initial_wait_days", "median"),
            longest_initial_tactical_wait_days=("initial_wait_days", "max"),
            median_cash_fraction=("average_cash_fraction", "median"),
            median_wealth_delta_vs_pool=("delta_ending_wealth_vs_pool", "median"),
            worst_wealth_delta_vs_pool=("delta_ending_wealth_vs_pool", "min"),
        )
        .reset_index()
    )


def plot_examples(source: Path, output: Path, results: pd.DataFrame) -> list[str]:
    """Export reproducible standalone research figures; no artificial daily returns."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["svg.hashsalt"] = "quant-cash-pool-research-v1"
    output.mkdir(exist_ok=True)
    assets = ["sp500", "nasdaq100", "csi300", "dividend_lowvol", "dividend_lowvol100"]
    names = [
        "legacy_dca",
        "pool_unconditional_core0",
        "pool_stabilized_core0",
        "pool_stabilized_core0.5",
        "cash_control_equity0.5",
    ]
    paths = []
    for asset in assets:
        subset = results[
            results.asset.eq(asset)
            & results.experiment.isin(names)
            & results.window.eq("latest_5y")
            & results.status.eq("computed")
        ]
        if subset.empty:
            continue
        fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True, layout="constrained")
        for name in names:
            selected = subset[subset.experiment.eq(name)]
            if selected.empty:
                continue
            row = selected.iloc[0]
            daily = pd.read_parquet(daily_artifact(source, row))
            axes[0].plot(daily.index, daily.twr_nav, label=name, linewidth=1.4)
            # Include the initial unit NAV in the peak for the first cost deduction.
            drawdown = daily.twr_nav / daily.twr_nav.cummax().clip(lower=1) - 1
            axes[1].plot(daily.index, 100 * drawdown, linewidth=1.2)
        axes[0].set_title(f"{asset}: matched latest 5-year cash accounts (exploratory)")
        axes[0].set_ylabel("Flow-adjusted NAV")
        axes[1].set_ylabel("Drawdown (%)")
        axes[0].legend(fontsize=7, loc="upper left", ncol=2)
        for ax in axes:
            ax.grid(alpha=0.2)
        for extension in ("png", "svg"):
            path = output / f"{asset}_5y.{extension}"
            fig.savefig(path, dpi=160, metadata={"Date": None} if extension == "svg" else {})
            paths.append(path.name)
        plt.close(fig)
    return paths


def analyze_pool_run(
    source: Path, config: dict, output: Path, *, corrections: Path | None = None
) -> dict:
    """Bind analysis to every saved result, including blocked and failed hypotheses."""
    if output.exists():
        raise ValueError("use a new analysis directory to preserve previous evidence")
    summary = json.loads((source / "summary.json").read_text())
    if any(x.get("status") == "asset_error" for x in summary["outcomes"]):
        raise ValueError("unresolved asset errors: repair and complete the run before analysis")
    results = pd.read_parquet(source / "results.parquet")
    superseded = pd.DataFrame()
    if corrections is not None:
        results, superseded = apply_calendar_corrections(source, results, corrections)
    if results.status.eq("error").any():
        raise ValueError("unresolved case errors: all failures must be adjudicated")
    computed = results[results.status.eq("computed")]
    if not computed.independent_ledger_verified.fillna(False).all():
        raise ValueError("independent accounting validation incomplete")
    output.mkdir(parents=True)
    event_files = sorted(source.glob("*/events.parquet"))
    write_json(
        output / "registration.json",
        {
            "source": str(source.resolve()),
            "registration_sha256": sha256_file(source / "registration.json"),
            "results_sha256": sha256_file(source / "results.parquet"),
            "event_hashes": {p.parent.name: sha256_file(p) for p in event_files},
            "config": config,
            "code": code_revision(),
            "selection": "none",
            "corrections": str(corrections) if corrections else None,
            "corrections_registration_sha256": sha256_file(corrections / "registration.json")
            if corrections
            else None,
        },
    )
    results.to_csv(output / "adjudicated_results.csv", index=False)
    superseded.to_csv(output / "superseded_cases.csv", index=False)
    windows = window_summary(results)
    windows.to_csv(output / "windows_all.csv", index=False)
    core = computed[computed.experiment.isin(CORE_EXPERIMENTS)].copy()
    core.to_csv(output / "core_all_windows.csv", index=False)
    recovery, episodes = recovery_diagnostics(source, core)
    recovery.to_csv(output / "recovery_all_windows.csv", index=False)
    episodes.to_csv(output / "recovery_episodes.csv", index=False)
    latest = core[core.window.isin(["latest_5y", "latest_10y", "latest_15y"])].copy()
    latest.to_csv(output / "matched_latest_windows.csv", index=False)
    waiting_columns = [
        "asset",
        "experiment",
        "window",
        "start",
        "end",
        "initial_wait_days",
        "initial_wait_censored",
        "average_cash_fraction",
        "ending_wealth",
        "contributed",
        "ending_cash",
        *[f"wealth_gap_at_{m}m_vs_pool" for m in (6, 12, 24)],
        *[f"cash_fraction_at_{m}m" for m in (6, 12, 24)],
    ]
    core[waiting_columns].to_csv(output / "waiting_cost_all.csv", index=False)
    results[
        results.experiment.str.startswith(
            ("neighbor_", "batches_", "extra_", "sensitivity_", "release_")
        )
    ].to_csv(output / "sensitivity_all.csv", index=False)
    results[results.experiment.str.startswith("shiller_")].to_csv(
        output / "revised_valuation_proxy_all.csv", index=False
    )
    events = pd.concat(
        [pd.read_parquet(p).assign(asset=p.parent.name) for p in event_files], ignore_index=True
    )
    events.to_csv(output / "events_all.csv", index=False)
    clustered, leave_out = clustered_event_comparisons(events, config["event_analysis"])
    clustered.to_csv(output / "event_cluster_comparisons.csv", index=False)
    leave_out.to_csv(output / "leave_one_crisis_out.csv", index=False)
    counts = events.groupby(["asset", "stage", "status"]).size().rename("events").reset_index()
    counts.to_csv(output / "event_status_counts.csv", index=False)
    figures = plot_examples(source, output / "figures", results)
    columns = [
        "asset",
        "experiment",
        "window",
        "start",
        "end",
        "annualized_return",
        "xirr",
        "max_drawdown",
        "longest_capital_shortfall_days",
        "initial_wait_days",
        "average_cash_fraction",
        "delta_ending_wealth_vs_pool",
    ]
    text = [
        "# 现金池、压力阶段与长期投资：完整比较",
        "",
        "所有账户包含待投现金和同日期月供，收益已剔除外部入金。等待上限不强制入场。",
        "下表年化为时间加权复利，XIRR为资金加权收益；比例用小数表示。累计投入亏损期与历史高点恢复期分开保存。",
        "同一标的、相同起止日期才能直接比较。美元价格指数不含分红或人民币汇率；基金案例包含已核查公司行动。",
        "全部结果均为已见历史上的探索。滚动窗口重叠，亏损窗口比例不是独立胜率；不据此宣布未来回撤上限。",
        "",
        f"共保留 {len(results)} 条登记结果，其中 {len(computed)} 条计算通过独立账本核对；无收益排名筛选。",
        "",
        "## 预先指定的主要对照",
        "",
        latest[columns].to_markdown(index=False),
        "",
        "## 证据文件",
        "",
        "- windows_all.csv：按5、10、15年分别统计所有策略的最差、中位和最好窗口。",
        "- waiting_cost_all.csv：6、12、24月现金与相对无条件现金池的财富差额，包含一直未入场的账户。",
        "- recovery_all_windows.csv及recovery_episodes.csv：所有历史高点损失区间，日历天数与未恢复删失分别列出，"
        "不把样本截止时的等待下界当作最终回本时间。累计投入亏损另列；未买入而保持现金不代表股票投资无风险。",
        "- event_cluster_comparisons.csv：以同一事件起点计的企稳收益差，未确认入场保留零收益现金。",
        "- leave_one_crisis_out.csv：依次移除一个危机簇；不同市场同期危机仍不独立。",
        "- sensitivity_all.csv：全部参数邻域、费用、月供、批数和发布日期假设。",
        "- revised_valuation_proxy_all.csv：Shiller修订版月度代理，不能视为当年已知PE/PB。",
        "",
        "少于3个危机簇不输出置信区间。其余区间也是探索性描述，未校正多重假设搜索，不作为选优证明。",
        "来源或估值历史不足的实验继续保留暂停状态；本报告不生成实盘交易指令。",
    ]
    (output / "report.md").write_text("\n".join(text) + "\n")
    payloads = {
        str(p.relative_to(output)): sha256_file(p)
        for p in sorted(output.rglob("*"))
        if p.is_file() and p.name != "registration.json"
    }
    write_json(output / "payloads.json", payloads)
    return {
        "directory": str(output),
        "computed": len(computed),
        "registered_records": len(results),
        "event_rows": len(events),
        "cluster_comparisons": len(clustered),
        "figures": figures,
        "formal_accepted": False,
    }


def pair_extension_results(results: pd.DataFrame) -> pd.DataFrame:
    """Compare only identical dates/contributions; factor and core remain matched."""
    validate_window_horizons(results)
    computed = results[results.status.eq("computed")].copy()
    lookup = computed.set_index(["group", "asset", "experiment", "window"])
    if not lookup.index.is_unique:
        raise ValueError("duplicate extension case")
    output = []
    for row in computed.to_dict("records"):
        group, identifier = row["group"], row["experiment"]
        if group == "style":
            suffix = identifier.rsplit("reinvest", 1)[1]
            control_id = f"single_csi300_etf_reinvest{suffix}"
            extra_control = None
        elif group == "currency":
            premium = row["premium"]
            control_id = f"cny_unconditional_premium{premium:g}"
            extra_control = identifier.rsplit("_premium", 1)[0] + "_premium0"
        elif group == "pressure":
            stem = f"{row['factor']}_lag{int(row['lag_sessions'])}"
            core = f"{row['core']:g}"
            control_id = f"{stem}_unconditional_core{core}"
            extra_control = f"{stem}_stabilized_core{core}"
        else:
            raise ValueError("unknown extension group")
        for name, reference in (("vs_pool", control_id), ("vs_extra_control", extra_control)):
            if reference is None:
                continue
            control = lookup.loc[(group, row["asset"], reference, row["window"])]
            if any(row[key] != control[key] for key in ("start", "end", "contributed")):
                raise ValueError("extension comparison has different funding calendars")
            row[f"control_{name}"] = reference
            for metric in ("annualized_return", "max_drawdown", "ending_wealth", "xirr"):
                row[f"delta_{metric}_{name}"] = row[metric] - control[metric]
        output.append(row)
    return pd.DataFrame(output)


def analyze_pool_extensions(source: Path, output: Path) -> dict:
    """Preserve the complete style/FX/factor matrix, including short and blocked history."""
    if output.exists():
        raise ValueError("use a new analysis directory")
    json.loads((source / "summary.json").read_text())  # Require a completed run.
    results = pd.read_parquet(source / "results.parquet")
    if results.status.eq("error").any():
        raise ValueError("adjudicate every failed extension case first")
    paired = pair_extension_results(results)
    if not paired.independent_ledger_verified.fillna(False).all():
        raise ValueError("all accounts need independent reconstruction")
    output.mkdir(parents=True)
    write_json(
        output / "registration.json",
        {
            "source": str(source),
            "registration_sha256": sha256_file(source / "registration.json"),
            "results_sha256": sha256_file(source / "results.parquet"),
            "code": code_revision(),
            "selection": "all_registered_extensions",
        },
    )
    paired.to_csv(output / "paired_all.csv", index=False)
    windows = window_summary(paired)
    windows.to_csv(output / "windows_all.csv", index=False)
    results[~results.status.eq("computed")].to_csv(output / "blocked_all.csv", index=False)
    columns = [
        "asset",
        "experiment",
        "window",
        "start",
        "end",
        "annualized_return",
        "max_drawdown",
        "longest_capital_shortfall_days",
        "ending_wealth",
        "average_cash_fraction",
        "delta_ending_wealth_vs_pool",
        "delta_ending_wealth_vs_extra_control",
    ]
    for group in ("style", "currency", "pressure"):
        selected = paired[paired.group.eq(group)]
        selected.to_csv(output / f"{group}_all.csv", index=False)
        latest = selected[selected.window.isin(["latest_5y", "latest_10y"])]
        # Short listed histories remain visible without being relabelled five years.
        covered = set(zip(latest.asset, latest.experiment, strict=True))
        has_long_window = pd.Series(
            [(a, e) in covered for a, e in zip(selected.asset, selected.experiment, strict=True)],
            index=selected.index,
        )
        short = selected[selected.window.eq("full") & ~has_long_window]
        display = pd.concat([latest, short])
        notes = {
            "style": "对照为同窗口510300单独持有，分红再投/现金分别匹配；这不是历史成交额选基。",
            "currency": "对照为相同溢价下的无条件现金池；extra_control为同策略零溢价情景。"
            "这些是人民币价格指数和假定溢价路径，非真实QDII。"
            "美联储H.10日汇率按周发布，登记中的日频可得时间未经逐份发布档案核验，"
            "不能作为真实交易时点可获得的外汇报价；本组仅保留为非可执行的渠道敏感性。",
            "pressure": "对照为同因子可用时间、同底仓的无条件现金池；extra_control为仅价格企稳。"
            "delta回撤为正表示跌幅较小，不能单独证明择时收益。实际Gamma与被迫平仓未观测。",
        }
        text = [
            f"# {group}：全部预先登记对照",
            "",
            notes[group],
            "",
            "比例用小数。等待现金包括在账户内，收益剔除外部入金；所有结果为已见历史探索。",
            "",
            display[[column for column in columns if column in display]].to_markdown(index=False),
            "",
            "完整窗口、负面结果与短历史保存在对应 *_all.csv；没有按收益筛选。",
        ]
        (output / f"{group}.md").write_text("\n".join(text) + "\n")
    payloads = {
        p.name: sha256_file(p) for p in sorted(output.iterdir()) if p.name != "registration.json"
    }
    write_json(output / "payloads.json", payloads)
    return {
        "directory": str(output),
        "computed": len(paired),
        "all_records": len(results),
        "formal_accepted": False,
    }

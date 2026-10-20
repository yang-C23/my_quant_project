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


def window_summary(results: pd.DataFrame) -> pd.DataFrame:
    """Separate five-, ten- and fifteen-year windows and retain adverse outcomes."""
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
            loss_window_fraction=("loss", "mean"),
            drawdown_over_30pct_fraction=("drawdown_exceeds_30pct", "mean"),
            no_tactical_entry_fraction=("initial_wait_censored", "mean"),
            wait_over_24m_fraction=("wait_longer_than_24m", "mean"),
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
            daily = pd.read_parquet(source / row.result_directory / "daily.parquet")
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


def analyze_pool_run(source: Path, config: dict, output: Path) -> dict:
    """Bind analysis to every saved result, including blocked and failed hypotheses."""
    if output.exists():
        raise ValueError("use a new analysis directory to preserve previous evidence")
    summary = json.loads((source / "summary.json").read_text())
    if any(x.get("status") == "asset_error" for x in summary["outcomes"]):
        raise ValueError("unresolved asset errors: repair and complete the run before analysis")
    results = pd.read_parquet(source / "results.parquet")
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
        },
    )
    windows = window_summary(results)
    windows.to_csv(output / "windows_all.csv", index=False)
    core = computed[computed.experiment.isin(CORE_EXPERIMENTS)].copy()
    core.to_csv(output / "core_all_windows.csv", index=False)
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

#!/usr/bin/env python3
"""Future monthly observations must not change past proxy signals or cash accounts."""

from pathlib import Path
import argparse
import json

import pandas as pd

from quant.data.catalog import DataCatalog
from quant.data.snapshots import sha256_file, write_json
from quant.etl.restart import code_revision
from quant.longterm.cash_pool import PoolPolicy, run_cash_pool
from quant.longterm.current_pe import current_pe_temperature
from quant.longterm.ledger import Costs, dec
from quant.longterm.pool_data import shiller_temperature
from quant.longterm.stages import qualify_value_events


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("data_root", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--cutoff", default="2024-12-31")
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("preserve previous causality checks")
    registration = json.loads((args.source / "registration.json").read_text())
    config = registration["config"]
    bars = pd.read_parquet(args.source / "inputs/sp500.parquet")
    stages = pd.read_parquet(args.source / "sp500/stages.parquet")
    cutoff = pd.Timestamp(args.cutoff)
    shorter_bars, shorter_stages = bars.loc[:cutoff], stages.loc[:cutoff]
    observed = DataCatalog(args.data_root).read(
        "shiller_monthly", version=registration["catalog_versions"]["shiller_monthly"]
    )
    earlier = observed[pd.to_datetime(observed.date) <= cutoff]
    if len(earlier) == len(observed) or len(shorter_bars) == len(bars):
        raise ValueError("cutoff must exclude actual later observations and prices")
    config_costs = config["execution"]
    costs = Costs(
        commission_rate=dec(config_costs["commission_rate"]),
        minimum_commission=dec(config_costs["minimum_commission"]),
        slippage_bps=dec(config_costs["slippage_bps"]),
    )
    temperatures, checks = {}, []
    for experiment in registration["experiments"]:
        identifier = experiment["id"]
        policy = PoolPolicy(**experiment["policy"])
        if policy.entry.endswith("kdj") and not {"high", "low"}.issubset(bars):
            checks.append({"experiment": identifier, "status": "blocked_actual_OHLC_missing"})
            continue
        key = (experiment["metric"], experiment["window"], experiment["observation_lag_months"])
        if key not in temperatures:
            if experiment.get("valuation_source") == "shiller_current_price_proxy":
                proxy_config = registration["current_pe_config"]
                full = current_pe_temperature(bars.close, observed, key[1], key[2], proxy_config)[
                    0
                ].temperature
                prefix = current_pe_temperature(
                    shorter_bars.close, earlier, key[1], key[2], proxy_config
                )[0].temperature
            else:
                full = shiller_temperature(bars, observed, *key, config)
                prefix = shiller_temperature(shorter_bars, earlier, *key, config)
            pd.testing.assert_series_equal(full.loc[:cutoff], prefix, check_exact=True)
            temperatures[key] = full, prefix
        full, prefix = temperatures[key]
        features, short_features = (
            stages.assign(temperature=full),
            shorter_stages.assign(temperature=prefix),
        )
        if policy.event_column and policy.uses_value:
            features = qualify_value_events(features, policy.buy_threshold)
            short_features = qualify_value_events(short_features, policy.buy_threshold)
            pd.testing.assert_frame_equal(features.loc[:cutoff], short_features, check_exact=True)
        start = bars.index[config["validation"]["initial_price_warmup"]]
        result = run_cash_pool(bars, features, policy, symbol="SP500", start=start, costs=costs)
        shorter = run_cash_pool(
            shorter_bars, short_features, policy, symbol="SP500", start=start, costs=costs
        )
        pd.testing.assert_frame_equal(result.daily.loc[:cutoff], shorter.daily, check_exact=True)
        journal = result.journal[pd.to_datetime(result.journal.date) <= cutoff].reset_index(
            drop=True
        )
        pd.testing.assert_frame_equal(
            journal.reindex(columns=shorter.journal.columns),
            shorter.journal.reset_index(drop=True),
            check_dtype=False,
            check_exact=True,
        )
        checks.append(
            {
                "experiment": identifier,
                "status": "passed",
                "prior_trades": int(shorter.metrics["trades"]),
                "known_temperature_sessions": int(prefix.loc[start:].notna().sum()),
            }
        )
    write_json(
        args.output,
        {
            "source": str(args.source),
            "cutoff": args.cutoff,
            "source_registration_sha256": sha256_file(args.source / "registration.json"),
            "script_sha256": sha256_file(Path(__file__)),
            "implementation": code_revision(),
            "all_computable_passed": all(
                row["status"] == "passed" or row["status"].startswith("blocked") for row in checks
            ),
            "comparisons": checks,
            "limitation": "computational_causality_only_not_historical_revision_or_release_proof",
        },
    )
    print(
        json.dumps(
            {"checked": len(checks), "passed": sum(row["status"] == "passed" for row in checks)}
        )
    )


if __name__ == "__main__":
    main()

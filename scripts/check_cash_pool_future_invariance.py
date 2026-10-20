#!/usr/bin/env python3
"""Check frozen real inputs: future bars must not rewrite past signals or accounts.

Run with PYTHONPATH pointing at the study's frozen src directory. The output
records both this script's hash and the actually imported research implementation.
"""

from pathlib import Path
import argparse
import json

import pandas as pd

from quant.data.snapshots import sha256_file, write_json
from quant.etl.restart import code_revision
from quant.longterm.asset_inputs import prepare_action_prices
from quant.longterm.cash_pool import PoolPolicy, run_cash_pool
from quant.longterm.ledger import Costs, dec
from quant.longterm.stages import StageSpec, stage_features


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    if arguments.output.exists():
        raise ValueError("preserve previous verification")
    registration = json.loads((arguments.source / "registration.json").read_text())
    config = registration["config"]
    rows = []
    for path in sorted((arguments.source / "inputs").glob("*.parquet")):
        if path.stem.endswith("_actions"):
            continue
        observed = pd.read_parquet(path)
        action_path = path.with_name(path.stem + "_actions.parquet")
        actions = pd.read_parquet(action_path) if action_path.exists() else None
        cut = max(300, int(len(observed) * 0.75))
        if cut >= len(observed):
            continue
        truncated = observed.iloc[:cut]
        past_actions = (
            actions[pd.to_datetime(actions.ex_date) <= truncated.index[-1]]
            if actions is not None
            else None
        )
        if actions is None:
            bars, signals = observed, observed
            short_bars, short_signals = truncated, truncated
        else:
            bars, signals, _ = prepare_action_prices(observed, actions)
            short_bars, short_signals, _ = prepare_action_prices(truncated, past_actions)
        pd.testing.assert_frame_equal(bars.iloc[:cut], short_bars, check_exact=True)
        pd.testing.assert_frame_equal(signals.iloc[:cut], short_signals, check_exact=True)
        features = stage_features(signals, StageSpec(**config["stages"]))
        short_features = stage_features(short_signals, StageSpec(**config["stages"]))
        pd.testing.assert_frame_equal(features.iloc[:cut], short_features, check_exact=True)
        for entry, core in (("unconditional", 0), ("stabilized", 0), ("stabilized", 0.5)):
            policy = PoolPolicy(**config["funding"], entry=entry, core_fraction=core, exit="none")
            kwargs = {
                "symbol": actions.symbol.iloc[0] if actions is not None else path.stem,
                "start": observed.index[config["validation"]["initial_price_warmup"]],
                "costs": Costs(
                    commission_rate=dec(0.0003), minimum_commission=dec(0), slippage_bps=dec(5)
                ),
                "lot": dec(100 if actions is not None else 0.000001),
            }
            complete = run_cash_pool(bars, features, policy, actions=actions, **kwargs)
            prefix = run_cash_pool(
                short_bars, short_features, policy, actions=past_actions, **kwargs
            )
            pd.testing.assert_frame_equal(
                complete.daily.loc[: truncated.index[-1]], prefix.daily, check_exact=True
            )
            full_journal = complete.journal[
                pd.to_datetime(complete.journal.date) <= truncated.index[-1]
            ].reset_index(drop=True)
            # Full-period journals can gain columns from later action types.
            pd.testing.assert_frame_equal(
                full_journal.reindex(columns=prefix.journal.columns),
                prefix.journal.reset_index(drop=True),
                check_dtype=False,
                check_exact=True,
            )
            rows.append(
                {
                    "asset": path.stem,
                    "entry": entry,
                    "core": core,
                    "cutoff": str(truncated.index[-1].date()),
                    "passed": True,
                }
            )
        print(path.stem, "passed", flush=True)
    write_json(
        arguments.output,
        {
            "source_registration_sha256": sha256_file(arguments.source / "registration.json"),
            "verification_script_sha256": sha256_file(Path(__file__)),
            "research_code": code_revision(),
            "comparisons": rows,
            "all_passed": bool(rows) and all(row["passed"] for row in rows),
        },
    )


if __name__ == "__main__":
    main()

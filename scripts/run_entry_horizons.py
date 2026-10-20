#!/usr/bin/env python3
"""Run through scripts/quant compute-run; never overwrite a prior experiment."""

import argparse
import json
from pathlib import Path

from quant.config import Settings
from quant.longterm.entry_horizons import run_study


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--config", type=Path, default=Path("configs/entry_horizons.json"))
    parser.add_argument("--workers", type=int, required=True)
    parser.add_argument("--replay", type=Path)
    parser.add_argument("--pilot", type=int, default=0)
    args = parser.parse_args()
    print(
        json.dumps(
            run_study(
                Settings().data_root,
                args.destination,
                args.config,
                args.workers,
                replay=args.replay,
                pilot=args.pilot,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

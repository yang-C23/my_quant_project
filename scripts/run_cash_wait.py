#!/usr/bin/env python3
"""Run real cash ETF waiting accounts under scripts/quant compute-run."""

import argparse
import json
from pathlib import Path

from quant.config import Settings
from quant.longterm.cash_wait import run_wait_study


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--config", type=Path, default=Path("configs/cash_wait_bil_v1.json"))
    parser.add_argument("--workers", type=int, required=True)
    parser.add_argument("--replay", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            run_wait_study(
                Settings().data_root,
                args.destination,
                args.config,
                args.workers,
                replay=args.replay,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

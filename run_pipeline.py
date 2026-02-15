from __future__ import annotations

import argparse
import logging

from quant.pipeline import run_pipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run quant pipeline with config")
    parser.add_argument("--config", required=True, help="Pipeline config (yaml/json)")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    args = parse_args()
    outputs = run_pipeline(args.config)

    print("Pipeline completed")
    for key, value in outputs.items():
        print(f"- {key}: {value}")


if __name__ == "__main__":
    main()

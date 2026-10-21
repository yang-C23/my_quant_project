#!/usr/bin/env python3
"""Inspect or run a command within the shared measured compute budget."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from quant.compute import admission_lock, execution_environment, probe_resources, worker_plan
from quant.config import get_settings

ROOT = Path(__file__).resolve().parents[1]


def requested_workers(command: list[str]) -> int | None:
    values = []
    for i, arg in enumerate(command):
        if arg == "--workers":
            if i + 1 == len(command):
                raise ValueError("--workers requires a count or {workers}")
            value = command[i + 1]
        elif arg.startswith("--workers="):
            value = arg.split("=", 1)[1]
        else:
            continue
        if value != "{workers}":
            values.append(int(value))
    if len(values) > 1:
        raise ValueError("duplicate worker options")
    return values[0] if values else None


def save_new(path: Path, payload: dict) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["plan", "run"])
    parser.add_argument("--workload", default="account_batch")
    parser.add_argument("--worker-option", action="store_true")
    parser.add_argument("--output", type=Path)
    argv = sys.argv[1:]
    split = argv.index("--") if "--" in argv else len(argv)
    args = parser.parse_args(argv[:split])
    command = argv[split + 1 :]
    policy_path = ROOT / "configs/compute_defaults.json"
    policy = json.loads(policy_path.read_text())
    if args.workload not in policy["workloads"]:
        parser.error("unknown workload")
    if args.mode == "run" and not command:
        parser.error("run requires -- COMMAND [ARG ...]")

    def prepare():
        resources = probe_resources()
        plan = worker_plan(resources, policy, args.workload, requested_workers(command))
        return {
            "at_utc": datetime.now(timezone.utc).isoformat(),
            "plan": plan,
            "resources": resources,
            "policy_sha256": hashlib.sha256(policy_path.read_bytes()).hexdigest(),
        }

    if args.mode == "plan":
        record = prepare()
        if args.output:
            save_new(args.output, record)
        print(json.dumps(record, ensure_ascii=False, indent=2))
        return 0
    try:
        with admission_lock():
            record = prepare()
            audit = get_settings().data_root / "audits" / "compute"
            audit.mkdir(parents=True, exist_ok=True)
            name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + f"-{os.getpid()}"
            record["command_sha256"] = hashlib.sha256(json.dumps(command).encode()).hexdigest()
            save_new(audit / f"{name}.plan.json", record)
            workers = record["plan"]["workers"]
            print(
                json.dumps(
                    {"compute": record["plan"], "receipt": str(audit / f"{name}.plan.json")}
                ),
                file=sys.stderr,
                flush=True,
            )
            if workers == 0:
                return 75
            if args.worker_option and not any(
                x == "--workers" or x.startswith("--workers=") for x in command
            ):
                command += ["--workers", str(workers)]
            command = [
                str(workers)
                if arg == "{workers}"
                else f"--workers={workers}"
                if arg == "--workers={workers}"
                else arg
                for arg in command
            ]
            started = time.perf_counter()
            try:
                result = subprocess.run(command, env=execution_environment(os.environ, workers))
                returncode, failure = result.returncode, None
            except OSError as exc:
                returncode, failure = 127, type(exc).__name__
            save_new(
                audit / f"{name}.result.json",
                {
                    "plan": str(audit / f"{name}.plan.json"),
                    "returncode": returncode,
                    "failure": failure,
                    "wall_seconds": time.perf_counter() - started,
                },
            )
            return returncode
    except (BlockingIOError, ValueError) as exc:
        print(json.dumps({"status": "defer", "reason": str(exc)}), file=sys.stderr)
        return 75


if __name__ == "__main__":
    raise SystemExit(main())

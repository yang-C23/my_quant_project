#!/usr/bin/env python3
"""Sample a benchmark's process tree and GPU without touching other tasks."""

import argparse
import csv
import json
from pathlib import Path
import subprocess
import threading
import time

import psutil


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command or args.output.exists():
        raise ValueError("a command and a new measurement directory are required")
    args.output.mkdir(parents=True)
    started = time.perf_counter()
    rows = []
    with (args.output / "command.log").open("w") as log:
        child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        root = psutil.Process(child.pid)
        stopped, finished = threading.Event(), []

        def wait_for_child():
            child.wait()
            finished.append(time.perf_counter())
            stopped.set()

        waiter = threading.Thread(target=wait_for_child)
        waiter.start()
        while not stopped.is_set():
            row = {"elapsed": time.perf_counter() - started, "rss": 0, "uss": 0, "cpu_seconds": 0}
            try:
                processes = [root, *root.children(recursive=True)]
            except psutil.Error:
                processes = []
            for process in processes:
                try:
                    memory, cpu = process.memory_full_info(), process.cpu_times()
                    row["rss"] += memory.rss
                    row["uss"] += memory.uss
                    row["cpu_seconds"] += cpu.user + cpu.system
                except psutil.Error:
                    pass
            gpu = subprocess.run(
                [
                    "/usr/lib/wsl/lib/nvidia-smi",
                    "--query-gpu=memory.used,utilization.gpu,power.draw",
                    "--format=csv,noheader,nounits",
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=5,
            )
            if gpu.returncode == 0:
                memory, utilization, power = next(csv.reader(gpu.stdout.splitlines()))
                row.update(
                    gpu_memory_mib=float(memory),
                    gpu_utilization_percent=float(utilization),
                    gpu_power_watts=float(power),
                )
            rows.append(row)
            stopped.wait(0.1)
        waiter.join()
    (args.output / "samples.json").write_text(json.dumps(rows, indent=2) + "\n")
    summary = {
        "command": command,
        "exit_code": child.returncode,
        "wall_including_interpreter_seconds": finished[0] - started,
        "peak_sum_rss_bytes": max(row["rss"] for row in rows),
        "peak_sum_uss_bytes": max(row["uss"] for row in rows),
        "peak_observed_gpu_memory_mib": max(row.get("gpu_memory_mib", 0) for row in rows),
        "peak_observed_gpu_utilization_percent": max(
            row.get("gpu_utilization_percent", 0) for row in rows
        ),
        "sampling": "100ms_sleep_plus_SMI_duration;may_miss_submillisecond_kernel_utilization",
    }
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary))
    if child.returncode:
        raise SystemExit(child.returncode)


if __name__ == "__main__":
    main()

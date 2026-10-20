#!/usr/bin/env python3
"""Record WSL limits and aggregate research load without changing any process."""

import argparse
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import time

import psutil


def capture(command):
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    return {"exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("preserve previous resource samples")
    candidates = []
    for process in psutil.process_iter(["pid", "name"]):
        try:
            command = process.cmdline()
            if process.pid == os.getpid() or not command:
                continue
            if any("quant" in value for value in command) and (
                "python" in process.name() or process.name().startswith("quant")
            ):
                process.cpu_percent()
                candidates.append(process)
        except psutil.Error:
            pass
    time.sleep(2)
    rows = []
    for process in candidates:
        try:
            memory = process.memory_full_info()
            rows.append(
                {
                    "pid": process.pid,
                    "name": process.name(),
                    "cpu_percent": process.cpu_percent(),
                    "rss": memory.rss,
                    "uss": memory.uss,
                    "threads": process.num_threads(),
                    "affinity": process.cpu_affinity(),
                }
            )
        except psutil.Error:
            pass
    limits = {}
    relative = Path("/proc/self/cgroup").read_text().strip().split(":")[-1]
    current = Path("/sys/fs/cgroup") / relative.lstrip("/")
    while current.is_relative_to("/sys/fs/cgroup"):
        for name in ("cpu.max", "memory.max", "pids.max", "cpuset.cpus.effective"):
            path = current / name
            if path.exists():
                limits[str(path)] = path.read_text().strip()
        if current == Path("/sys/fs/cgroup"):
            break
        current = current.parent
    result = {
        "kernel": platform.release(),
        "logical_cpus": psutil.cpu_count(),
        "physical_cpus": psutil.cpu_count(logical=False),
        "affinity": sorted(os.sched_getaffinity(0)),
        "memory": dict(psutil.virtual_memory()._asdict()),
        "swap": dict(psutil.swap_memory()._asdict()),
        "limits": limits,
        "rlimit_as": resource.getrlimit(resource.RLIMIT_AS),
        "rlimit_nproc": resource.getrlimit(resource.RLIMIT_NPROC),
        "research_processes": rows,
        "research_sum_cpu_percent": sum(row["cpu_percent"] for row in rows),
        "research_sum_rss_including_shared": sum(row["rss"] for row in rows),
        "research_sum_uss": sum(row["uss"] for row in rows),
        "research_sum_threads": sum(row["threads"] for row in rows),
        "gpu": capture(["/usr/lib/wsl/lib/nvidia-smi", "-q"]),
        "nvcc": capture(["/usr/local/cuda/bin/nvcc", "--version"]),
        "disk": capture(["df", "-h", str(args.output.parent)]),
        "lscpu": capture(["lscpu"]),
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "logical_cpus",
                    "physical_cpus",
                    "research_sum_cpu_percent",
                    "research_sum_rss_including_shared",
                )
            }
        )
    )


if __name__ == "__main__":
    main()

"""Measured execution defaults and host-wide admission, independent of financial rules."""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import math
import os
from pathlib import Path
import platform
import resource
import shutil
import subprocess
import tempfile

import psutil

GIB = 1024**3
THREAD_VARIABLES = (
    "OPENBLAS_NUM_THREADS",
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "BLIS_NUM_THREADS",
    "ARROW_IO_THREADS",
)
_THREAD_LIMIT = None


def cgroup_limits(root: Path, membership: str) -> dict:
    """Read the tightest cgroup v2 limits from this group and every ancestor."""
    current = root / membership.lstrip("/")
    cpu, memory, raw = [], [], {}
    while current.is_relative_to(root):
        for name in ("cpu.max", "memory.max", "memory.current", "cpuset.cpus.effective"):
            path = current / name
            if path.is_file():
                raw[str(path)] = path.read_text().strip()
        quota = raw.get(str(current / "cpu.max"), "max 100000").split()
        if quota[0] != "max":
            cpu.append(int(quota[0]) / int(quota[1]))
        maximum = raw.get(str(current / "memory.max"), "max")
        used = raw.get(str(current / "memory.current"))
        if maximum != "max" and used is not None:
            memory.append(max(0, int(maximum) - int(used)))
        if current == root:
            break
        current = current.parent
    return {
        "cpu_quota_cores": min(cpu) if cpu else None,
        "memory_headroom_bytes": min(memory) if memory else None,
        "raw": raw,
    }


def research_processes(excluded: set[int]) -> list:
    """Include worker descendants even when spawned argv has no project name."""
    candidates = {}
    for process in psutil.process_iter(["pid", "name"]):
        try:
            if process.pid in excluded or "python" not in process.name().lower():
                continue
            if any("quant" in arg.lower() for arg in process.cmdline()):
                # Spawned Python workers often have no project name in argv.
                # Include descendants and deduplicate across controller matches.
                for related in [process, *process.children(recursive=True)]:
                    if related.pid not in excluded:
                        candidates[related.pid] = related
        except psutil.Error:
            continue
    return list(candidates.values())


def probe_resources(interval: float = 0.25) -> dict:
    """Sample aggregate load without exposing process arguments or changing processes."""
    affinity = sorted(os.sched_getaffinity(0))
    excluded = {os.getpid(), *(p.pid for p in psutil.Process().parents())}
    candidates = research_processes(excluded)
    for process in candidates:
        try:
            process.cpu_percent()
        except psutil.Error:
            pass
    per_cpu = psutil.cpu_percent(interval=interval, percpu=True)
    rows = []
    for process in candidates:
        try:
            memory = process.memory_full_info()
            rows.append(
                {
                    "pid": process.pid,
                    "cpu_percent": process.cpu_percent(),
                    "rss": memory.rss,
                    "uss": getattr(memory, "uss", None),
                    "threads": process.num_threads(),
                }
            )
        except psutil.Error:
            continue
    membership = next(
        (
            line.split(":", 2)[2]
            for line in Path("/proc/self/cgroup").read_text().splitlines()
            if line.startswith("0::")
        ),
        "/",
    )
    limits = cgroup_limits(Path("/sys/fs/cgroup"), membership)
    vm = psutil.virtual_memory()
    headroom = limits["memory_headroom_bytes"]
    smi = shutil.which("nvidia-smi")
    fallback = Path("/usr/lib/wsl/lib/nvidia-smi")
    if smi is None and fallback.exists():
        smi = str(fallback)
    gpu = {"available": False}
    if smi:
        try:
            result = subprocess.run(
                [
                    smi,
                    "--query-gpu=name,memory.total,memory.used,utilization.gpu,driver_version",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            gpu = {
                "available": result.returncode == 0,
                "csv": result.stdout.strip(),
                "fields": ["name", "total_mib", "used_mib", "utilization_percent", "driver"],
            }
        except (OSError, subprocess.TimeoutExpired) as exc:
            gpu = {"available": False, "reason": type(exc).__name__}
    return {
        "kernel": platform.release(),
        "logical_cpus": psutil.cpu_count(),
        "physical_cores": psutil.cpu_count(logical=False),
        "affinity": affinity,
        "cpu_capacity_cores": min(len(affinity), limits["cpu_quota_cores"] or len(affinity)),
        "busy_affinity_cores": sum(per_cpu[i] / 100 for i in affinity if i < len(per_cpu)),
        "memory_total_bytes": vm.total,
        "memory_available_bytes": min(vm.available, headroom)
        if headroom is not None
        else vm.available,
        "cgroup": limits,
        "rlimit_as": resource.getrlimit(resource.RLIMIT_AS),
        "research_processes": rows,
        "research_cpu_cores": sum(p["cpu_percent"] for p in rows) / 100,
        "research_rss_including_shared": sum(p["rss"] for p in rows),
        "research_uss": sum(p["uss"] or 0 for p in rows),
        "gpu": gpu,
        "sample_seconds": interval,
    }


def worker_plan(resources: dict, policy: dict, workload: str, requested: int | None = None) -> dict:
    """Select a measured cap, then reduce it for affinity, quotas, total load and memory."""
    if policy["internal_threads"] != 1:
        raise ValueError("this measured worker policy requires one native thread per worker")
    spec = policy["workloads"][workload]
    capacity = resources["cpu_capacity_cores"]
    reserve = min(policy["reserve_logical_cpus"], max(0, math.floor(capacity) - 1))
    cpu = max(0, math.floor(capacity - reserve - resources["busy_affinity_cores"]))
    memory = max(
        0,
        math.floor(
            (
                resources["memory_available_bytes"] / GIB
                - policy["reserve_memory_gib"]
                - policy["controller_memory_gib"]
            )
            / spec["memory_per_worker_gib"]
        ),
    )
    busy = resources["research_cpu_cores"] >= policy["busy_research_threshold_cores"]
    maximum = min(
        spec["default_workers"],
        cpu,
        memory,
        policy["busy_worker_cap"] if busy else spec["default_workers"],
    )
    if requested is not None and (requested < 1 or requested > maximum):
        raise ValueError(
            f"requested workers={requested} exceeds current allowed range 1..{maximum}"
        )
    return {
        "workload": workload,
        "workers": requested or maximum,
        "status": "ready" if maximum else "defer",
        "cpu_budget_workers": cpu,
        "memory_budget_workers": memory,
        "measured_or_existing_cap": spec["default_workers"],
        "other_research_busy": busy,
        "internal_threads": policy["internal_threads"],
        "gpu_default": policy["gpu_default"],
        "evidence": spec["evidence"],
    }


def execution_environment(env: dict[str, str], workers: int, threads: int = 1) -> dict[str, str]:
    """Set execution-only limits before the child imports numerical libraries."""
    result = dict(env)
    result.update({name: str(threads) for name in THREAD_VARIABLES})
    result.update(QUANT_WORKERS=str(workers), QUANT_COMPUTE_MANAGED="1")
    return result


def configure_native_threads() -> None:
    """Bound native pools in CLI parents; forked workers inherit these limits."""
    global _THREAD_LIMIT
    import pyarrow as pa
    from threadpoolctl import threadpool_limits

    _THREAD_LIMIT = threadpool_limits(limits=1)
    pa.set_cpu_count(1)
    pa.set_io_thread_count(1)


@contextmanager
def admission_lock(path: Path | None = None):
    """Only one managed heavy batch per user; never stop another research process."""
    if path is None:
        directory = Path(tempfile.gettempdir()) / f"quant-compute-{os.getuid()}"
        directory.mkdir(mode=0o700, exist_ok=True)
        path = directory / "admission.lock"
    with path.open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise BlockingIOError(
                "another managed batch is running; retry after it completes"
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)

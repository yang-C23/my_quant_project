"""Resource admission invariants, without running research or depending on host capacity."""

import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from quant.compute import (
    admission_lock,
    cgroup_limits,
    execution_environment,
    research_processes,
    worker_plan,
)


@pytest.fixture
def policy():
    return json.loads(
        (Path(__file__).resolve().parents[2] / "configs/compute_defaults.json").read_text()
    )


def resources(**changes):
    return {
        "cpu_capacity_cores": 24,
        "busy_affinity_cores": 0.0,
        "memory_available_bytes": 40 * 1024**3,
        "research_cpu_cores": 0.0,
        **changes,
    }


def test_idle_uses_measured_cap_and_not_all_logical_threads(policy):
    assert worker_plan(resources(), policy, "account_batch")["workers"] == 12
    assert worker_plan(resources(), policy, "asset_study")["workers"] == 4


@pytest.mark.parametrize(
    "change, expected",
    [
        ({"cpu_capacity_cores": 6}, 4),
        ({"cpu_capacity_cores": 1.5}, 1),
        ({"busy_affinity_cores": 20}, 2),
        ({"research_cpu_cores": 2}, 6),
        ({"memory_available_bytes": 7 * 1024**3}, 5),
    ],
)
def test_reduces_budget_for_real_limits(policy, change, expected):
    assert worker_plan(resources(**change), policy, "account_batch")["workers"] == expected


def test_does_not_force_one_worker_when_memory_is_exhausted(policy):
    state = resources(memory_available_bytes=4 * 1024**3)
    plan = worker_plan(state, policy, "account_batch")
    assert plan["workers"] == 0 and plan["status"] == "defer"
    with pytest.raises(ValueError):
        worker_plan(state, policy, "account_batch", requested=1)


def test_explicit_request_cannot_bypass_shared_budget(policy):
    with pytest.raises(ValueError):
        worker_plan(resources(), policy, "account_batch", requested=16)


def test_parent_cgroup_limits_are_not_ignored(tmp_path):
    child = tmp_path / "user" / "session"
    child.mkdir(parents=True)
    (tmp_path / "cpu.max").write_text("200000 100000")
    (child / "cpu.max").write_text("800000 100000")
    (tmp_path / "memory.max").write_text(str(4 * 1024**3))
    (tmp_path / "memory.current").write_text(str(3 * 1024**3))
    (child / "memory.max").write_text("max")
    limits = cgroup_limits(tmp_path, "/user/session")
    assert limits["cpu_quota_cores"] == 2
    assert limits["memory_headroom_bytes"] == 1024**3


def test_thread_environment_replaces_inherited_oversubscription():
    original = {"OPENBLAS_NUM_THREADS": "64", "OTHER_SETTING": "preserve"}
    actual = execution_environment(original, workers=12)
    assert actual["OPENBLAS_NUM_THREADS"] == actual["OMP_NUM_THREADS"] == "1"
    assert actual["QUANT_WORKERS"] == "12" and actual["OTHER_SETTING"] == "preserve"
    assert original["OPENBLAS_NUM_THREADS"] == "64"


def test_other_process_cannot_admit_a_second_batch_and_lock_releases(tmp_path):
    lock = tmp_path / "lock"
    code = "from pathlib import Path; from quant.compute import admission_lock; "
    code += "import sys\ntry:\n with admission_lock(Path(sys.argv[1])): pass\n"
    code += "except BlockingIOError: sys.exit(75)\n"
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2] / "src"))
    with admission_lock(lock):
        assert subprocess.run([sys.executable, "-c", code, str(lock)], env=env).returncode == 75
    assert subprocess.run([sys.executable, "-c", code, str(lock)], env=env).returncode == 0


def test_spawned_workers_counted_once_without_project_name(monkeypatch):
    worker = SimpleNamespace(
        pid=22,
        name=lambda: "python",
        cmdline=lambda: ["python", "spawn_main"],
        children=lambda **kw: [],
    )
    parent = SimpleNamespace(
        pid=11,
        name=lambda: "python",
        cmdline=lambda: ["quant_research.py"],
        children=lambda **kw: [worker],
    )
    monkeypatch.setattr("quant.compute.psutil.process_iter", lambda fields: [parent, worker])
    assert {p.pid for p in research_processes(set())} == {11, 22}
    assert {p.pid for p in research_processes({22})} == {11}

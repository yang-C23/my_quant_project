import json

from quant.data.research_integrity import verify_research_replay
from quant.data.snapshots import sha256_file


def test_replay_verifies_files_not_only_unchanged_manifests(tmp_path):
    roots = [tmp_path / name for name in ("original", "replay")]
    for root in roots:
        root.mkdir()
        (root / "result.csv").write_text("return\n0.01\n")
        (root / "payloads.json").write_text(
            json.dumps({"result.csv": sha256_file(root / "result.csv")})
        )
        (root / "registration.json").write_text(json.dumps({"code": {"sources": {"x.py": "a"}}}))
    assert verify_research_replay(*roots)["ok"]
    (roots[1] / "result.csv").write_text("return\n99.99\n")
    result = verify_research_replay(*roots)
    assert not result["ok"]
    assert result["changed_payloads"] == []
    assert result["invalid_files"] == [{"run": "replay", "payload": "result.csv"}]


def test_different_registered_source_does_not_pass_replay(tmp_path):
    roots = [tmp_path / name for name in ("original", "replay")]
    for i, root in enumerate(roots):
        root.mkdir()
        (root / "result.csv").write_text("return\n0.01\n")
        (root / "payloads.json").write_text(
            json.dumps({"result.csv": sha256_file(root / "result.csv")})
        )
        (root / "registration.json").write_text(json.dumps({"code": {"sources": {"x.py": str(i)}}}))
    assert not verify_research_replay(*roots)["ok"]

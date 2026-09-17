"""Independent T10 checks for the accepted diff-gate checkers.

The repository fixture is deliberately temporary: these tests never mutate the
checkout that contains the accepted checker implementations.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools.check_spec_contract import check_contract
from tools.check_task_scope import CHECKERS, check_scope, git, spec_digest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write(root: Path, name: str, content: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture
def temporary_harness_repo(tmp_path: Path) -> tuple[Path, str, Path]:
    root = tmp_path / "candidate"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.email", "t10@example.invalid")
    git(root, "config", "user.name", "T10")
    git(root, "config", "core.autocrlf", "false")
    _write(root, "README.md", "fixture\n")
    for checker in CHECKERS:
        _write(root, checker, (PROJECT_ROOT / checker).read_text(encoding="utf-8"))
    _write(root, "spec/models.md", "Known\n")
    manifest = {
        "spec_version": "IR-SIMPLE-1.0.3",
        "tasks": [
            {"id": "T00", "depends_on": [], "modify": [], "create": [".harness/runs/T00/result.json"], "commands": []},
            {"id": "T10", "depends_on": ["T00"], "modify": [],
             "create": ["tests/test_workspace_harness_acceptance.py", ".harness/runs/T10/result.json"], "commands": []},
        ],
    }
    contracts = {"spec_version": "IR-SIMPLE-1.0.3", "model_definitions": "models.md", "routes": [], "frozen_modules": []}
    _write(root, "spec/tasks.json", json.dumps(manifest))
    _write(root, "spec/contracts.json", json.dumps(contracts))
    _write(root, "spec/directory-allowlist.md", "| `tests/test_workspace_harness_acceptance.py` | T10 N |\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "fixture")
    base = git(root, "rev-parse", "HEAD").decode().strip()
    evidence = root / ".git" / "freeze.json"
    evidence.write_text(json.dumps({
        "spec_version": "IR-SIMPLE-1.0.3",
        "spec_sha256": spec_digest(root, "spec"),
        "baseline_commit": base,
        "approval_basis": "T10 fixture authorization",
        "enforcement": "diff-gate-only",
        "checker_sha256": {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in CHECKERS
        },
    }), encoding="utf-8")
    return root, base, evidence


def test_t10_allowlist_accepts_only_its_two_creates(temporary_harness_repo):
    root, _, evidence = temporary_harness_repo
    _write(root, "tests/test_workspace_harness_acceptance.py", "candidate\n")
    _write(root, ".harness/runs/T10/result.json", "{}\n")
    assert check_scope(root, "T10", temporary_harness_repo[1], "spec", evidence) == [
        ".harness/runs/T10/result.json", "tests/test_workspace_harness_acceptance.py"
    ]


def test_t10_rejects_report_sibling_and_preserves_allowlist_boundary(temporary_harness_repo):
    root, base, evidence = temporary_harness_repo
    _write(root, ".harness/runs/T10/debug.log", "leak\n")
    with pytest.raises(ValueError, match="out-of-scope"):
        check_scope(root, "T10", base, "spec", evidence)


def test_t10_rejects_tampered_checker_after_trust_is_frozen(temporary_harness_repo):
    root, base, evidence = temporary_harness_repo
    _write(root, "tests/test_workspace_harness_acceptance.py", "candidate\n")
    checker = root / CHECKERS[0]
    checker.write_text(checker.read_text(encoding="utf-8") + "# tampered\n", encoding="utf-8")
    with pytest.raises(ValueError, match="checker hash"):
        check_scope(root, "T10", base, "spec", evidence)


def test_contract_rejects_casefolded_ownership_collision(temporary_harness_repo):
    root, _, _ = temporary_harness_repo
    manifest_path = root / "spec/tasks.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["tasks"][1]["create"].append("Tests/test_workspace_harness_acceptance.py")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="case collision"):
        check_contract(root)


def test_policy_and_coordinator_records_keep_h04_h05_manual_and_h06_diff_only():
    harness = (PROJECT_ROOT / "spec/06-harness.md").read_text(encoding="utf-8")
    assert "enforcement 固定为 diff-gate-only" in harness
    assert "Docker既不是启动条件也不是验收条件" in harness
    assert "协调者独立核对" in harness
    assert "不声称工具凭据或操作系统进程已被物理销毁" in harness

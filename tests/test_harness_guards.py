"""Adversarial guard tests use temporary repositories, never the user's checkout."""
import hashlib
import json
import os
import subprocess

import pytest

from tools.check_task_scope import CHECKERS, check_scope, git, safe_path, spec_digest
from tools.check_spec_contract import check_contract


def write(root, name, content="changed\n"):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def save(root, name, value):
    return write(root, name, json.dumps(value))


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.email", "guard@example.invalid")
    git(root, "config", "user.name", "Guard Test")
    git(root, "config", "core.autocrlf", "false")
    git(root, "config", "core.filemode", "false")
    write(root, "keep.txt", "original\n")
    write(root, "outside.txt", "outside\n")
    write(root, ".gitignore", "cache/\n")
    for checker in CHECKERS:
        write(root, checker, "# accepted checker\n")
    manifest = {"spec_version": "test", "tasks": [
        {"id": "T00", "depends_on": [], "modify": ["keep.txt"],
         "create": ["new.txt", ".harness/runs/T00/result.json"], "commands": []},
        {"id": "T01", "depends_on": ["T00"], "modify": ["keep.txt"],
         "create": ["later.txt", ".harness/runs/T01/result.json"], "commands": []},
    ]}
    save(root, "spec/tasks.json", manifest)
    save(root, "spec/contracts.json", {"spec_version": "test", "model_definitions": "models.md", "routes": [], "frozen_modules": []})
    write(root, "spec/models.md", "`Known` definition\n")
    write(root, "spec/directory-allowlist.md", "| `keep.txt` | T00 M, T01 M |\n| `new.txt` | T00 N |\n| `later.txt` | T01 N |\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "base")
    base = git(root, "rev-parse", "HEAD").decode().strip()
    evidence = root / ".git/freeze.json"
    evidence.write_text(json.dumps({"spec_version": "test", "spec_sha256": spec_digest(root, "spec"),
        "baseline_commit": base, "approval_basis": "test authorization", "enforcement": "diff-gate-only", "checker_sha256": {}}))
    return root, base, evidence


def check(repo, task="T00"):
    return check_scope(repo[0], task, repo[1], "spec", repo[2])


@pytest.mark.parametrize("state", ["unstaged", "staged", "committed"])
def test_allowed_tracked_changes(repo, state):
    root, _, _ = repo
    write(root, "keep.txt")
    if state != "unstaged":
        git(root, "add", "keep.txt")
    if state == "committed":
        git(root, "commit", "-m", "candidate")
    assert check(repo) == ["keep.txt"]


def test_untracked_allowed_and_ignored_cache(repo):
    write(repo[0], "new.txt")
    write(repo[0], "cache/output.bin")
    assert check(repo) == ["new.txt"]


@pytest.mark.parametrize("state", ["unstaged", "staged", "untracked", "committed"])
def test_outside_allowlist_rejected(repo, state):
    root, _, _ = repo
    name = "rogue.py" if state == "untracked" else "outside.txt"
    write(root, name)
    if state in {"staged", "committed"}:
        git(root, "add", name)
    if state == "committed":
        git(root, "commit", "-m", "candidate")
    with pytest.raises(ValueError, match="out-of-scope"):
        check(repo)


def test_staged_violation_not_hidden_by_worktree_restore(repo):
    root, _, _ = repo
    write(root, "outside.txt")
    git(root, "add", "outside.txt")
    write(root, "outside.txt", "outside\n")
    with pytest.raises(ValueError):
        check(repo)


@pytest.mark.parametrize("operation", ["delete", "rename"])
def test_delete_and_rename_rejected(repo, operation):
    root, _, _ = repo
    if operation == "delete":
        (root / "keep.txt").unlink()
    else:
        git(root, "mv", "keep.txt", "new.txt")
    with pytest.raises(ValueError):
        check(repo)


@pytest.mark.parametrize("name", ["../escape", "/tmp/escape", "E:/escape", "a/../b", "a//b", "a\\b", "a/*.py", "a/", ".git/../x", "KEEP.txt"])
def test_invalid_paths_rejected(repo, name):
    with pytest.raises(ValueError):
        safe_path(repo[0], name)


def test_symlink_escape_rejected(repo, tmp_path):
    target = write(tmp_path, "target.txt")
    try:
        (repo[0] / "new.txt").symlink_to(target)
    except OSError:
        pytest.skip("OS does not grant symlink creation; junction/hardlink tests still run")
    with pytest.raises(ValueError, match="link"):
        check(repo)


def test_hardlink_rejected(repo, tmp_path):
    target = write(tmp_path, "target.txt")
    os.link(target, repo[0] / "new.txt")
    with pytest.raises(ValueError, match="link"):
        check(repo)


@pytest.mark.skipif(os.name != "nt", reason="Windows junction")
def test_junction_rejected(repo, tmp_path):
    target = tmp_path / "external"
    target.mkdir()
    junction = repo[0] / "linked"
    # Fixed command and fixture-only paths; removal uses rmdir on the link itself.
    subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(target)], check=True, capture_output=True)
    try:
        with pytest.raises(ValueError, match="link"):
            safe_path(repo[0], "linked/new.txt")
    finally:
        junction.rmdir()


@pytest.mark.parametrize("mode", ["160000", "120000"])
def test_nonregular_index_rejected(repo, mode):
    root, base, _ = repo
    object_id = base if mode == "160000" else git(root, "hash-object", "-w", "keep.txt").decode().strip()
    git(root, "update-index", "--add", "--cacheinfo", f"{mode},{object_id},new.txt")
    write(root, "new.txt")
    with pytest.raises(ValueError, match="nonregular index"):
        check(repo)


@pytest.mark.parametrize("name", ["spec/models.md", "spec/tasks.json"])
def test_spec_mutation_rejected(repo, name):
    write(repo[0], name)
    with pytest.raises(ValueError, match="spec hash"):
        check(repo)


def test_bootstrap_only_t00(repo):
    write(repo[0], "keep.txt")
    with pytest.raises(ValueError, match="checker hashes"):
        check(repo, "T01")


def test_trusted_checker_hashes_and_mutation(repo):
    root, _, evidence = repo
    freeze = json.loads(evidence.read_text())
    freeze["checker_sha256"] = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in CHECKERS}
    evidence.write_text(json.dumps(freeze))
    write(root, "keep.txt")
    assert check(repo, "T01") == ["keep.txt"]
    write(root, CHECKERS[0], "# bypass\n")
    with pytest.raises(ValueError, match="checker hash"):
        check(repo, "T01")


def test_empty_diff_rejected(repo):
    with pytest.raises(ValueError, match="empty"):
        check(repo)


@pytest.mark.parametrize("kind,name", [("create", "keep.txt"), ("modify", "missing.txt")])
def test_base_file_semantics(repo, kind, name):
    root, _, evidence = repo
    manifest = json.loads((root / "spec/tasks.json").read_text())
    manifest["tasks"][0][kind].append(name)
    save(root, "spec/tasks.json", manifest)
    freeze = json.loads(evidence.read_text())
    freeze["spec_sha256"] = spec_digest(root, "spec")
    evidence.write_text(json.dumps(freeze))
    with pytest.raises(ValueError, match="in base"):
        check(repo)


def test_spec_digest_uses_posix_sort(repo):
    root, _, _ = repo
    write(root, "spec/README.md", "uppercase sort sentinel")
    expected = hashlib.sha256("".join(f"{p.relative_to(root / 'spec').as_posix()}\0{hashlib.sha256(p.read_bytes()).hexdigest()}\n" for p in sorted((root / "spec").iterdir(), key=lambda p: p.name)).encode()).hexdigest()
    assert spec_digest(root, "spec") == expected


def test_contract_valid(repo):
    check_contract(repo[0])


@pytest.mark.parametrize("mutation", ["duplicate", "cycle", "dependency", "glob", "command", "closure", "interface", "report"])
def test_contract_corruption_rejected(repo, mutation):
    root, _, _ = repo
    manifest = json.loads((root / "spec/tasks.json").read_text())
    if mutation == "duplicate":
        manifest["tasks"].append(manifest["tasks"][0])
    elif mutation == "cycle":
        manifest["tasks"][0]["depends_on"] = ["T01"]
    elif mutation == "dependency":
        manifest["tasks"][0]["depends_on"] = ["T99"]
    elif mutation == "glob":
        manifest["tasks"][0]["create"].append("tools/*.py")
    elif mutation == "command":
        manifest["tasks"][0]["commands"] = [["python", "missing.py"]]
    elif mutation == "closure":
        write(root, "spec/directory-allowlist.md", "")
    elif mutation == "interface":
        c = json.loads((root / "spec/contracts.json").read_text())
        c["routes"] = [{"method": "GET", "path": "/a", "request": None, "response": "Unknown"}]
        save(root, "spec/contracts.json", c)
    elif mutation == "report":
        manifest["tasks"][0]["create"].remove(".harness/runs/T00/result.json")
    save(root, "spec/tasks.json", manifest)
    with pytest.raises(ValueError):
        check_contract(root)

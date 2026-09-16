"""Diff-only task guard. This does not provide OS write isolation."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess

CHECKERS = ("tools/check_task_scope.py", "tools/check_spec_contract.py")


def git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True).stdout


def safe_path(root: Path, name: str) -> Path:
    if (not isinstance(name, str) or not name or "\\" in name or ":" in name
            or any(c in name for c in "*?[]\x00") or name.startswith("/")
            or any(p in ("", ".", "..") for p in name.split("/"))):
        raise ValueError(f"unsafe path: {name!r}")
    path = root.joinpath(*PurePosixPath(name).parts)
    current = root
    for part in PurePosixPath(name).parts:
        if current.is_dir():
            matches = [p.name for p in current.iterdir() if p.name.casefold() == part.casefold()]
            if matches and matches != [part]:
                raise ValueError(f"path case mismatch: {name}")
        current = current / part
        if current.exists() or current.is_symlink():
            info = current.lstat()
            if (stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400
                    or (stat.S_ISREG(info.st_mode) and info.st_nlink > 1)):
                raise ValueError(f"link/reparse point forbidden: {name}")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"external path: {name}")
    return path


def spec_digest(root: Path, spec_root: str) -> str:
    directory = safe_path(root, spec_root)
    entries = []
    for parent, dirs, files in os.walk(directory, followlinks=False):
        for name in dirs + files:
            path = Path(parent) / name
            relative = path.relative_to(root).as_posix()
            safe_path(root, relative)
            if path.is_file():
                entries.append((path.relative_to(directory).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()))
            elif not path.is_dir():
                raise ValueError(f"nonregular spec entry: {relative}")
    if not entries:
        raise ValueError("empty spec")
    return hashlib.sha256("".join(f"{p}\0{h}\n" for p, h in sorted(entries)).encode()).hexdigest()


def changes(root: Path, *args: str) -> list[tuple[str, str]]:
    fields = git(root, "diff", "--name-status", "-z", "--find-renames", *args, "--").decode("utf-8").split("\0")
    result = []
    i = 0
    while i < len(fields) and fields[i]:
        status = fields[i][0]
        count = 2 if status in "RC" else 1
        for name in fields[i + 1:i + 1 + count]:
            result.append((status, name))
        i += count + 1
    return result


def check_scope(root: Path, task_id: str, base: str, spec_root: str, evidence: Path) -> list[str]:
    root = root.resolve()
    if not base or base.startswith("-"):
        raise ValueError("base required")
    base_sha = git(root, "rev-parse", "--verify", f"{base}^{{commit}}").decode().strip()
    git(root, "merge-base", "--is-ancestor", base_sha, "HEAD")
    freeze = json.loads(evidence.read_text(encoding="utf-8-sig"))
    if freeze["enforcement"] != "diff-gate-only" or not freeze["approval_basis"]:
        raise ValueError("invalid freeze evidence")
    baseline = freeze["baseline_commit"]
    if not isinstance(baseline, str) or len(baseline) != 40 or any(c not in "0123456789abcdef" for c in baseline):
        raise ValueError("invalid frozen baseline")
    git(root, "merge-base", "--is-ancestor", baseline, base_sha)
    if spec_digest(root, spec_root) != freeze["spec_sha256"]:
        raise ValueError("frozen spec hash mismatch")
    manifest = json.loads(safe_path(root, f"{spec_root}/tasks.json").read_text(encoding="utf-8"))
    if manifest["spec_version"] != freeze["spec_version"]:
        raise ValueError("spec version mismatch")
    hashes = freeze["checker_sha256"]
    if not (task_id == "T00" and hashes == {}):
        if set(hashes) != set(CHECKERS):
            raise ValueError("both trusted checker hashes required")
        for name in CHECKERS:
            if hashlib.sha256(safe_path(root, name).read_bytes()).hexdigest() != hashes[name]:
                raise ValueError(f"frozen checker hash mismatch: {name}")
    tasks = [t for t in manifest["tasks"] if t["id"] == task_id]
    if len(tasks) != 1:
        raise ValueError("unknown/duplicate task")
    task = tasks[0]
    tree = {}
    for record in git(root, "ls-tree", "-rz", base_sha).split(b"\0"):
        if record:
            meta, name = record.decode().split("\t", 1)
            tree[name] = meta.split()[0]
    allowed = set(task["modify"] + task["create"])
    for name in allowed:
        safe_path(root, name)
        if name in task["create"] and name in tree:
            raise ValueError(f"create already exists in base: {name}")
        if name in task["modify"] and name not in tree:
            raise ValueError(f"modify missing in base: {name}")
    changed = changes(root, base_sha, "HEAD") + changes(root, "--cached", "HEAD") + changes(root)
    changed += [("A", p) for p in git(root, "ls-files", "--others", "--exclude-standard", "-z").decode().split("\0") if p]
    if not changed and task.get("code_changes_allowed", True):
        raise ValueError("empty task diff")
    for status, name in changed:
        path = safe_path(root, name)
        if status in "DRCU" or name not in allowed:
            raise ValueError(f"out-of-scope or forbidden operation: {status} {name}")
        if name == spec_root or name.startswith(spec_root + "/"):
            raise ValueError("Spec is readonly")
        if task_id != "T00" and name in CHECKERS:
            raise ValueError("checkers are readonly")
        if not path.is_file():
            raise ValueError(f"not a regular file (submodule/directory/deletion): {name}")
    for record in git(root, "ls-files", "--stage", "-z").split(b"\0"):
        if record:
            meta, name = record.decode().split("\t", 1)
            if name in {p for _, p in changed} and meta.split()[0] not in ("100644", "100755"):
                raise ValueError(f"nonregular index entry: {name}")
    return sorted({p for _, p in changed})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--spec-root", default="spec")
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args()
    try:
        root = Path(git(Path.cwd(), "rev-parse", "--show-toplevel").decode().strip())
        paths = check_scope(root, args.task, args.base, args.spec_root, args.evidence)
        print(json.dumps({"enforcement": "diff-gate-only", "changed_files": paths}))
        return 0
    except (ValueError, KeyError, TypeError, OSError, subprocess.CalledProcessError) as exc:
        print(f"Task scope rejected: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

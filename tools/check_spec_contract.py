"""Validate static Spec references; behavioral acceptance remains in task tests."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess

try:
    from tools.check_task_scope import git, safe_path, spec_digest
except ModuleNotFoundError:
    from check_task_scope import git, safe_path, spec_digest


def check_contract(root: Path, spec_root: str = "spec") -> None:
    directory = safe_path(root, spec_root)
    spec_digest(root, spec_root)  # Reject links and nonregular entries too.
    manifest = json.loads((directory / "tasks.json").read_text(encoding="utf-8"))
    contracts = json.loads((directory / "contracts.json").read_text(encoding="utf-8"))
    if manifest["spec_version"] != contracts["spec_version"]:
        raise ValueError("contract version mismatch")
    tasks = manifest["tasks"]
    by_id = {t["id"]: t for t in tasks}
    if not tasks or len(by_id) != len(tasks):
        raise ValueError("duplicate or empty task IDs")
    visited, active = set(), set()

    def visit(task_id: str) -> None:
        if task_id not in by_id or task_id in active:
            raise ValueError(f"unknown dependency or cycle: {task_id}")
        if task_id in visited:
            return
        active.add(task_id)
        for dep in by_id[task_id]["depends_on"]:
            visit(dep)
        active.remove(task_id)
        visited.add(task_id)

    ownership, creates, folded = {}, {}, {}
    for task in tasks:
        task_id = task["id"]
        if not re.fullmatch(r"T\d{2}", task_id):
            raise ValueError(f"invalid task ID: {task_id}")
        visit(task_id)
        local = set()
        for kind, marker in (("modify", "M"), ("create", "N")):
            for name in task[kind]:
                safe_path(root, name)
                if name in local or name == spec_root or name.startswith(spec_root + "/"):
                    raise ValueError(f"duplicate or readonly permission: {name}")
                local.add(name)
                if name.casefold() in folded and folded[name.casefold()] != name:
                    raise ValueError(f"case collision: {name}")
                folded[name.casefold()] = name
                ownership.setdefault(name, []).append(f"{task_id} {marker}")
                if kind == "create":
                    if name in creates:
                        raise ValueError(f"multiple creators: {name}")
                    creates[name] = task_id
    for name in ownership:
        if not safe_path(root, name).is_file() and name not in creates:
            raise ValueError(f"unowned missing file: {name}")
    for name in ownership:
        if any(name.startswith(other + "/") for other in ownership):
            raise ValueError(f"file/directory conflict: {name}")
    table = (directory / "directory-allowlist.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\| `([^`]+)` \| ([^|]+) \|$", table, re.MULTILINE)
    actual = {name: re.findall(r"T\d{2} [MN]", owners) for name, owners in rows}
    source_ownership = {name: owners for name, owners in ownership.items() if not name.startswith(".harness/")}
    for task in tasks:
        reports = [name for name in task["create"] if name.startswith(".harness/")]
        if reports != [f".harness/runs/{task['id']}/result.json"]:
            raise ValueError("each task must own exactly its report path")
    if len(rows) != len(actual) or actual != source_ownership:
        raise ValueError("directory allowlist is not closed over manifest ownership")
    for task in tasks:
        for name in task.get("read_inputs", []):
            if not safe_path(root, name).is_file() and name not in creates:
                raise ValueError(f"dangling input: {name}")
        for argv in task["commands"]:
            if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
                raise ValueError("command must be a nonempty argv array")
            for token in argv:
                if "${" in token or token.startswith("-"):
                    continue
                if token.endswith((".py", ".json", ".ts", ".tsx")):
                    name = "frontend/" + token if "--prefix" in argv and token.startswith("src/") else token
                    if not safe_path(root, name).is_file() and name not in creates:
                        raise ValueError(f"dangling command/test path: {name}")
    for name in contracts["frozen_modules"]:
        safe_path(root, name)
        if name not in ownership:
            raise ValueError(f"unowned frozen module: {name}")
    definition = safe_path(root, f"{spec_root}/{contracts['model_definitions']}").read_text(encoding="utf-8")
    seen = set()
    for route in contracts["routes"]:
        key = (route["method"], route["path"])
        if key in seen or route["method"] not in {"GET", "POST", "PATCH", "PUT", "DELETE"} or not route["path"].startswith("/"):
            raise ValueError(f"invalid/duplicate route: {key}")
        seen.add(key)
        for field in ("request", "response"):
            symbol = route[field]
            if symbol is not None and not re.search(r"\b" + re.escape(symbol) + r"\b", definition):
                raise ValueError(f"dangling interface reference: {symbol}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec-root", default="spec")
    args = parser.parse_args()
    try:
        root = Path(git(Path.cwd(), "rev-parse", "--show-toplevel").decode().strip())
        check_contract(root, args.spec_root)
        print("Spec contract check passed (static references only).")
        return 0
    except (ValueError, KeyError, TypeError, OSError, subprocess.CalledProcessError) as exc:
        print(f"Spec contract rejected: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

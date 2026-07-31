"""检查关键代码变更是否包含对应主题的文档更新。"""

from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = PROJECT_ROOT / "docs" / "code-document-map.json"


def _git_paths(*arguments: str) -> set[str]:
    """执行只读 Git 查询，并统一为正斜杠仓库相对路径。"""

    result = subprocess.run(
        ["git", *arguments],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return {
        line.strip().replace("\\", "/")
        for line in result.stdout.splitlines()
        if line.strip()
    }


def changed_paths(base_ref: str | None) -> set[str]:
    """返回相对基线、工作区和未跟踪文件的变更并集。"""

    paths = (
        _git_paths("diff", "--name-only", f"{base_ref}...HEAD")
        if base_ref
        else set()
    )
    paths.update(_git_paths("diff", "--name-only", "HEAD"))
    paths.update(_git_paths("ls-files", "--others", "--exclude-standard"))
    return paths


def missing_document_updates(
    paths: set[str],
    groups: list[dict],
) -> list[tuple[str, list[str], list[str]]]:
    """找出发生代码变化、但映射文档没有任何更新的主题组。"""

    missing: list[tuple[str, list[str], list[str]]] = []
    for group in groups:
        changed_code = sorted(
            path
            for path in paths
            if any(
                fnmatch.fnmatchcase(path, pattern)
                for pattern in group["code_patterns"]
            )
        )
        if not changed_code:
            continue
        changed_docs = sorted(set(group["documents"]) & paths)
        if not changed_docs:
            missing.append(
                (group["name"], changed_code, group["documents"])
            )
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Require documentation updates for mapped code changes."
    )
    parser.add_argument("--base-ref")
    parser.add_argument(
        "--allow-code-only",
        action="store_true",
        help="Explicitly allow a verified behavior-preserving code-only change.",
    )
    args = parser.parse_args()

    mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    paths = changed_paths(args.base_ref)
    missing = missing_document_updates(paths, mapping["groups"])
    if not missing or args.allow_code_only:
        print("Documentation sync check passed.")
        return 0

    print("Documentation sync check failed:")
    for name, code_paths, expected_docs in missing:
        print(f"\n[{name}] changed code:")
        for path in code_paths:
            print(f"  - {path}")
        print("Update at least one mapped document:")
        for path in expected_docs:
            print(f"  - {path}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

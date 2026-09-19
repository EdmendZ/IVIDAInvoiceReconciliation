"""IDE-friendly entrypoint for the accepted Windows local demo launcher."""

from __future__ import annotations

import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent


def build_start_command(project_root: Path = PROJECT_ROOT) -> list[str]:
    """Return the fixed command that delegates to the existing launcher."""

    return [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(project_root / "start_local_demo.ps1"),
    ]


def main() -> None:
    completed = subprocess.run(
        build_start_command(),
        cwd=PROJECT_ROOT,
        check=False,
    )
    raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()

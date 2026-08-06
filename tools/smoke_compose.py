from __future__ import annotations

import argparse
import json
import time
import urllib.request


def wait_json(url: str, timeout_seconds: int = 60) -> dict:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            last_error = exc
            time.sleep(1)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error}")


def wait_text(url: str, timeout_seconds: int = 60) -> str:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                return response.read().decode("utf-8")
        except Exception as exc:
            last_error = exc
            time.sleep(1)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="http://127.0.0.1:8200")
    parser.add_argument("--frontend-url", default="http://127.0.0.1:5274")
    args = parser.parse_args()

    health = wait_json(f"{args.api_url}/api/health")
    if health.get("status") != "ok":
        raise RuntimeError(f"Unexpected API health response: {health}")
    html = wait_text(args.frontend_url)
    if '<div id="root">' not in html:
        raise RuntimeError("Frontend root element is missing")
    print("Compose smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

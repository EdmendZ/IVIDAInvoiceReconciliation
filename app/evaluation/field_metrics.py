from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from app.evaluation.models import ComparisonCounts


def _normalized_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value).strip()).casefold()


def _equivalent(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is right
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except (InvalidOperation, ValueError):
        return _normalized_text(left) == _normalized_text(right)


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "items":
                continue
            path = f"{prefix}.{key}" if prefix else key
            result.update(_flatten(item, path))
        return result
    if isinstance(value, list):
        for index, item in enumerate(value):
            path = f"{prefix}.{index}" if prefix else str(index)
            result.update(_flatten(item, path))
        return result
    result[prefix] = value
    return result


def _line_key(item: dict) -> str:
    sku = item.get("sku")
    if sku:
        return f"sku:{_normalized_text(sku)}"
    return f"description:{_normalized_text(item.get('description', ''))}"


def _canonical_evidence_paths(
    evidence_paths: set[str],
    predicted_items: list[dict],
) -> set[str]:
    result: set[str] = set()
    indexed_items = {
        str(index): _line_key(item)
        for index, item in enumerate(predicted_items)
    }
    for original in evidence_paths:
        path = original.replace("[", ".").replace("]", "")
        if path.startswith("document."):
            path = path.removeprefix("document.")
        match = re.fullmatch(r"items\.(\d+)\.(.+)", path)
        if match and match.group(1) in indexed_items:
            result.add(
                f"items.{indexed_items[match.group(1)]}.{match.group(2)}"
            )
        else:
            result.add(path)
    return result


def compare_documents(
    predicted: dict,
    gold: dict,
    evidence_paths: set[str] | None = None,
) -> ComparisonCounts:
    evidence_paths = evidence_paths or set()
    errors: list[str] = []
    correct = 0
    total = 0

    predicted_scalars = _flatten(predicted)
    gold_scalars = _flatten(gold)
    for path, expected in gold_scalars.items():
        total += 1
        actual = predicted_scalars.get(path)
        if _equivalent(actual, expected):
            correct += 1
        else:
            errors.append(f"{path}: expected={expected!r} actual={actual!r}")

    predicted_lines = {
        _line_key(item): item for item in predicted.get("items", [])
    }
    gold_lines = {_line_key(item): item for item in gold.get("items", [])}
    matched_keys = predicted_lines.keys() & gold_lines.keys()
    missing_keys = gold_lines.keys() - predicted_lines.keys()
    extra_keys = predicted_lines.keys() - gold_lines.keys()

    evidence_total_paths = set(gold_scalars)
    for key in sorted(matched_keys):
        predicted_fields = _flatten(predicted_lines[key], f"items.{key}")
        gold_fields = _flatten(gold_lines[key], f"items.{key}")
        evidence_total_paths.update(gold_fields)
        for path, expected in gold_fields.items():
            total += 1
            actual = predicted_fields.get(path)
            if _equivalent(actual, expected):
                correct += 1
            else:
                errors.append(
                    f"{path}: expected={expected!r} actual={actual!r}"
                )

    errors.extend(f"missing line {key}" for key in sorted(missing_keys))
    errors.extend(f"extra line {key}" for key in sorted(extra_keys))

    normalized_evidence = _canonical_evidence_paths(
        evidence_paths,
        predicted.get("items", []),
    )
    evidence_covered = sum(
        1
        for path in evidence_total_paths
        if path in normalized_evidence
        or any(item.endswith(f".{path}") for item in normalized_evidence)
    )
    return ComparisonCounts(
        correct=correct,
        total=total,
        matched_lines=len(matched_keys),
        missing_lines=len(missing_keys),
        extra_lines=len(extra_keys),
        evidence_covered=evidence_covered,
        evidence_total=len(evidence_total_paths),
        errors=errors,
    )

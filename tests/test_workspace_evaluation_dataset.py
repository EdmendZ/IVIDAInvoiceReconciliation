"""Workspace matching and comparison checks over the local Gold evaluation set.

The Gold JSON files represent trusted, already extracted document payloads.  These
tests therefore exercise the deterministic workspace rules; they do not claim to
evaluate OCR or an external model.  The ignored local dataset is optional in a
fresh checkout, so the module skips clearly when it is not available.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

from app.domain.workspace import RevisionView
from app.services.workspace_comparison import compare_workspace
from app.services.workspace_matching import select_candidates
from tools.validate_evaluation_dataset import validate as validate_dataset


ROOT = Path(__file__).resolve().parents[1]
DATASET_ROOT = ROOT / "evaluation_data"
MANIFEST_PATH = DATASET_ROOT / "manifest.json"

if not DATASET_ROOT.exists():
    pytestmark = pytest.mark.skip(
        reason="optional local evaluation_data is not present; no data result is claimed"
    )


EXPECTED = {
    "case-01-exact-single": {
        "match_status": "selected",
        "selected_count": 1,
        "outcome": "consistent",
        "different_lines": 0,
        "unverified_lines": 0,
    },
    "case-02-exact-split-delivery": {
        "match_status": "selected",
        "selected_count": 2,
        "outcome": "consistent",
        "different_lines": 0,
        "unverified_lines": 0,
    },
    "case-03-short-delivery": {
        "match_status": "selected",
        "selected_count": 1,
        "outcome": "difference",
        "different_lines": 1,
        "unverified_lines": 0,
    },
    "case-04-price-variance": {
        "match_status": "selected",
        "selected_count": 1,
        "outcome": "difference",
        "different_lines": 1,
        "unverified_lines": 0,
    },
    "case-05-invoice-only-line": {
        "match_status": "selected",
        "selected_count": 1,
        "outcome": "difference",
        "different_lines": 1,
        "unverified_lines": 1,
    },
    "case-06-receive-note-only-line": {
        "match_status": "selected",
        "selected_count": 1,
        "outcome": "difference",
        "different_lines": 1,
        "unverified_lines": 1,
    },
    "case-07-rounding-tolerance": {
        "match_status": "selected",
        "selected_count": 1,
        "outcome": "consistent",
        "different_lines": 0,
        "unverified_lines": 0,
    },
    "case-08-po-mismatch": {
        "match_status": "needs_selection",
        "selected_count": 0,
        "outcome": None,
        "different_lines": None,
        "unverified_lines": None,
    },
}

LINE_EXPECTATIONS = {
    "case-03-short-delivery": ("MOZZ-2", "different"),
    "case-04-price-variance": ("BOX-12", "different"),
    "case-05-invoice-only-line": ("BASIL-1", "invoice_only"),
    "case-06-receive-note-only-line": ("GARLIC-1", "receive_only"),
}


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _request(case_id: str) -> dict:
    path = DATASET_ROOT / "gold" / case_id / "reconciliation_request.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _revision(case_id: str, payload: dict, role: str, index: int) -> RevisionView:
    document_id = uuid5(
        NAMESPACE_URL,
        f"ivida-evaluation:{case_id}:{role}:{index}:{payload['document_number']}",
    )
    revision_id = uuid5(NAMESPACE_URL, f"{document_id}:revision:1")
    return RevisionView(
        document_id=str(document_id),
        revision_id=str(revision_id),
        sequence=1,
        origin="extracted",
        payload=payload,
        created_at=datetime(2026, 9, 18, tzinfo=UTC),
    )


def test_dataset_manifest_and_pdf_sources_are_complete() -> None:
    manifest = _manifest()
    assert manifest["synthetic"] is True
    assert manifest["case_count"] == 8
    assert len(manifest["cases"]) == len(EXPECTED)

    # Reuse the existing source-support and reconciliation dataset validator.
    # It checks all 17 PDFs, Gold files, printed critical fields and legacy line
    # summaries without involving OCR, models, or TapTouch.
    validate_dataset()


@pytest.mark.parametrize("case_id", tuple(EXPECTED))
def test_gold_request_drives_workspace_rules(case_id: str) -> None:
    data = _request(case_id)
    invoice = _revision(case_id, data["invoice"], "invoice", 0)
    receivings = [
        _revision(case_id, payload, "receive_note", index)
        for index, payload in enumerate(data["receive_notes"], start=1)
    ]

    proposal = select_candidates(invoice, receivings, set())
    expected = EXPECTED[case_id]
    assert proposal.status.value == expected["match_status"]
    assert len(proposal.selected_document_ids) == expected["selected_count"]
    assert proposal.selected_document_ids == sorted(proposal.selected_document_ids)

    if case_id == "case-08-po-mismatch":
        candidate = proposal.candidates[0]
        assert candidate.eligible is False
        assert "PO_CONFLICT" in candidate.reason_codes
        assert proposal.selected_document_ids == []

        # A reviewer may explicitly choose the otherwise matching source.  The
        # comparison remains deterministic, while automatic matching stays gated.
        manual_result = compare_workspace(invoice, receivings)
        assert manual_result.outcome.value == "consistent"
        return

    selected = [
        revision
        for revision in receivings
        if revision.document_id in proposal.selected_document_ids
    ]
    result = compare_workspace(invoice, selected)
    assert result.outcome.value == expected["outcome"]
    assert result.summary.different_lines == expected["different_lines"]
    assert result.summary.unverified_lines == expected["unverified_lines"]

    if case_id == "case-02-exact-split-delivery":
        assert all(len(line.receive_lines) == 2 for line in result.lines)
    if case_id == "case-07-rounding-tolerance":
        yeast = next(line for line in result.lines if line.sku == "YEAST-500")
        assert yeast.price.status.value == "within_tolerance"

    if case_id in LINE_EXPECTATIONS:
        sku, status = LINE_EXPECTATIONS[case_id]
        line = next(line for line in result.lines if line.sku == sku)
        assert line.status.value == status

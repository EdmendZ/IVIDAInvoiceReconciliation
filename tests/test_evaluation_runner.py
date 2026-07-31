import json
from pathlib import Path

from app.domain.documents import Invoice
from app.domain.normalization import FieldEvidence, NormalizationResult
from app.domain.parsing import (
    ParserPollResult,
    ParserSubmission,
    ParseResult,
    ParseState,
)
from app.evaluation.cache import MinerUParseCache
from app.evaluation.runner import ExtractionEvaluationRunner


class Parser:
    provider_name = "mineru"
    model_name = "vlm"

    def __init__(self) -> None:
        self.submit_count = 0

    def submit(self, **kwargs) -> ParserSubmission:
        self.submit_count += 1
        return ParserSubmission(remote_job_id="remote-1")

    def poll(self, remote_job_id: str) -> ParserPollResult:
        return ParserPollResult(
            state=ParseState.SUCCEEDED,
            progress=100,
            result=ParseResult(
                provider="mineru",
                model_name="vlm",
                remote_task_id=remote_job_id,
                markdown="# Invoice",
                content_blocks=[],
                tables=[],
                page_count=1,
                artifact_archive=b"zip",
            ),
        )


class Normalizer:
    provider_name = "fixture"
    model_name = "fixture-v1"
    prompt_version = "sha256:fixture"

    def normalize(self, **kwargs) -> NormalizationResult:
        return NormalizationResult(
            document=Invoice.model_validate(
                {
                    "document_type": "invoice",
                    "document_number": "INV-1",
                    "currency": "AUD",
                    "total": "11.00",
                    "items": [
                        {
                            "sku": "A",
                            "description": "Cheese",
                            "quantity": "1",
                            "unit_price": "10.00",
                            "line_total": "10.00",
                        }
                    ],
                }
            ),
            evidence=[
                FieldEvidence(
                    field_path="document_number",
                    source_text="INV-1",
                )
            ],
            raw_response={},
        )


class FailingNormalizer(Normalizer):
    def normalize(self, **kwargs) -> NormalizationResult:
        raise ValueError("malformed model JSON")


def _dataset(root: Path) -> Path:
    source_directory = root / "source_documents" / "pdf" / "case-1"
    gold_directory = root / "gold" / "case-1"
    source_directory.mkdir(parents=True)
    gold_directory.mkdir(parents=True)
    (source_directory / "invoice__INV-1.pdf").write_bytes(b"%PDF fixture")
    gold = {
        "document_type": "invoice",
        "document_number": "INV-1",
        "currency": "AUD",
        "total": "11.00",
        "items": [
            {
                "sku": "A",
                "description": "Cheese",
                "quantity": "1",
                "unit_price": "10.00",
                "line_total": "10.00",
            }
        ],
    }
    (gold_directory / "invoice__INV-1.json").write_text(
        json.dumps(gold),
        encoding="utf-8",
    )
    manifest = {
        "cases": [
            {
                "case_id": "case-1",
                "documents": [
                    "source_documents/pdf/case-1/invoice__INV-1.pdf"
                ],
            }
        ]
    }
    path = root / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_runner_reuses_parse_cache(tmp_path: Path) -> None:
    parser = Parser()
    manifest = _dataset(tmp_path / "dataset")
    runner = ExtractionEvaluationRunner(
        parser=parser,
        normalizer=Normalizer(),
        cache=MinerUParseCache(tmp_path / "cache"),
        poll_interval_seconds=0,
    )

    first, _, _ = runner.run(
        manifest_path=manifest,
        variant_name="baseline",
        output_root=tmp_path / "results",
    )
    second, documents, _ = runner.run(
        manifest_path=manifest,
        variant_name="baseline",
        output_root=tmp_path / "results",
    )

    assert parser.submit_count == 1
    assert first.field_micro_accuracy == 1
    assert second.parser_cache_hits == 1
    assert documents[0].parser_cache_hit is True


def test_runner_resumes_pending_mineru_job_without_resubmitting(
    tmp_path: Path,
) -> None:
    parser = Parser()
    manifest = _dataset(tmp_path / "dataset")
    source = (
        tmp_path
        / "dataset"
        / "source_documents"
        / "pdf"
        / "case-1"
        / "invoice__INV-1.pdf"
    ).read_bytes()
    cache = MinerUParseCache(tmp_path / "cache")
    cache.put_pending(source, "existing-remote-job")
    runner = ExtractionEvaluationRunner(
        parser=parser,
        normalizer=Normalizer(),
        cache=cache,
        poll_interval_seconds=0,
    )

    runner.run(
        manifest_path=manifest,
        variant_name="baseline",
        output_root=tmp_path / "results",
    )

    assert parser.submit_count == 0
    assert cache.get_pending(source) is None


def test_runner_records_document_failure_instead_of_aborting(
    tmp_path: Path,
) -> None:
    manifest = _dataset(tmp_path / "dataset")
    runner = ExtractionEvaluationRunner(
        parser=Parser(),
        normalizer=FailingNormalizer(),
        cache=MinerUParseCache(tmp_path / "cache"),
        poll_interval_seconds=0,
    )

    summary, documents, output_directory = runner.run(
        manifest_path=manifest,
        variant_name="broken-json",
        output_root=tmp_path / "results",
    )

    assert summary.document_count == 1
    assert summary.schema_valid_rate == 0
    assert documents[0].schema_valid is False
    assert documents[0].error_stage == "normalizer"
    assert documents[0].error_code == "ValueError"
    assert "malformed model JSON" in documents[0].error_message
    assert (output_directory / "documents.jsonl").exists()

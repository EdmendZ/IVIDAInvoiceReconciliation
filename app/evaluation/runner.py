"""可复现的抽取评测运行器。

MinerU 结果按原件哈希缓存；每份文档独立记录失败，避免只统计成功样本造成
幸存者偏差。输出保存预测 JSON，指标可在不重复调用模型的情况下离线复算。
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from statistics import median
from time import perf_counter
from collections.abc import Callable

from app.domain.documents import DocumentType
from app.domain.normalization import NormalizationProvider
from app.domain.parsing import AsyncDocumentParser, ParseResult, ParseState
from app.evaluation.cache import MinerUParseCache
from app.evaluation.field_metrics import compare_documents
from app.evaluation.models import DocumentEvaluation, EvaluationSummary


class EvaluationParseFailed(RuntimeError):
    """MinerU 失败或轮询超时时的统一评测错误。"""

    pass


class ExtractionEvaluationRunner:
    """在合成 Gold 数据集上执行 Parser + Normalizer 并聚合指标。"""

    def __init__(
        self,
        *,
        parser: AsyncDocumentParser,
        normalizer: NormalizationProvider,
        cache: MinerUParseCache,
        poll_interval_seconds: float = 2,
        max_polls: int = 600,
        progress: Callable[[str], None] | None = None,
    ) -> None:
        self._parser = parser
        self._normalizer = normalizer
        self._cache = cache
        self._poll_interval_seconds = poll_interval_seconds
        self._max_polls = max_polls
        self._progress = progress or (lambda message: None)

    def run(
        self,
        *,
        manifest_path: Path,
        variant_name: str,
        output_root: Path,
        max_documents: int | None = None,
    ) -> tuple[EvaluationSummary, list[DocumentEvaluation], Path]:
        """运行清单内样本并写出可复算结果。

        返回聚合摘要、逐文档结果和本次运行目录。逐文档 JSONL 保留预测值，
        因而修改指标算法后无需再次支付模型调用费用。
        """
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        dataset_root = manifest_path.parent
        documents: list[DocumentEvaluation] = []
        for case in manifest["cases"]:
            for relative_document in case["documents"]:
                if max_documents is not None and len(documents) >= max_documents:
                    break
                source_path = dataset_root / relative_document
                document_type = self._document_type(source_path.name)
                gold_path = (
                    dataset_root
                    / "gold"
                    / case["case_id"]
                    / f"{source_path.stem}.json"
                )
                documents.append(
                    self._evaluate_one(
                        case_id=case["case_id"],
                        source_path=source_path,
                        gold_path=gold_path,
                        document_type=document_type,
                    )
                )
            if max_documents is not None and len(documents) >= max_documents:
                break

        summary = self._summarize(variant_name, documents)
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        output_directory = output_root / run_id
        output_directory.mkdir(parents=True, exist_ok=False)
        with (output_directory / "documents.jsonl").open(
            "w",
            encoding="utf-8",
        ) as stream:
            for document in documents:
                stream.write(document.model_dump_json() + "\n")
        (output_directory / "summary.json").write_text(
            summary.model_dump_json(indent=2),
            encoding="utf-8",
        )
        return summary, documents, output_directory

    def _evaluate_one(
        self,
        *,
        case_id: str,
        source_path: Path,
        gold_path: Path,
        document_type: DocumentType,
    ) -> DocumentEvaluation:
        source = source_path.read_bytes()
        gold = json.loads(gold_path.read_text(encoding="utf-8"))
        parse_result = self._cache.get(source)
        cache_hit = parse_result is not None
        if parse_result is None:
            try:
                parse_result = self._parse(
                    filename=source_path.name,
                    content=self._content_type(source_path),
                    source=source,
                )
            except Exception as exc:
                self._progress(f"failed to parse {source_path.name}: {exc}")
                return self._failure(
                    case_id=case_id,
                    source_path=source_path,
                    document_type=document_type,
                    gold=gold,
                    stage="parser",
                    error=exc,
                    parser_cache_hit=False,
                    parser_model=self._parser.model_name,
                )
            self._cache.put(source, parse_result)

        started = perf_counter()
        try:
            normalized = self._normalizer.normalize(
                document_type=document_type,
                parse_result=parse_result,
            )
        except Exception as exc:
            latency_ms = round((perf_counter() - started) * 1000)
            self._progress(
                f"failed to normalize {source_path.name}: {exc}"
            )
            return self._failure(
                case_id=case_id,
                source_path=source_path,
                document_type=document_type,
                gold=gold,
                stage="normalizer",
                error=exc,
                parser_cache_hit=cache_hit,
                parser_model=parse_result.model_name,
                latency_ms=latency_ms,
            )
        latency_ms = round((perf_counter() - started) * 1000)
        predicted = normalized.document.model_dump(mode="json")
        counts = compare_documents(
            predicted,
            gold,
            {item.field_path for item in normalized.evidence},
        )
        evidence_paths = sorted(
            {item.field_path for item in normalized.evidence}
        )
        return DocumentEvaluation(
            case_id=case_id,
            document_path=str(source_path),
            document_type=document_type.value,
            schema_valid=True,
            counts=counts,
            latency_ms=latency_ms,
            estimated_cost_aud=normalized.estimated_cost_aud,
            parser_cache_hit=cache_hit,
            parser_model=parse_result.model_name,
            normalizer_model=self._normalizer.model_name,
            prompt_version=self._normalizer.prompt_version,
            predicted_document=predicted,
            evidence_paths=evidence_paths,
        )

    def _failure(
        self,
        *,
        case_id: str,
        source_path: Path,
        document_type: DocumentType,
        gold: dict,
        stage: str,
        error: Exception,
        parser_cache_hit: bool,
        parser_model: str,
        latency_ms: int = 0,
    ) -> DocumentEvaluation:
        """把单文档异常转换为评测结果，让后续文档继续运行。"""

        error_code = getattr(error, "code", None)
        return DocumentEvaluation(
            case_id=case_id,
            document_path=str(source_path),
            document_type=document_type.value,
            schema_valid=False,
            counts=compare_documents({}, gold),
            latency_ms=latency_ms,
            parser_cache_hit=parser_cache_hit,
            parser_model=parser_model,
            normalizer_model=self._normalizer.model_name,
            prompt_version=self._normalizer.prompt_version,
            error_stage=stage,
            error_code=str(error_code or error.__class__.__name__),
            error_message=str(error),
        )

    def _parse(
        self,
        *,
        filename: str,
        content: str,
        source: bytes,
    ) -> ParseResult:
        remote_job_id = self._cache.get_pending(source)
        if remote_job_id is None:
            submission = self._parser.submit(
                filename=filename,
                content_type=content,
                content=source,
            )
            remote_job_id = submission.remote_job_id
            self._cache.put_pending(source, remote_job_id)
            self._progress(
                f"submitted {filename} to MinerU as {remote_job_id}"
            )
        else:
            self._progress(
                f"resuming {filename} from MinerU job {remote_job_id}"
            )
        for _ in range(self._max_polls):
            result = self._parser.poll(remote_job_id)
            if result.state == ParseState.SUCCEEDED and result.result is not None:
                self._progress(f"MinerU completed {filename}")
                return result.result
            if result.state == ParseState.FAILED:
                raise EvaluationParseFailed(
                    result.error_code or "MinerU evaluation parse failed"
                )
            time.sleep(self._poll_interval_seconds)
        raise EvaluationParseFailed("MinerU evaluation parse timed out")

    @staticmethod
    def _document_type(filename: str) -> DocumentType:
        if filename.casefold().startswith("invoice__"):
            return DocumentType.INVOICE
        if filename.casefold().startswith("receive_note__"):
            return DocumentType.RECEIVE_NOTE
        raise ValueError(f"Cannot infer document type from {filename}")

    @staticmethod
    def _content_type(path: Path) -> str:
        if path.suffix.casefold() == ".pdf":
            return "application/pdf"
        if path.suffix.casefold() == ".png":
            return "image/png"
        return "image/jpeg"

    @staticmethod
    def _summarize(
        variant_name: str,
        documents: list[DocumentEvaluation],
    ) -> EvaluationSummary:
        if not documents:
            return EvaluationSummary(
                variant_name=variant_name,
                document_count=0,
                schema_valid_rate=Decimal("0"),
                field_micro_accuracy=Decimal("0"),
                line_item_f1=Decimal("0"),
                evidence_coverage=Decimal("0"),
                p50_latency_ms=0,
                p95_latency_ms=0,
                parser_cache_hits=0,
            )
        total_fields = sum(item.counts.total for item in documents)
        correct_fields = sum(item.counts.correct for item in documents)
        matched = sum(item.counts.matched_lines for item in documents)
        missing = sum(item.counts.missing_lines for item in documents)
        extra = sum(item.counts.extra_lines for item in documents)
        evidence_total = sum(item.counts.evidence_total for item in documents)
        evidence_covered = sum(
            item.counts.evidence_covered for item in documents
        )
        latencies = sorted(item.latency_ms for item in documents)
        p95_index = max(0, round((len(latencies) - 1) * 0.95))
        costs = [
            item.estimated_cost_aud
            for item in documents
            if item.estimated_cost_aud is not None
        ]
        total_cost = sum(costs, Decimal("0")) if costs else None
        return EvaluationSummary(
            variant_name=variant_name,
            document_count=len(documents),
            schema_valid_rate=(
                Decimal(sum(item.schema_valid for item in documents))
                / Decimal(len(documents))
            ),
            field_micro_accuracy=(
                Decimal(correct_fields) / Decimal(total_fields)
                if total_fields
                else Decimal("1")
            ),
            line_item_f1=(
                Decimal(2 * matched)
                / Decimal(2 * matched + missing + extra)
                if 2 * matched + missing + extra
                else Decimal("1")
            ),
            evidence_coverage=(
                Decimal(evidence_covered) / Decimal(evidence_total)
                if evidence_total
                else Decimal("1")
            ),
            p50_latency_ms=round(median(latencies)),
            p95_latency_ms=latencies[p95_index],
            average_cost_aud=(
                total_cost / Decimal(len(costs))
                if total_cost is not None
                else None
            ),
            total_cost_aud=total_cost,
            parser_cache_hits=sum(
                item.parser_cache_hit for item in documents
            ),
        )

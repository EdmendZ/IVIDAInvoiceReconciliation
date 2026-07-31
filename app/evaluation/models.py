from decimal import Decimal

from pydantic import BaseModel, Field


class ComparisonCounts(BaseModel):
    correct: int = Field(ge=0)
    total: int = Field(ge=0)
    matched_lines: int = Field(ge=0)
    missing_lines: int = Field(ge=0)
    extra_lines: int = Field(ge=0)
    evidence_covered: int = Field(ge=0)
    evidence_total: int = Field(ge=0)
    errors: list[str] = Field(default_factory=list)

    @property
    def field_accuracy(self) -> Decimal:
        if self.total == 0:
            return Decimal("1")
        return Decimal(self.correct) / Decimal(self.total)

    @property
    def line_item_f1(self) -> Decimal:
        denominator = (
            2 * self.matched_lines + self.missing_lines + self.extra_lines
        )
        if denominator == 0:
            return Decimal("1")
        return Decimal(2 * self.matched_lines) / Decimal(denominator)

    @property
    def evidence_coverage(self) -> Decimal:
        if self.evidence_total == 0:
            return Decimal("1")
        return Decimal(self.evidence_covered) / Decimal(self.evidence_total)


class DocumentEvaluation(BaseModel):
    case_id: str
    document_path: str
    document_type: str
    schema_valid: bool
    counts: ComparisonCounts
    latency_ms: int = Field(ge=0)
    estimated_cost_aud: Decimal | None = Field(default=None, ge=0)
    parser_cache_hit: bool
    parser_model: str
    normalizer_model: str
    prompt_version: str
    predicted_document: dict = Field(default_factory=dict)
    evidence_paths: list[str] = Field(default_factory=list)
    error_stage: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class EvaluationSummary(BaseModel):
    variant_name: str
    document_count: int = Field(ge=0)
    schema_valid_rate: Decimal = Field(ge=0, le=1)
    field_micro_accuracy: Decimal = Field(ge=0, le=1)
    line_item_f1: Decimal = Field(ge=0, le=1)
    evidence_coverage: Decimal = Field(ge=0, le=1)
    p50_latency_ms: int = Field(ge=0)
    p95_latency_ms: int = Field(ge=0)
    average_cost_aud: Decimal | None = Field(default=None, ge=0)
    total_cost_aud: Decimal | None = Field(default=None, ge=0)
    parser_cache_hits: int = Field(ge=0)


class RankedVariant(BaseModel):
    rank: int = Field(ge=1)
    name: str
    within_budget: bool
    field_micro_accuracy: Decimal
    line_item_f1: Decimal
    evidence_coverage: Decimal
    average_cost_aud: Decimal | None = None
    rationale: list[str] = Field(default_factory=list)

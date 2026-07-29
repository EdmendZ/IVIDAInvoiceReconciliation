from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field


class IssueSeverity(StrEnum):
    WARNING = "warning"
    BLOCKING = "blocking"


class ValidationIssue(BaseModel):
    rule_code: str
    severity: IssueSeverity
    field_path: str
    message: str
    measured_difference: Decimal | None = None


class ValidationReport(BaseModel):
    issues: list[ValidationIssue] = Field(default_factory=list)
    line_tolerance: Decimal = Decimal("0.02")
    document_tolerance: Decimal = Decimal("0.05")

    @property
    def blocking_count(self) -> int:
        return sum(
            issue.severity == IssueSeverity.BLOCKING for issue in self.issues
        )

    @property
    def warning_count(self) -> int:
        return sum(
            issue.severity == IssueSeverity.WARNING for issue in self.issues
        )

    def has_warning(self, rule_code: str) -> bool:
        return any(
            issue.rule_code == rule_code
            and issue.severity == IssueSeverity.WARNING
            for issue in self.issues
        )

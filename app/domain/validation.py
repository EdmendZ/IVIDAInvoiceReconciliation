"""确定性文档校验问题和汇总报告。"""

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field


class IssueSeverity(StrEnum):
    """Warning 允许批准但需关注；Blocking 必须先解决。"""

    WARNING = "warning"
    BLOCKING = "blocking"


class ValidationIssue(BaseModel):
    """指向具体字段、规则代码和可解释差值的问题。"""

    rule_code: str
    severity: IssueSeverity
    field_path: str
    message: str
    measured_difference: Decimal | None = None


class ValidationReport(BaseModel):
    """一次文档校验的全部问题和实际使用容差。"""

    issues: list[ValidationIssue] = Field(default_factory=list)
    line_tolerance: Decimal = Decimal("0.02")
    document_tolerance: Decimal = Decimal("0.05")

    @property
    def blocking_count(self) -> int:
        """返回阻止批准的问题数量。"""

        return sum(
            issue.severity == IssueSeverity.BLOCKING for issue in self.issues
        )

    @property
    def warning_count(self) -> int:
        """返回不会自动阻止批准的提示数量。"""

        return sum(
            issue.severity == IssueSeverity.WARNING for issue in self.issues
        )

    def has_warning(self, rule_code: str) -> bool:
        return any(
            issue.rule_code == rule_code
            and issue.severity == IssueSeverity.WARNING
            for issue in self.issues
        )

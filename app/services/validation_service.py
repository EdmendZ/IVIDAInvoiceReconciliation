"""单张业务文档内部的确定性财务一致性校验。"""

from decimal import Decimal

from app.domain.documents import BusinessDocument
from app.domain.validation import (
    IssueSeverity,
    ValidationIssue,
    ValidationReport,
)


class ValidationService:
    """生成 Warning/Blocking Issue，不修改文档也不决定最终核对结果。"""

    def __init__(
        self,
        *,
        line_tolerance: Decimal = Decimal("0.02"),
        document_tolerance: Decimal = Decimal("0.05"),
    ) -> None:
        self._line_tolerance = line_tolerance
        self._document_tolerance = document_tolerance

    def validate(self, document: BusinessDocument) -> ValidationReport:
        """验证行金额、税额、小计和总额，并保留可解释差值。"""

        issues: list[ValidationIssue] = []
        if not document.purchase_order_number:
            issues.append(
                ValidationIssue(
                    rule_code="PO_MISSING",
                    severity=IssueSeverity.WARNING,
                    field_path="purchase_order_number",
                    message="Purchase order number is missing",
                )
            )

        calculated_subtotal = Decimal("0")
        calculated_tax = Decimal("0")
        # 行金额不完整时不能断言 subtotal 错误，否则会把“未知”误判成“不一致”。
        has_all_line_totals = True
        for index, item in enumerate(document.items):
            expected_line_total = (
                item.quantity * item.unit_price
                if item.unit_price is not None
                else None
            )
            if item.line_total is None:
                has_all_line_totals = False
            else:
                calculated_subtotal += item.line_total
            if (
                expected_line_total is not None
                and item.line_total is not None
                and abs(expected_line_total - item.line_total)
                > self._line_tolerance
            ):
                issues.append(
                    ValidationIssue(
                        rule_code="LINE_TOTAL_MISMATCH",
                        severity=IssueSeverity.BLOCKING,
                        field_path=f"items.{index}.line_total",
                        message="Line total does not equal quantity multiplied by unit price",
                        measured_difference=abs(
                            expected_line_total - item.line_total
                        ),
                    )
                )
            if item.tax_amount is not None:
                calculated_tax += item.tax_amount
            if (
                item.tax_code
                and item.tax_code.upper() in {"GST_FREE", "GST-FREE", "FRE", "0"}
                and item.tax_amount not in {None, Decimal("0")}
            ):
                issues.append(
                    ValidationIssue(
                        rule_code="GST_FREE_LINE_HAS_TAX",
                        severity=IssueSeverity.BLOCKING,
                        field_path=f"items.{index}.tax_amount",
                        message="GST-free line contains a non-zero tax amount",
                        measured_difference=item.tax_amount,
                    )
                )

        # 只有所有行金额都已知，才比较行金额之和与文档小计。
        if (
            has_all_line_totals
            and document.subtotal is not None
            and abs(calculated_subtotal - document.subtotal)
            > self._document_tolerance
        ):
            issues.append(
                ValidationIssue(
                    rule_code="SUBTOTAL_MISMATCH",
                    severity=IssueSeverity.BLOCKING,
                    field_path="subtotal",
                    message="Subtotal does not equal the sum of line totals",
                    measured_difference=abs(
                        calculated_subtotal - document.subtotal
                    ),
                )
            )
        if (
            any(item.tax_amount is not None for item in document.items)
            and document.tax_total is not None
            and abs(calculated_tax - document.tax_total)
            > self._document_tolerance
        ):
            issues.append(
                ValidationIssue(
                    rule_code="TAX_TOTAL_MISMATCH",
                    severity=IssueSeverity.BLOCKING,
                    field_path="tax_total",
                    message="Tax total does not equal the sum of line tax amounts",
                    measured_difference=abs(calculated_tax - document.tax_total),
                )
            )
        if (
            document.subtotal is not None
            and document.tax_total is not None
            and document.total is not None
        ):
            expected_total = document.subtotal + document.tax_total
            if abs(expected_total - document.total) > self._document_tolerance:
                issues.append(
                    ValidationIssue(
                        rule_code="TOTAL_MISMATCH",
                        severity=IssueSeverity.BLOCKING,
                        field_path="total",
                        message="Total does not equal subtotal plus tax",
                        measured_difference=abs(
                            expected_total - document.total
                        ),
                    )
                )
        return ValidationReport(
            issues=issues,
            line_tolerance=self._line_tolerance,
            document_tolerance=self._document_tolerance,
        )

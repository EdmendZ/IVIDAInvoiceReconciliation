"""将已持久化的核对快照导出为适合 Excel 打开的审计 CSV。"""

from csv import writer
from io import StringIO

from app.domain.reconciliation_records import ReconciliationRecord


def render_reconciliation_csv(record: ReconciliationRecord) -> bytes:
    """生成 UTF-8 BOM CSV，保留标识符文本和 Decimal 的精确字符串表示。"""

    output = StringIO(newline="")
    rows = writer(output, lineterminator="\r\n")
    result = record.result
    summary = result.summary
    rows.writerow(["Reconciliation ID", _safe_text(record.reconciliation_id)])
    rows.writerow(["Created at", record.created_at.isoformat()])
    rows.writerow(["Created by", _safe_text(record.created_by)])
    rows.writerow(["Invoice number", _safe_text(result.invoice_number)])
    rows.writerow(
        [
            "Receive note numbers",
            _safe_text(", ".join(result.receive_note_numbers)),
        ]
    )
    rows.writerow(["Purchase order match", _optional_bool(result.purchase_order_match)])
    rows.writerow(["Currency match", _optional_bool(result.currency_match)])
    rows.writerow(["Requires review", _optional_bool(summary.requires_review)])
    rows.writerow([])
    rows.writerow(
        [
            "Match key",
            "SKU",
            "Description",
            "Invoice quantity",
            "Received quantity",
            "Quantity difference",
            "Invoice unit price",
            "Received unit price",
            "Unit price difference",
            "Invoice amount",
            "Received amount",
            "Amount difference",
            "Status",
            "Reasons",
        ]
    )
    for line in result.lines:
        rows.writerow(
            [
                _safe_text(line.match_key),
                _safe_text(line.sku or ""),
                _safe_text(line.description),
                str(line.invoice_quantity),
                str(line.received_quantity),
                str(line.quantity_difference),
                _optional_decimal(line.invoice_unit_price),
                _optional_decimal(line.received_unit_price),
                _optional_decimal(line.unit_price_difference),
                _optional_decimal(line.invoice_amount),
                _optional_decimal(line.received_amount),
                _optional_decimal(line.amount_difference),
                _safe_text(line.status.value),
                _safe_text("; ".join(line.reasons)),
            ]
        )
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def _optional_decimal(value: object | None) -> str:
    return "" if value is None else str(value)


def _optional_bool(value: bool | None) -> str:
    if value is None:
        return "Unknown"
    return "Yes" if value else "No"


def _safe_text(value: str) -> str:
    """阻止用户可控文本在 Excel 中被解释成公式。"""

    if value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return f"'{value}"
    return value

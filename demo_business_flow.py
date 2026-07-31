"""无需数据库和模型即可断点学习的 Invoice / Receive Note 业务演示。

在 PyCharm 中直接右键运行本文件。推荐在 `run_demo`、`assess_candidate` 和
`reconcile` 设置断点，观察：

1. 为什么采购订单号只是候选信号，而不是唯一关联键；
2. 两张分批 Receive Notes 如何先聚合，再与一张 Invoice 核对；
3. 一个数量差异如何变成 `mismatch` 和 `requires_review=True`。

本脚本只演示批准后的纯领域规则，不访问 `.env`、PostgreSQL、MinIO、MinerU
或公共模型。完整系统在进入这里之前仍需完成上传、抽取、校验和人工批准。
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from app.domain.documents import Invoice, LineItem, Party, ReceiveNote
from app.domain.reconciliation import ReconciliationRequest
from app.domain.reconciliation_candidates import ReconciliationCandidate
from app.services.candidate_matching_service import assess_candidate
from app.services.reconciliation_service import reconcile


def build_demo_documents() -> tuple[Invoice, list[ReceiveNote]]:
    """构造符合澳洲披萨门店采购场景的一张发票和两张分批收货单。

    发票包含 10 箱面粉和 6 箱奶酪。两次收货合计收到 10 箱面粉、5 箱奶酪，
    因此候选关系很强，但正式核对仍会发现奶酪少收 1 箱。
    """

    supplier = Party(
        name="Southern Cross Foodservice Pty Ltd",
        business_number="51 824 753 556",
        address="18 Distribution Drive, Smithfield NSW 2164",
    )
    location = Party(
        name="Harbour Pizza Newtown",
        address="88 King Street, Newtown NSW 2042",
    )
    invoice = Invoice(
        document_number="SCF-INV-260701",
        document_date=date(2026, 7, 1),
        purchase_order_number="PO-SYD-1042",
        supplier=supplier,
        location=location,
        subtotal=Decimal("470.00"),
        tax_total=Decimal("47.00"),
        total=Decimal("517.00"),
        items=[
            LineItem(
                sku="FLOUR-12.5",
                description="Tipo 00 Pizza Flour 12.5kg",
                quantity=Decimal("10"),
                unit="carton",
                unit_price=Decimal("32.00"),
                line_total=Decimal("320.00"),
            ),
            LineItem(
                sku="CHEESE-2",
                description="Shredded Mozzarella 2kg",
                quantity=Decimal("6"),
                unit="carton",
                unit_price=Decimal("25.00"),
                line_total=Decimal("150.00"),
            ),
        ],
    )
    receive_notes = [
        ReceiveNote(
            document_number="RN-SYD-1042-A",
            document_date=date(2026, 6, 29),
            purchase_order_number="PO-SYD-1042",
            supplier=supplier,
            location=location,
            items=[
                LineItem(
                    sku="FLOUR-12.5",
                    description="Tipo 00 Pizza Flour 12.5kg",
                    quantity=Decimal("6"),
                    unit="carton",
                    unit_price=Decimal("32.00"),
                    line_total=Decimal("192.00"),
                ),
                LineItem(
                    sku="CHEESE-2",
                    description="Shredded Mozzarella 2kg",
                    quantity=Decimal("3"),
                    unit="carton",
                    unit_price=Decimal("25.00"),
                    line_total=Decimal("75.00"),
                ),
            ],
        ),
        ReceiveNote(
            document_number="RN-SYD-1042-B",
            document_date=date(2026, 6, 30),
            purchase_order_number="PO-SYD-1042",
            supplier=supplier,
            location=location,
            items=[
                LineItem(
                    sku="FLOUR-12.5",
                    description="Tipo 00 Pizza Flour 12.5kg",
                    quantity=Decimal("4"),
                    unit="carton",
                    unit_price=Decimal("32.00"),
                    line_total=Decimal("128.00"),
                ),
                LineItem(
                    sku="CHEESE-2",
                    description="Shredded Mozzarella 2kg",
                    quantity=Decimal("2"),
                    unit="carton",
                    unit_price=Decimal("25.00"),
                    line_total=Decimal("50.00"),
                ),
            ],
        ),
    ]
    return invoice, receive_notes


def run_demo() -> dict:
    """执行候选评估和一对多核对，返回便于测试与观察的序列化结果。"""

    invoice, receive_notes = build_demo_documents()

    # 候选评估逐张进行：它回答“这张收货单是否可能属于该发票”。
    candidates: list[ReconciliationCandidate] = [
        assess_candidate(
            invoice=invoice,
            receive_note=note,
            receive_note_version_id=f"demo-version-{index}",
        )
        for index, note in enumerate(receive_notes, start=1)
    ]

    # 正式核对必须一次传入所有已确认的收货单。reconcile 会先按 SKU 聚合，
    # 否则任何一张分批收货单单独与整张发票比较都会产生伪缺货。
    reconciliation = reconcile(
        ReconciliationRequest(
            invoice=invoice,
            receive_notes=receive_notes,
        )
    )
    return {
        "candidate_assessments": [
            candidate.model_dump(mode="json") for candidate in candidates
        ],
        "reconciliation": reconciliation.model_dump(mode="json"),
    }


def main() -> None:
    """打印人类可读 JSON；断点学习时可直接检查 `result` 变量。"""

    result = run_demo()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

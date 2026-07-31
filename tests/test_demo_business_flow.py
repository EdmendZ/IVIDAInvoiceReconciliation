from demo_business_flow import build_demo_documents, run_demo


def test_demo_models_one_invoice_with_two_partial_receipts() -> None:
    invoice, notes = build_demo_documents()

    assert invoice.purchase_order_number == "PO-SYD-1042"
    assert len(notes) == 2
    assert all(
        note.purchase_order_number == invoice.purchase_order_number
        for note in notes
    )


def test_demo_explains_candidate_strength_and_real_quantity_mismatch() -> None:
    result = run_demo()
    candidates = result["candidate_assessments"]
    reconciliation = result["reconciliation"]

    assert all(candidate["recommended"] for candidate in candidates)
    assert reconciliation["purchase_order_match"] is True
    assert reconciliation["summary"]["exact_lines"] == 1
    assert reconciliation["summary"]["mismatch_lines"] == 1
    assert reconciliation["summary"]["requires_review"] is True

    cheese = next(
        line
        for line in reconciliation["lines"]
        if line["sku"] == "CHEESE-2"
    )
    assert cheese["invoice_quantity"] == "6"
    assert cheese["received_quantity"] == "5"
    assert cheese["quantity_difference"] == "1"
    assert cheese["status"] == "mismatch"

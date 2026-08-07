from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
DATASET_ROOT = ROOT / "evaluation_data"
PDF_ROOT = DATASET_ROOT / "source_documents" / "pdf"
GOLD_ROOT = DATASET_ROOT / "gold"

GST_RATE = Decimal("0.10")
MONEY = Decimal("0.01")


@dataclass(frozen=True)
class Party:
    name: str
    abn: str
    address: str


@dataclass(frozen=True)
class Item:
    sku: str
    description: str
    unit: str
    quantity: Decimal
    unit_price: Decimal | None


@dataclass(frozen=True)
class Document:
    document_type: str
    number: str
    document_date: date
    po_number: str
    supplier: Party
    location: Party
    items: tuple[Item, ...]
    show_prices: bool = True
    total_adjustment: Decimal = Decimal("0.00")


@dataclass(frozen=True)
class Case:
    case_id: str
    title: str
    expected_outcome: str
    invoice: Document
    receive_notes: tuple[Document, ...]


SUPPLIERS = {
    "foodservice": Party(
        "Southern Cross Foodservice Pty Ltd",
        "12 345 678 901",
        "18 Distribution Drive, Smithfield NSW 2164",
    ),
    "dairy": Party(
        "Tasman Dairy Distribution Pty Ltd",
        "23 456 789 012",
        "44 Coldchain Road, Truganina VIC 3029",
    ),
    "produce": Party(
        "Coastal Fresh Produce Pty Ltd",
        "34 567 890 123",
        "7 Market Lane, Rocklea QLD 4106",
    ),
    "packaging": Party(
        "Outback Packaging Supplies Pty Ltd",
        "45 678 901 234",
        "91 Supply Crescent, Welshpool WA 6106",
    ),
}

STORES = {
    "sydney": Party(
        "Harbour Slice Pizza Pty Ltd",
        "56 789 012 345",
        "128 Harbour Street, Sydney NSW 2000",
    ),
    "melbourne": Party(
        "Laneway Pizza Kitchen Pty Ltd",
        "67 890 123 456",
        "22 Hardware Lane, Melbourne VIC 3000",
    ),
    "brisbane": Party(
        "River City Pizza Co Pty Ltd",
        "78 901 234 567",
        "63 Riverside Avenue, Brisbane QLD 4000",
    ),
    "perth": Party(
        "West Coast Oven Pty Ltd",
        "89 012 345 678",
        "15 Ocean View Road, Fremantle WA 6160",
    ),
}


def d(value: str) -> Decimal:
    return Decimal(value)


def invoice(
    number: str,
    day: int,
    po: str,
    supplier: Party,
    location: Party,
    items: list[Item],
    adjustment: str = "0.00",
) -> Document:
    return Document(
        "invoice",
        number,
        date(2026, 7, day),
        po,
        supplier,
        location,
        tuple(items),
        True,
        d(adjustment),
    )


def receive_note(
    number: str,
    day: int,
    po: str,
    supplier: Party,
    location: Party,
    items: list[Item],
    show_prices: bool = True,
) -> Document:
    return Document(
        "receive_note",
        number,
        date(2026, 7, day),
        po,
        supplier,
        location,
        tuple(items),
        show_prices,
    )


CASES = (
    Case(
        "case-01-exact-single",
        "Exact match - one invoice and one receive note",
        "No manual review required",
        invoice(
            "SCF-INV-260701",
            3,
            "PO-SYD-1042",
            SUPPLIERS["foodservice"],
            STORES["sydney"],
            [
                Item("FLOUR-12.5", "Pizza flour 12.5 kg", "bag", d("8"), d("22.50")),
                Item("TOMATO-6", "Italian tomato base 6 x 2.5 kg", "case", d("4"), d("31.20")),
                Item("OLIVE-3", "Sliced black olives 3 kg", "tub", d("2"), d("19.80")),
            ],
        ),
        (
            receive_note(
                "GRN-SYD-260703-01",
                3,
                "PO-SYD-1042",
                SUPPLIERS["foodservice"],
                STORES["sydney"],
                [
                    Item("FLOUR-12.5", "Pizza flour 12.5 kg", "bag", d("8"), d("22.50")),
                    Item("TOMATO-6", "Italian tomato base 6 x 2.5 kg", "case", d("4"), d("31.20")),
                    Item("OLIVE-3", "Sliced black olives 3 kg", "tub", d("2"), d("19.80")),
                ],
            ),
        ),
    ),
    Case(
        "case-02-exact-split-delivery",
        "Exact match - invoice fulfilled by two receive notes",
        "Quantities aggregate across both receive notes",
        invoice(
            "TDD-INV-260714",
            15,
            "PO-MEL-2208",
            SUPPLIERS["dairy"],
            STORES["melbourne"],
            [
                Item("MOZZ-2", "Shredded mozzarella 2 kg", "case", d("12"), d("28.40")),
                Item("PARM-1", "Grated parmesan 1 kg", "bag", d("6"), d("17.90")),
            ],
        ),
        (
            receive_note(
                "GRN-MEL-260714-A",
                14,
                "PO-MEL-2208",
                SUPPLIERS["dairy"],
                STORES["melbourne"],
                [
                    Item("MOZZ-2", "Shredded mozzarella 2 kg", "case", d("7"), d("28.40")),
                    Item("PARM-1", "Grated parmesan 1 kg", "bag", d("2"), d("17.90")),
                ],
            ),
            receive_note(
                "GRN-MEL-260715-B",
                15,
                "PO-MEL-2208",
                SUPPLIERS["dairy"],
                STORES["melbourne"],
                [
                    Item("MOZZ-2", "Shredded mozzarella 2 kg", "case", d("5"), d("28.40")),
                    Item("PARM-1", "Grated parmesan 1 kg", "bag", d("4"), d("17.90")),
                ],
            ),
        ),
    ),
    Case(
        "case-03-short-delivery",
        "Quantity mismatch - short delivery",
        "Mozzarella is invoiced at 10 cases but only 8 cases were received",
        invoice(
            "TDD-INV-260718",
            18,
            "PO-BNE-3315",
            SUPPLIERS["dairy"],
            STORES["brisbane"],
            [
                Item("MOZZ-2", "Shredded mozzarella 2 kg", "case", d("10"), d("28.40")),
                Item("FETA-2", "Danish feta 2 kg", "tub", d("3"), d("24.50")),
            ],
        ),
        (
            receive_note(
                "GRN-BNE-260718",
                18,
                "PO-BNE-3315",
                SUPPLIERS["dairy"],
                STORES["brisbane"],
                [
                    Item("MOZZ-2", "Shredded mozzarella 2 kg", "case", d("8"), d("28.40")),
                    Item("FETA-2", "Danish feta 2 kg", "tub", d("3"), d("24.50")),
                ],
            ),
        ),
    ),
    Case(
        "case-04-price-variance",
        "Unit price mismatch",
        "Pizza boxes are invoiced above the price recorded on the receive note",
        invoice(
            "OPS-INV-260721",
            21,
            "PO-PER-4410",
            SUPPLIERS["packaging"],
            STORES["perth"],
            [
                Item("BOX-12", "Pizza box kraft 12 inch", "100 pack", d("5"), d("42.50")),
                Item("BOX-14", "Pizza box kraft 14 inch", "100 pack", d("3"), d("49.00")),
            ],
        ),
        (
            receive_note(
                "GRN-PER-260721",
                21,
                "PO-PER-4410",
                SUPPLIERS["packaging"],
                STORES["perth"],
                [
                    Item("BOX-12", "Pizza box kraft 12 inch", "100 pack", d("5"), d("40.00")),
                    Item("BOX-14", "Pizza box kraft 14 inch", "100 pack", d("3"), d("49.00")),
                ],
            ),
        ),
    ),
    Case(
        "case-05-invoice-only-line",
        "Invoice contains an undelivered item",
        "Basil appears on the invoice but not on the receive note",
        invoice(
            "CFP-INV-260723",
            23,
            "PO-SYD-1088",
            SUPPLIERS["produce"],
            STORES["sydney"],
            [
                Item("MUSH-5", "Cup mushrooms 5 kg", "crate", d("3"), d("34.00")),
                Item("CAPS-R-5", "Red capsicum 5 kg", "crate", d("2"), d("29.50")),
                Item("BASIL-1", "Fresh basil 1 kg", "box", d("1"), d("26.00")),
            ],
        ),
        (
            receive_note(
                "GRN-SYD-260723",
                23,
                "PO-SYD-1088",
                SUPPLIERS["produce"],
                STORES["sydney"],
                [
                    Item("MUSH-5", "Cup mushrooms 5 kg", "crate", d("3"), d("34.00")),
                    Item("CAPS-R-5", "Red capsicum 5 kg", "crate", d("2"), d("29.50")),
                ],
            ),
        ),
    ),
    Case(
        "case-06-receive-note-only-line",
        "Receive note contains an unbilled item",
        "Garlic appears on the receive note but not on the invoice",
        invoice(
            "CFP-INV-260724",
            24,
            "PO-BNE-3362",
            SUPPLIERS["produce"],
            STORES["brisbane"],
            [
                Item("ONION-10", "Brown onions 10 kg", "bag", d("2"), d("18.50")),
                Item("ROCKET-1", "Wild rocket 1 kg", "box", d("4"), d("16.80")),
            ],
        ),
        (
            receive_note(
                "GRN-BNE-260724",
                24,
                "PO-BNE-3362",
                SUPPLIERS["produce"],
                STORES["brisbane"],
                [
                    Item("ONION-10", "Brown onions 10 kg", "bag", d("2"), d("18.50")),
                    Item("ROCKET-1", "Wild rocket 1 kg", "box", d("4"), d("16.80")),
                    Item("GARLIC-1", "Peeled garlic 1 kg", "tub", d("1"), d("14.00")),
                ],
            ),
        ),
    ),
    Case(
        "case-07-rounding-tolerance",
        "Minor price and GST rounding difference",
        "Difference remains within configured financial tolerance",
        invoice(
            "SCF-INV-260726",
            26,
            "PO-MEL-2251",
            SUPPLIERS["foodservice"],
            STORES["melbourne"],
            [
                Item("YEAST-500", "Instant dry yeast 500 g", "pack", d("3"), d("15.000")),
                Item("OIL-4", "Extra virgin olive oil 4 L", "tin", d("2"), d("44.750")),
            ],
        ),
        (
            receive_note(
                "GRN-MEL-260726",
                26,
                "PO-MEL-2251",
                SUPPLIERS["foodservice"],
                STORES["melbourne"],
                [
                    Item("YEAST-500", "Instant dry yeast 500 g", "pack", d("3"), d("14.999")),
                    Item("OIL-4", "Extra virgin olive oil 4 L", "tin", d("2"), d("44.750")),
                ],
            ),
        ),
    ),
    Case(
        "case-08-po-mismatch",
        "Purchase order mismatch",
        "Line items match but the receive note references a different PO",
        invoice(
            "OPS-INV-260728",
            28,
            "PO-PER-4455",
            SUPPLIERS["packaging"],
            STORES["perth"],
            [
                Item("NAPKIN-2P", "Kraft napkin 2 ply", "500 pack", d("4"), d("18.90")),
                Item("BAG-L", "Paper delivery bag large", "250 pack", d("3"), d("32.00")),
            ],
        ),
        (
            receive_note(
                "GRN-PER-260728",
                28,
                "PO-PER-4456",
                SUPPLIERS["packaging"],
                STORES["perth"],
                [
                    Item("NAPKIN-2P", "Kraft napkin 2 ply", "500 pack", d("4"), d("18.90")),
                    Item("BAG-L", "Paper delivery bag large", "250 pack", d("3"), d("32.00")),
                ],
            ),
        ),
    ),
)


def money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def item_amount(item: Item) -> Decimal | None:
    if item.unit_price is None:
        return None
    return money(item.quantity * item.unit_price)


def document_totals(document: Document) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    amounts = [item_amount(item) for item in document.items]
    if not document.show_prices or any(amount is None for amount in amounts):
        return None, None, None
    subtotal = money(sum(amounts, Decimal("0")) + document.total_adjustment)
    gst = money(subtotal * GST_RATE)
    return subtotal, gst, money(subtotal + gst)


def party_json(party: Party) -> dict[str, str]:
    return {
        "name": party.name,
        "business_number": party.abn,
        "address": party.address,
    }


def document_json(document: Document) -> dict[str, Any]:
    subtotal, gst, total = document_totals(document)
    items: list[dict[str, Any]] = []
    for index, item in enumerate(document.items, start=1):
        amount = item_amount(item) if document.show_prices else None
        items.append(
            {
                "line_number": str(index),
                "sku": item.sku,
                "description": item.description,
                "quantity": str(item.quantity),
                "unit": item.unit,
                "unit_price": str(item.unit_price) if document.show_prices else None,
                "tax_amount": (
                    str(money(amount * GST_RATE)) if amount is not None else None
                ),
                "line_total": str(amount) if amount is not None else None,
            }
        )
    return {
        "document_type": document.document_type,
        "document_number": document.number,
        "document_date": document.document_date.isoformat(),
        "purchase_order_number": document.po_number,
        "currency": "AUD",
        "supplier": party_json(document.supplier),
        "location": party_json(document.location),
        "subtotal": str(subtotal) if subtotal is not None else None,
        "tax_total": str(gst) if gst is not None else None,
        "total": str(total) if total is not None else None,
        "items": items,
    }


def styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "DocTitle",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=20,
            leading=22,
            textColor=colors.HexColor("#123B5D"),
        ),
        "right": ParagraphStyle(
            "Right",
            parent=base["BodyText"],
            alignment=TA_RIGHT,
            fontSize=8.5,
            leading=11,
        ),
        "small": ParagraphStyle(
            "Small",
            parent=base["BodyText"],
            fontSize=8.5,
            leading=11,
        ),
        "banner": ParagraphStyle(
            "Banner",
            parent=base["BodyText"],
            alignment=TA_CENTER,
            fontName="Helvetica-Bold",
            fontSize=10,
            textColor=colors.white,
        ),
        "footer": ParagraphStyle(
            "Footer",
            parent=base["BodyText"],
            alignment=TA_CENTER,
            fontSize=7.5,
            textColor=colors.HexColor("#6B7280"),
        ),
    }


def render_pdf(document: Document, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    style = styles()
    pdf = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=f"{document.document_type}: {document.number}",
        author="IVIDA synthetic evaluation dataset",
    )

    title = "TAX INVOICE" if document.document_type == "invoice" else "GOODS RECEIVED NOTE"
    story: list[Any] = [
        Table(
            [[Paragraph("SYNTHETIC EVALUATION DOCUMENT - NOT FOR PAYMENT", style["banner"])]],
            colWidths=[178 * mm],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#B42318")),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#7A271A")),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            ),
        ),
        Spacer(1, 7 * mm),
        Table(
            [
                [
                    Paragraph(title, style["title"]),
                    Paragraph(
                        f"<b>{document.supplier.name}</b><br/>"
                        f"ABN {document.supplier.abn}<br/>"
                        f"{document.supplier.address}",
                        style["right"],
                    ),
                ]
            ],
            colWidths=[82 * mm, 96 * mm],
            style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]),
        ),
        Spacer(1, 5 * mm),
    ]

    label = "Invoice No." if document.document_type == "invoice" else "Receive Note No."
    details = [
        [label, document.number, "Document Date", document.document_date.strftime("%d %b %Y")],
        ["Purchase Order", document.po_number, "Currency", "AUD"],
        ["Deliver To", document.location.name, "Store ABN", document.location.abn],
        ["Delivery Address", document.location.address, "", ""],
    ]
    story.extend(
        [
            Table(
                details,
                colWidths=[28 * mm, 65 * mm, 28 * mm, 57 * mm],
                style=TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EAF2F8")),
                        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#EAF2F8")),
                        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, -1), 8),
                        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#B8C4CE")),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("TOPPADDING", (0, 0), (-1, -1), 5),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                        ("SPAN", (1, 3), (3, 3)),
                    ]
                ),
            ),
            Spacer(1, 7 * mm),
        ]
    )

    if document.document_type == "invoice":
        table_data = [["Line", "Code", "Description", "Unit", "Qty", "Unit Price", "GST", "Line Total"]]
        for index, item in enumerate(document.items, start=1):
            amount = item_amount(item)
            assert amount is not None
            table_data.append(
                [
                    str(index),
                    item.sku,
                    item.description,
                    item.unit,
                    str(item.quantity),
                    f"${item.unit_price:.3f}",
                    f"${money(amount * GST_RATE):.2f}",
                    f"${amount:.2f}",
                ]
            )
        widths = [10, 20, 55, 19, 13, 21, 17, 23]
    else:
        headers = ["Line", "Code", "Description", "Unit", "Qty Received", "Condition"]
        widths = [10, 24, 66, 25, 24, 29]
        if document.show_prices:
            headers.insert(5, "Recorded Price")
            widths = [10, 22, 55, 23, 21, 24, 23]
        table_data = [headers]
        for index, item in enumerate(document.items, start=1):
            row = [str(index), item.sku, item.description, item.unit, str(item.quantity)]
            if document.show_prices:
                row.append(f"${item.unit_price:.3f}")
            row.append("Accepted")
            table_data.append(row)

    story.append(
        Table(
            table_data,
            colWidths=[width * mm for width in widths],
            repeatRows=1,
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#123B5D")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#B8C4CE")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ALIGN", (4, 1), (-1, -1), "RIGHT"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F9FB")]),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            ),
        )
    )

    subtotal, gst, total = document_totals(document)
    if subtotal is not None:
        totals = Table(
            [
                ["Subtotal ex GST", f"${subtotal:.2f}"],
                ["GST 10%", f"${gst:.2f}"],
                ["Total inc GST", f"${total:.2f}"],
            ],
            colWidths=[37 * mm, 28 * mm],
            hAlign="RIGHT",
            style=TableStyle(
                [
                    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                    ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                    ("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.HexColor("#123B5D")),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            ),
        )
        story.extend([Spacer(1, 5 * mm), totals])

    if document.document_type == "receive_note":
        story.extend(
            [
                Spacer(1, 10 * mm),
                KeepTogether(
                    [
                        Table(
                            [
                                ["Received by", "Alex Morgan (synthetic)"],
                                ["Delivery condition", "Goods checked against delivery docket"],
                                ["Exceptions", "See line quantities and condition above"],
                            ],
                            colWidths=[42 * mm, 136 * mm],
                            style=TableStyle(
                                [
                                    ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                                    ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#D0D5DD")),
                                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                                ]
                            ),
                        )
                    ]
                ),
            ]
        )

    story.extend(
        [
            Spacer(1, 12 * mm),
            Paragraph(
                "All names, ABNs, addresses, prices and transactions in this document are fictional. "
                "Prepared solely for IVIDA invoice reconciliation testing.",
                style["footer"],
            ),
        ]
    )
    pdf.build(story)


def build_dataset() -> None:
    PDF_ROOT.mkdir(parents=True, exist_ok=True)
    GOLD_ROOT.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {
        "dataset_name": "IVIDA Australia Pizza Procurement Evaluation Set",
        "version": "1.0.0",
        "synthetic": True,
        "currency": "AUD",
        "tax_regime": "Australian GST 10%",
        "case_count": len(CASES),
        "cases": [],
    }

    for case in CASES:
        case_pdf_root = PDF_ROOT / case.case_id
        case_gold_root = GOLD_ROOT / case.case_id
        case_pdf_root.mkdir(parents=True, exist_ok=True)
        case_gold_root.mkdir(parents=True, exist_ok=True)

        documents = (case.invoice, *case.receive_notes)
        document_paths: list[str] = []
        for document in documents:
            filename = f"{document.document_type}__{document.number}.pdf"
            render_pdf(document, case_pdf_root / filename)
            gold_filename = filename.replace(".pdf", ".json")
            (case_gold_root / gold_filename).write_text(
                json.dumps(document_json(document), indent=2),
                encoding="utf-8",
            )
            document_paths.append(
                (Path("source_documents") / "pdf" / case.case_id / filename).as_posix()
            )

        request = {
            "invoice": document_json(case.invoice),
            "receive_notes": [document_json(note) for note in case.receive_notes],
            "tolerance": {
                "quantity": "0",
                "unit_price": "0.01",
                "amount": "0.02",
            },
        }
        (case_gold_root / "reconciliation_request.json").write_text(
            json.dumps(request, indent=2),
            encoding="utf-8",
        )

        manifest["cases"].append(
            {
                "case_id": case.case_id,
                "title": case.title,
                "expected_outcome": case.expected_outcome,
                "invoice_number": case.invoice.number,
                "receive_note_numbers": [note.number for note in case.receive_notes],
                "documents": document_paths,
                "gold_request": (
                    Path("gold") / case.case_id / "reconciliation_request.json"
                ).as_posix(),
            }
        )

    (DATASET_ROOT / "manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    (DATASET_ROOT / "README.md").write_text(
        """# IVIDA Australia Pizza Procurement Evaluation Set

This directory is generated and intentionally ignored by Git.

- All organisations, ABNs, people, addresses, prices and transactions are fictional.
- PDF source documents are under `source_documents/pdf`.
- Human-labelled JSON is under `gold`.
- `manifest.json` defines the eight evaluation cases.
- Do not replace synthetic files with customer documents unless they are redacted and approved.
""",
        encoding="utf-8",
    )
    print(f"Generated {len(CASES)} cases in {DATASET_ROOT}")


if __name__ == "__main__":
    build_dataset()

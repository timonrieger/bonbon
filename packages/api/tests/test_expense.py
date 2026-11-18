import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from bonbon.receipts.expense import (
    ExtractedItem,
    normalize_store,
    parse_expense,
    parse_rappen,
)

DATA = Path(__file__).parent / "data"


def expense(summary: list[dict] | None = None, rows: list[dict] | None = None) -> dict:
    """A minimal AnalyzeExpense response with the given summary fields and line items."""
    return {
        "ExpenseDocuments": [
            {
                "SummaryFields": summary or [],
                "LineItemGroups": [{"LineItems": rows or []}],
            }
        ]
    }


def summary_field(kind: str, value: str, label: str | None = None, **extra: object) -> dict:
    found = {"Type": {"Text": kind}, "ValueDetection": {"Text": value}, **extra}
    if label is not None:
        found["LabelDetection"] = {"Text": label}
    return found


def row(**fields: str) -> dict:
    return {
        "LineItemExpenseFields": [
            {"Type": {"Text": kind}, "ValueDetection": {"Text": value}}
            for kind, value in fields.items()
        ]
    }


def test_real_migros_receipt() -> None:
    """Textract's answer to a photographed Migros receipt (bottom with the date cut off)."""
    receipt = parse_expense(json.loads((DATA / "textract_migros.json").read_text()))

    assert receipt.store == "Migros"
    assert receipt.purchase_date is None
    # "Total CHF 185.70", not "Total in EUR 206.33".
    assert receipt.total_rappen == 18570
    assert len(receipt.items) == 43
    # The Cumulus vouchers (-30.00) are no line items, so the items add up to the subtotal.
    assert sum(i.amount_rappen for i in receipt.items) == 21570
    assert receipt.items[0] == ExtractedItem(
        name="MClass Joghurt Mokka",
        amount_rappen=960,
        quantity=Decimal("16.000"),
        unit_price_rappen=60,
    )
    # Weighed goods: the printed unit price is per kg.
    assert receipt.items[14] == ExtractedItem(
        name="Poulet Schnitzel",
        amount_rappen=1140,
        quantity=Decimal("1.000"),
        unit_price_rappen=3300,
    )


@pytest.mark.parametrize(
    ("text", "rappen"),
    [
        ("185.70", 18570),
        ("CHF 12.50", 1250),
        ("12,50", 1250),
        ("1'234.50", 123450),
        ("5", 500),
        ("1.5", 150),
        ("-1.20", -120),
        ("20.00-", -2000),
        ("", None),
        ("abc", None),
        ("12.345", None),
    ],
)
def test_parse_rappen(text: str, rappen: int | None) -> None:
    assert parse_rappen(text) == rappen


@pytest.mark.parametrize(
    ("text", "store"),
    [
        ("MIGROS", "Migros"),
        ("Genossenschaft Migros Ostschweiz", "Migros"),
        ("Coop Pronto", "Coop"),
        ("ALDI SUISSE", "Aldi"),
        ("Lidl Schweiz", "Lidl"),
        ("Volg\nDorfladen", "Volg"),
        ("  Bäckerei   Beck ", "Bäckerei Beck"),
        ("", None),
    ],
)
def test_normalize_store(text: str, store: str | None) -> None:
    assert normalize_store(text) == store


def test_vendor_from_name_field_in_vendor_group() -> None:
    receipt = parse_expense(
        expense([summary_field("NAME", "coop", GroupProperties=[{"Types": ["VENDOR"]}])])
    )
    assert receipt.store == "Coop"


@pytest.mark.parametrize(
    ("text", "day"),
    [
        ("17.11.2026", date(2026, 11, 17)),
        ("17.11.26", date(2026, 11, 17)),
        ("7.1.2026", date(2026, 1, 7)),
        ("17/11/2026", date(2026, 11, 17)),
        ("17.11.2026 14:32", date(2026, 11, 17)),
        ("2026-11-17", date(2026, 11, 17)),
        ("31.02.2026", None),
        ("Datum fehlt", None),
    ],
)
def test_purchase_date(text: str, day: date | None) -> None:
    receipt = parse_expense(expense([summary_field("INVOICE_RECEIPT_DATE", text)]))
    assert receipt.purchase_date == day


def test_total_skips_foreign_currency_and_falls_back_to_amount_paid() -> None:
    eur_only = [
        summary_field("TOTAL", "206.33", "Total in EUR"),
        summary_field("TOTAL", "206.33", "Total", Currency={"Code": "EUR"}),
        summary_field("AMOUNT_PAID", "185.70", "Mastercard"),
    ]
    assert parse_expense(expense(eur_only)).total_rappen == 18570
    assert parse_expense(expense([])).total_rappen is None


def test_two_line_item_takes_last_line_of_the_row() -> None:
    rows = [row(PRICE="2.20", EXPENSE_ROW="1 2.20 2.20 1\nSt. Galler Brot ruch")]
    [item] = parse_expense(expense(rows=rows)).items
    assert item.name == "St. Galler Brot ruch"


def test_items_without_price_are_left_out_and_quantity_defaults_to_one() -> None:
    rows = [
        row(ITEM="Bananen", PRICE="2.30", QUANTITY="?"),
        row(ITEM="Bonuspunkte", QUANTITY="3"),
        row(ITEM="Äpfel", PRICE="3.10", QUANTITY="0,452"),
    ]
    items = parse_expense(expense(rows=rows)).items
    assert [(i.name, i.quantity, i.unit_price_rappen) for i in items] == [
        ("Bananen", Decimal(1), None),
        ("Äpfel", Decimal("0.452"), None),
    ]

"""Turns a Textract AnalyzeExpense result into the fields we store (docs/features/02).

Pure functions on the JSON, so they can be tested with real Textract output
(tests/data/textract_*.json). Anything that can't be read is left out (None) rather than
guessed: a receipt without a recognized date counts towards its upload month, one without a
total is missing from the store and month totals until a member corrects it.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

# Receipts from these chains get one store name each, however the header is printed
# ("MIGROS", "Genossenschaft Migros Ostschweiz"), so the report per store adds them up.
KNOWN_STORES = ("Migros", "Coop", "Aldi", "Lidl")

# "185.70", "CHF 12.50", "12,50", "1'234.50", "-1.20" and the Swiss "20.00-" for deductions.
_AMOUNT = re.compile(r"^(-)?(\d+)(?:[.,](\d{1,2}))?(-)?$")
# 17.11.2026, 17.11.26, 17/11/2026, possibly followed by a time.
_DAY_FIRST = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4}|\d{2})\b")
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


@dataclass
class ExtractedItem:
    name: str
    amount_rappen: int
    quantity: Decimal = Decimal(1)
    # As printed: for weighed goods the price per kg, for reduced items the price before the
    # reduction. So it isn't always amount / quantity.
    unit_price_rappen: int | None = None


@dataclass
class ExtractedReceipt:
    store: str | None = None
    purchase_date: date | None = None
    total_rappen: int | None = None
    items: list[ExtractedItem] = field(default_factory=list)


def parse_expense(result: dict[str, Any]) -> ExtractedReceipt:
    """Store, date, total and items of an AnalyzeExpense response.

    A photo can come back as several expense documents; the header fields are taken from the
    first document that has them and the items of all documents are kept in order.
    """
    documents = result.get("ExpenseDocuments", [])
    summary = [f for doc in documents for f in doc.get("SummaryFields", [])]
    rows = [
        row
        for doc in documents
        for group in doc.get("LineItemGroups", [])
        for row in group.get("LineItems", [])
    ]
    return ExtractedReceipt(
        store=_store(summary),
        purchase_date=_first(_parse_date, _values(summary, "INVOICE_RECEIPT_DATE")),
        total_rappen=_total(summary),
        items=[item for row in rows if (item := _item(row)) is not None],
    )


def parse_rappen(text: str) -> int | None:
    """An amount in CHF as printed on a receipt, in Rappen; None if it isn't one."""
    cleaned = re.sub(r"\s|'|CHF|Fr\.", "", text, flags=re.IGNORECASE)
    match = _AMOUNT.match(cleaned)
    if not match:
        return None
    leading_minus, francs, cents, trailing_minus = match.groups()
    rappen = int(francs) * 100 + int((cents or "0").ljust(2, "0"))
    return -rappen if leading_minus or trailing_minus else rappen


def normalize_store(text: str) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    for known in KNOWN_STORES:
        if known.lower() in text.lower():
            return known
    return " ".join(lines[0].split())


def _parse_date(text: str) -> date | None:
    if match := _ISO.search(text):
        year, month, day = map(int, match.groups())
    elif match := _DAY_FIRST.search(text):
        day, month, year = map(int, match.groups())
        year += 2000 if year < 100 else 0
    else:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _store(summary: list[dict]) -> str | None:
    vendor_names = _values(summary, "NAME", group="VENDOR") + _values(summary, "VENDOR_NAME")
    return _first(normalize_store, vendor_names)


def _total(summary: list[dict]) -> int | None:
    """TOTAL in Swiss francs, else the amount paid. Receipts also print a total in EUR."""
    for kind in ("TOTAL", "AMOUNT_PAID"):
        chf = [
            f["ValueDetection"]["Text"]
            for f in summary
            if f["Type"]["Text"] == kind and not _foreign_currency(f)
        ]
        if (total := _first(parse_rappen, chf)) is not None:
            return total
    return None


def _foreign_currency(summary_field: dict) -> bool:
    code = summary_field.get("Currency", {}).get("Code")
    label = summary_field.get("LabelDetection", {}).get("Text", "")
    return (code is not None and code != "CHF") or bool(re.search(r"\bEUR\b|€", label))


def _item(row: dict) -> ExtractedItem | None:
    fields: dict[str, str] = {}
    for f in row.get("LineItemExpenseFields", []):
        fields.setdefault(f["Type"]["Text"], f["ValueDetection"]["Text"])
    amount = parse_rappen(fields.get("PRICE", ""))
    if amount is None:
        # amount_rappen is required; a row without a price isn't an item we can count.
        return None
    return ExtractedItem(
        name=_item_name(fields),
        amount_rappen=amount,
        quantity=_quantity(fields.get("QUANTITY", "")),
        unit_price_rappen=parse_rappen(fields.get("UNIT_PRICE", "")),
    )


def _item_name(fields: dict[str, str]) -> str:
    """ITEM, or for two-line items the last line of the row's raw text (EXPENSE_ROW)."""
    if name := " ".join(fields.get("ITEM", "").split()):
        return name
    lines = [line.strip() for line in fields.get("EXPENSE_ROW", "").splitlines() if line.strip()]
    return lines[-1] if lines else "Unbekannter Artikel"


def _quantity(text: str) -> Decimal:
    try:
        quantity = Decimal(text.strip().rstrip("xX").replace(",", "."))
    except InvalidOperation:
        return Decimal(1)
    # numeric(10, 3) in the database.
    if not quantity.is_finite() or quantity <= 0 or quantity >= 10_000_000:
        return Decimal(1)
    return quantity.quantize(Decimal("0.001"))


def _values(summary: list[dict], kind: str, group: str | None = None) -> list[str]:
    return [
        f["ValueDetection"]["Text"]
        for f in summary
        if f["Type"]["Text"] == kind
        and (
            group is None or any(group in g.get("Types", []) for g in f.get("GroupProperties", []))
        )
    ]


def _first[T](parse: Callable[[str], T | None], texts: list[str]) -> T | None:
    for text in texts:
        if (value := parse(text)) is not None:
            return value
    return None

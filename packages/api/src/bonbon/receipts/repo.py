from decimal import Decimal
from uuid import UUID

from aws_lambda_powertools.event_handler.exceptions import NotFoundError, ServiceError

from bonbon import db
from bonbon.receipts.categories import DEFAULT_CATEGORY
from bonbon.receipts.models import ReceiptCorrection, ReceiptItem, ReceiptSummary, month_bounds

# The day a receipt counts towards: its purchase date, or else the day it was uploaded, in
# Swiss time (the database runs in UTC). The receipt list, its month filter and the reports
# all use this, so a receipt always shows up in the month it is counted in.
RECEIPT_DAY = "COALESCE(r.purchase_date, (r.created_at AT TIME ZONE 'Europe/Zurich')::date)"

# The upload URL is valid for 5 minutes, and the worker ends every receipt whose file arrived in
# 'done', 'failed' or 'duplicate' within 18 minutes (2 queues x 3 attempts x 180 s visibility
# timeout). A receipt still 'uploaded' after 30 minutes never got its file; the list leaves it
# out (the row itself stays).
ABANDONED = "r.status = 'uploaded' AND r.created_at < now() - interval '30 minutes'"

# The last column is possible_duplicate: same store, date and total as another done receipt of
# the household (see ReceiptSummary). Receipts missing one of the three are never flagged.
SUMMARY = (
    "SELECT r.id, r.status, r.store, r.purchase_date, r.total_rappen, u.display_name,"
    " r.created_at,"
    " (r.status = 'done' AND EXISTS ("
    "   SELECT 1 FROM receipts o WHERE o.household_id = r.household_id AND o.id <> r.id"
    "   AND o.status = 'done' AND o.store = r.store AND o.purchase_date = r.purchase_date"
    "   AND o.total_rappen = r.total_rappen))"
    " FROM receipts r LEFT JOIN users u ON u.user_id = r.uploaded_by"
)


def create(household_id: str, uploaded_by: str) -> str:
    """Add a receipt in status 'uploaded' and return its id; the file follows via S3."""
    [[receipt_id]] = db.query(
        "INSERT INTO receipts (household_id, uploaded_by) VALUES (:household_id, :uploaded_by)"
        " RETURNING id",
        household_id=UUID(household_id),
        uploaded_by=uploaded_by,
    )
    return str(receipt_id)


def list_for_household(household_id: str, month: str | None) -> list[ReceiptSummary]:
    """Newest first by the day the receipt counts towards, then latest upload first."""
    sql = SUMMARY + " WHERE r.household_id = :household_id AND NOT (" + ABANDONED + ")"
    params: dict[str, object] = {"household_id": UUID(household_id)}
    if month:
        sql += " AND " + RECEIPT_DAY + " >= :start AND " + RECEIPT_DAY + " < :end"
        params["start"], params["end"] = month_bounds(month)
    sql += " ORDER BY " + RECEIPT_DAY + " DESC, r.created_at DESC"
    return [_summary(*row) for row in db.query(sql, **params)]


def get(household_id: str, receipt_id: str) -> tuple[ReceiptSummary, list[ReceiptItem]]:
    """The receipt with its items; 404 if it doesn't exist in this household."""
    try:
        parsed = UUID(receipt_id)
    except ValueError:
        raise NotFoundError("Receipt not found") from None
    rows = db.query(
        SUMMARY + " WHERE r.id = :receipt_id AND r.household_id = :household_id",
        receipt_id=parsed,
        household_id=UUID(household_id),
    )
    if not rows:
        raise NotFoundError("Receipt not found")
    items = db.query(
        "SELECT i.position, i.name, i.quantity, i.unit_price_rappen, i.amount_rappen, c.name"
        " FROM receipt_items i JOIN categories c ON c.id = i.category_id"
        " WHERE i.receipt_id = :receipt_id ORDER BY i.position",
        receipt_id=parsed,
    )
    return _summary(*rows[0]), [
        ReceiptItem(
            position=position,
            name=name,
            quantity=quantity,
            unit_price_rappen=unit_price,
            amount_rappen=amount,
            category=category,
        )
        for position, name, quantity, unit_price, amount, category in items
    ]


def correct(household_id: str, receipt_id: str, correction: ReceiptCorrection) -> None:
    """Apply a member's correction to a done receipt, in one transaction.

    404 if the receipt isn't in this household, 409 unless it is 'done' (the worker may still
    write an 'uploaded' one; failed and duplicate receipts don't count anyway), 422 for an
    unknown category.
    """
    try:
        parsed = UUID(receipt_id)
    except ValueError:
        raise NotFoundError("Receipt not found") from None
    given = correction.model_fields_set
    with db.transaction() as conn:
        rows = conn.run(
            "SELECT status FROM receipts WHERE id = :receipt_id AND household_id = :household_id"
            " FOR UPDATE",
            receipt_id=parsed,
            household_id=UUID(household_id),
        )
        if not rows:
            raise NotFoundError("Receipt not found")
        if rows[0][0] != "done":
            raise ServiceError(409, "Only processed receipts can be corrected")
        # One statement for every combination of fields; a field left out keeps its value.
        conn.run(
            "UPDATE receipts SET"
            " store = CASE WHEN :set_store THEN :store ELSE store END,"
            " purchase_date = CASE WHEN :set_date THEN :purchase_date ELSE purchase_date END,"
            " total_rappen = CASE WHEN :set_total THEN :total_rappen ELSE total_rappen END"
            " WHERE id = :receipt_id",
            set_store="store" in given,
            store=correction.store,
            set_date="purchase_date" in given,
            purchase_date=correction.purchase_date,
            set_total="total_rappen" in given,
            total_rappen=correction.total_rappen,
            receipt_id=parsed,
        )
        if correction.items is None:
            return
        names = sorted({item.category for item in correction.items})
        category_ids = dict(
            conn.run("SELECT name, id FROM categories WHERE name = ANY(:names)", names=names)
        )
        if unknown := [name for name in names if name not in category_ids]:
            raise ServiceError(422, f"Unknown category: {', '.join(unknown)}")
        conn.run("DELETE FROM receipt_items WHERE receipt_id = :receipt_id", receipt_id=parsed)
        for item in correction.items:
            conn.run(
                "INSERT INTO receipt_items"
                " (receipt_id, position, name, quantity, unit_price_rappen, amount_rappen,"
                "  category_id)"
                " VALUES (:receipt_id, :position, :name, :quantity, :unit_price, :amount,"
                "  :category_id)",
                receipt_id=parsed,
                position=item.position,
                name=item.name,
                quantity=Decimal(str(item.quantity)).quantize(Decimal("0.001")),
                unit_price=item.unit_price_rappen,
                amount=item.amount_rappen,
                category_id=category_ids[item.category],
            )


def category_names() -> list[str]:
    return [
        name
        for [name] in db.query(
            "SELECT name FROM categories ORDER BY name = :last, name", last=DEFAULT_CATEGORY
        )
    ]


def _summary(
    receipt_id, status, store, purchase_date, total, uploaded_by_name, created_at, duplicate
) -> ReceiptSummary:
    return ReceiptSummary(
        id=str(receipt_id),
        status=status,
        store=store,
        purchase_date=purchase_date,
        total_rappen=total,
        uploaded_by_name=uploaded_by_name,
        created_at=created_at,
        possible_duplicate=duplicate,
    )

from uuid import UUID

from aws_lambda_powertools.event_handler.exceptions import NotFoundError

from bonbon import db
from bonbon.receipts.models import ReceiptItem, ReceiptSummary, month_bounds

# The day a receipt counts towards: its purchase date, or else the day it was uploaded, in
# Swiss time (the database runs in UTC). The receipt list, its month filter and the reports
# all use this, so a receipt always shows up in the month it is counted in.
RECEIPT_DAY = "COALESCE(r.purchase_date, (r.created_at AT TIME ZONE 'Europe/Zurich')::date)"

# The upload URL is valid for 5 minutes. A receipt still 'uploaded' long after that never got
# its file; the list leaves it out (the row itself stays).
ABANDONED = "r.status = 'uploaded' AND r.created_at < now() - interval '15 minutes'"

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

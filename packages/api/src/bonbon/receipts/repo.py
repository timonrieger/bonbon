from typing import Literal
from uuid import UUID

from aws_lambda_powertools.event_handler.exceptions import NotFoundError
from pg8000.native import Connection

from bonbon import db
from bonbon.receipts.categories import categorize
from bonbon.receipts.expense import ExtractedReceipt
from bonbon.receipts.models import ReceiptItem, ReceiptSummary, month_bounds

# What the database worker did with a receipt: its new status, 'unchanged' if it had left
# 'uploaded' already (a second delivery), 'missing' if the receipt no longer exists.
WorkerOutcome = Literal["done", "duplicate", "failed", "unchanged", "missing"]

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


def finish_extracted(
    household_id: UUID, receipt_id: UUID, file_hash: str, receipt: ExtractedReceipt
) -> WorkerOutcome:
    """Store what Textract read and set 'done', or 'duplicate' for a file already in the household.

    One transaction, guarded by status 'uploaded' (docs/decisions/0007): a second delivery
    changes nothing, and a crash rolls back everything, so the retry starts clean. Two uploads
    of the same file processed at the same time collide on the file-hash index; the loser rolls
    back, and its retry finds the other receipt and becomes 'duplicate'.
    """
    # Before the transaction: categorize() may load its rules from the database, and a query
    # that reconnects in the middle of an open transaction would lose it.
    categories = [categorize(item.name) for item in receipt.items]
    with db.transaction() as conn:
        status = _lock_uploaded(conn, household_id, receipt_id)
        if status != "uploaded":
            return status
        same_file = conn.run(
            "SELECT 1 FROM receipts WHERE household_id = :household_id"
            " AND file_hash = :file_hash AND id <> :receipt_id"
            " AND status NOT IN ('duplicate', 'failed')",
            household_id=household_id,
            file_hash=file_hash,
            receipt_id=receipt_id,
        )
        outcome: WorkerOutcome = "duplicate" if same_file else "done"
        # A duplicate keeps store, date and total so the list shows which receipt it is, but
        # no items: it never counts in the reports.
        conn.run(
            "UPDATE receipts SET status = :status, file_hash = :file_hash, store = :store,"
            " purchase_date = :purchase_date, total_rappen = :total_rappen, processed_at = now()"
            " WHERE id = :receipt_id",
            status=outcome,
            file_hash=file_hash,
            store=receipt.store,
            purchase_date=receipt.purchase_date,
            total_rappen=receipt.total_rappen,
            receipt_id=receipt_id,
        )
        if outcome == "done":
            for position, (item, category) in enumerate(
                zip(receipt.items, categories, strict=True), start=1
            ):
                # A category name that doesn't exist fails the NOT NULL on category_id, so a
                # wrong rule shows up as an error instead of a silently dropped item.
                conn.run(
                    "INSERT INTO receipt_items"
                    " (receipt_id, position, name, quantity, unit_price_rappen, amount_rappen,"
                    "  category_id)"
                    " VALUES (:receipt_id, :position, :name, :quantity, :unit_price, :amount,"
                    "  (SELECT id FROM categories WHERE name = :category))",
                    receipt_id=receipt_id,
                    position=position,
                    name=item.name,
                    quantity=item.quantity,
                    unit_price=item.unit_price_rappen,
                    amount=item.amount_rappen,
                    category=category,
                )
        return outcome


def finish_failed(household_id: UUID, receipt_id: UUID) -> WorkerOutcome:
    """Set 'failed' after Textract gave up on the file; same guard as finish_extracted()."""
    with db.transaction() as conn:
        status = _lock_uploaded(conn, household_id, receipt_id)
        if status != "uploaded":
            return status
        conn.run(
            "UPDATE receipts SET status = 'failed', processed_at = now() WHERE id = :receipt_id",
            receipt_id=receipt_id,
        )
        return "failed"


def _lock_uploaded(
    conn: Connection, household_id: UUID, receipt_id: UUID
) -> Literal["uploaded", "unchanged", "missing"]:
    """Lock the receipt row for this transaction and tell whether the worker may still write it."""
    rows = conn.run(
        "SELECT status FROM receipts WHERE id = :receipt_id AND household_id = :household_id"
        " FOR UPDATE",
        receipt_id=receipt_id,
        household_id=household_id,
    )
    if not rows:
        return "missing"
    return "uploaded" if rows[0][0] == "uploaded" else "unchanged"


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

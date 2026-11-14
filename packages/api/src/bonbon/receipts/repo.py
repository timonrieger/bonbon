from uuid import UUID

from bonbon import db


def create(household_id: str, uploaded_by: str) -> str:
    """Add a receipt in status 'uploaded' and return its id; the file follows via S3."""
    [[receipt_id]] = db.query(
        "INSERT INTO receipts (household_id, uploaded_by) VALUES (:household_id, :uploaded_by)"
        " RETURNING id",
        household_id=UUID(household_id),
        uploaded_by=uploaded_by,
    )
    return str(receipt_id)

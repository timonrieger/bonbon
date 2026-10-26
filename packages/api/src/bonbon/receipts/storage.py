"""S3 key layout for receipt files. The presigned upload and the worker both go through here."""

import os


def bucket_name() -> str:
    return os.environ["RECEIPTS_BUCKET"]


def receipt_key(household_id: str, receipt_id: str) -> str:
    return f"households/{household_id}/receipts/{receipt_id}"


def parse_receipt_key(key: str) -> tuple[str, str]:
    """Return (household_id, receipt_id) from a key built by receipt_key()."""
    match key.split("/"):
        case ["households", household_id, "receipts", receipt_id]:
            return household_id, receipt_id
    raise ValueError(f"Not a receipt key: {key}")

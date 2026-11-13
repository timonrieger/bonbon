"""S3 key layout for receipt files. The presigned upload and the worker both go through here."""

import os
from functools import cache

import boto3
from botocore.config import Config

# Unprocessed files carry this tag; the bucket's lifecycle rule deletes them after 7 days.
# The worker removes the tag once the receipt is processed.
PENDING_TAG = "status=pending"


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


@cache
def _s3():
    return boto3.client("s3", config=Config(signature_version="s3v4"))


def presigned_upload(
    key: str, content_type: str, size_bytes: int, expires_in: int
) -> tuple[str, dict[str, str]]:
    """URL and headers for one browser PUT of the file.

    Signed locally, so no network access is needed (the API Lambdas run in a VPC without a
    route to S3). Type, size and the pending tag are part of the signature: S3 rejects a PUT
    that changes any of them.
    """
    url = _s3().generate_presigned_url(
        "put_object",
        Params={
            "Bucket": bucket_name(),
            "Key": key,
            "ContentType": content_type,
            "ContentLength": size_bytes,
            "Tagging": PENDING_TAG,
        },
        ExpiresIn=expires_in,
    )
    # Content-Length is set by the browser itself from the file and can't be sent by hand.
    return url, {"Content-Type": content_type, "x-amz-tagging": PENDING_TAG}

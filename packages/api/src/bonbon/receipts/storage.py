"""S3 key layout for receipt files. The presigned upload and the worker both go through here."""

import json
import os
from functools import cache
from typing import Any

import boto3
from botocore.config import Config

# Unprocessed files carry this tag; the bucket's lifecycle rule deletes them after 7 days.
# The database worker removes the tag once the receipt is processed (remove_pending_tag()).
PENDING_TAG = "status=pending"


def bucket_name() -> str:
    return os.environ["RECEIPTS_BUCKET"]


def receipt_key(household_id: str, receipt_id: str) -> str:
    return f"households/{household_id}/receipts/{receipt_id}"


def result_key(household_id: str, receipt_id: str) -> str:
    """Where the Textract Lambda stores the raw AnalyzeExpense JSON of a receipt.

    Outside households/, so storing it doesn't trigger the bucket notification again; the
    lifecycle rule deletes everything under textract-results/ after 30 days.
    """
    return f"textract-results/{household_id}/{receipt_id}.json"


def parse_receipt_key(key: str) -> tuple[str, str]:
    """Return (household_id, receipt_id) from a key built by receipt_key()."""
    match key.split("/"):
        case ["households", household_id, "receipts", receipt_id]:
            return household_id, receipt_id
    raise ValueError(f"Not a receipt key: {key}")


def read_object(key: str) -> bytes:
    """Return the bytes of an object in the receipts bucket (used by the Textract Lambda)."""
    return _s3().get_object(Bucket=bucket_name(), Key=key)["Body"].read()


def put_json(key: str, data: bytes) -> None:
    """Store a JSON object in the receipts bucket (the raw Textract result)."""
    _s3().put_object(Bucket=bucket_name(), Key=key, Body=data, ContentType="application/json")


def household_prefixes(household_id: str) -> tuple[str, str]:
    """Every key of a household starts with one of these: its receipt files and Textract results."""
    return f"households/{household_id}/", f"textract-results/{household_id}/"


def delete_household_files(household_id: str) -> int:
    """Delete all files of a household from the bucket and return how many there were.

    Called by the households Lambda (inside the VPC, through the S3 gateway endpoint) after the
    household is gone from the database. Short timeouts, so an unreachable S3 fails the cleanup
    within seconds instead of the whole 15 s request.
    """
    s3 = _s3_cleanup()
    deleted = 0
    for prefix in household_prefixes(household_id):
        for page in s3.get_paginator("list_objects_v2").paginate(
            Bucket=bucket_name(), Prefix=prefix
        ):
            # A page has at most 1000 keys, which is also the limit of one delete_objects call.
            keys = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
            if keys:
                s3.delete_objects(Bucket=bucket_name(), Delete={"Objects": keys, "Quiet": True})
                deleted += len(keys)
    return deleted


@cache
def _s3():
    # Every call must fail well within the workers' 30 s Lambda timeout, also without a route to
    # S3 (no gateway endpoint in the VPC): at most 5 s connect + 10 s read = 15 s. No retries
    # inside the invocation; SQS retries the whole message. Presigning makes no calls.
    return boto3.client(
        "s3",
        config=Config(
            signature_version="s3v4",
            connect_timeout=5,
            read_timeout=10,
            retries={"mode": "standard", "max_attempts": 1},
        ),
    )


@cache
def _s3_cleanup():
    # One retry; connect and read time out fast (see delete_household_files).
    return boto3.client(
        "s3",
        config=Config(
            connect_timeout=2, read_timeout=5, retries={"max_attempts": 2, "mode": "standard"}
        ),
    )


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


def presigned_download(key: str, expires_in: int) -> str:
    """URL for the browser to GET the original file, signed locally like the upload."""
    return _s3().generate_presigned_url(
        "get_object", Params={"Bucket": bucket_name(), "Key": key}, ExpiresIn=expires_in
    )


def read_json(key: str) -> Any:
    """A JSON object from the bucket, e.g. a raw Textract result under textract-results/."""
    return json.loads(_s3().get_object(Bucket=bucket_name(), Key=key)["Body"].read())


def remove_pending_tag(key: str) -> None:
    """Keep a processed file: the lifecycle rule only deletes files tagged status=pending.

    Removes all tags; the pending tag is the only one we set. Safe to call twice.
    """
    _s3().delete_object_tagging(Bucket=bucket_name(), Key=key)

import hashlib
import json
import os
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import boto3
import pytest
from bonbon.handlers import process_receipt
from bonbon.receipts.storage import receipt_key, result_key
from botocore.exceptions import ClientError
from conftest import LambdaContext

HOUSEHOLD = str(uuid4())
RECEIPT = str(uuid4())
RESULTS_QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/bonbon-results-test"


@pytest.fixture(autouse=True)
def worker_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESULTS_QUEUE_URL", RESULTS_QUEUE_URL)
    monkeypatch.setenv("MAX_RECEIVE_COUNT", "3")
    # Reset the cached boto3 clients so each test gets ones bound to the moto mock.
    process_receipt._textract.cache_clear()
    process_receipt._sqs.cache_clear()


def s3_event(key: str) -> dict:
    return {
        "Records": [
            {
                "eventName": "ObjectCreated:Put",
                "s3": {"bucket": {"name": "b"}, "object": {"key": key, "size": 1}},
            }
        ]
    }


def invoke(body: dict, *, receive_count: int = 1) -> Any:
    event = {
        "Records": [
            {
                "messageId": "msg-0",
                "body": json.dumps(body),
                "eventSource": "aws:sqs",
                "attributes": {"ApproximateReceiveCount": str(receive_count)},
                "messageAttributes": {},
            }
        ]
    }
    context: Any = LambdaContext()
    return process_receipt.handler(event, context)


def seed_bucket_and_queue(image: bytes, key: str) -> tuple[Any, str]:
    """Create the bucket with one uploaded file and the results queue; return (s3, queue_url)."""
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=os.environ["RECEIPTS_BUCKET"])
    s3.put_object(
        Bucket=os.environ["RECEIPTS_BUCKET"], Key=key, Body=image, Tagging="status=pending"
    )
    sqs = boto3.client("sqs", region_name="us-east-1")
    queue_url = sqs.create_queue(QueueName="bonbon-results-test")["QueueUrl"]
    return s3, queue_url


def read_one_message(queue_url: str) -> dict:
    sqs = boto3.client("sqs", region_name="us-east-1")
    msgs = sqs.receive_message(QueueUrl=queue_url).get("Messages", [])
    assert len(msgs) == 1
    return json.loads(msgs[0]["Body"])


def textract_client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "x"}}, "AnalyzeExpense")


def test_extracts_and_sends_result() -> None:
    image = b"receipt-bytes"
    key = receipt_key(HOUSEHOLD, RECEIPT)
    s3, queue_url = seed_bucket_and_queue(image, key)

    fake_textract = {"ExpenseDocuments": [{"SummaryFields": []}]}
    with patch.object(process_receipt, "_textract") as textract:
        textract.return_value.analyze_expense.return_value = fake_textract
        # The real results queue url is faked; point the sender at the moto queue.
        with patch.dict(os.environ, {"RESULTS_QUEUE_URL": queue_url}):
            process_receipt._sqs.cache_clear()
            result = invoke(s3_event(key))

    assert result == {"batchItemFailures": []}

    # Raw JSON stored outside households/
    out_key = result_key(HOUSEHOLD, RECEIPT)
    stored = s3.get_object(Bucket=os.environ["RECEIPTS_BUCKET"], Key=out_key)["Body"].read()
    assert json.loads(stored) == fake_textract

    # one ExtractedResult on the results queue, in the agreed format
    assert read_one_message(queue_url) == {
        "outcome": "extracted",
        "household_id": HOUSEHOLD,
        "receipt_id": RECEIPT,
        "result_key": out_key,
        "file_hash": hashlib.sha256(image).hexdigest(),
    }


def test_ignores_s3_test_event() -> None:
    result = invoke({"Event": "s3:TestEvent"})
    assert result == {"batchItemFailures": []}


def test_transient_error_retries_before_last_attempt() -> None:
    key = receipt_key(HOUSEHOLD, RECEIPT)
    _, queue_url = seed_bucket_and_queue(b"x", key)
    with patch.object(process_receipt, "_textract") as textract:
        textract.return_value.analyze_expense.side_effect = textract_client_error(
            "ThrottlingException"
        )
        with patch.dict(os.environ, {"RESULTS_QUEUE_URL": queue_url}):
            process_receipt._sqs.cache_clear()
            result = invoke(s3_event(key), receive_count=1)

    # Reported as a failure so SQS retries; no message sent yet.
    assert result == {"batchItemFailures": [{"itemIdentifier": "msg-0"}]}
    sqs = boto3.client("sqs", region_name="us-east-1")
    assert sqs.receive_message(QueueUrl=queue_url).get("Messages", []) == []


def test_transient_error_on_last_attempt_sends_failure_and_dead_letters() -> None:
    key = receipt_key(HOUSEHOLD, RECEIPT)
    _, queue_url = seed_bucket_and_queue(b"x", key)
    with patch.object(process_receipt, "_textract") as textract:
        textract.return_value.analyze_expense.side_effect = textract_client_error(
            "ThrottlingException"
        )
        with patch.dict(os.environ, {"RESULTS_QUEUE_URL": queue_url}):
            process_receipt._sqs.cache_clear()
            result = invoke(s3_event(key), receive_count=3)

    # Re-raised on the last attempt so SQS still moves it to the DLQ...
    assert result == {"batchItemFailures": [{"itemIdentifier": "msg-0"}]}
    # ...but a FailedResult was sent first so the receipt becomes 'failed'.
    assert read_one_message(queue_url) == {
        "outcome": "failed",
        "household_id": HOUSEHOLD,
        "receipt_id": RECEIPT,
        "error": "ThrottlingException",
    }


def test_permanent_error_fails_immediately_without_retry() -> None:
    key = receipt_key(HOUSEHOLD, RECEIPT)
    _, queue_url = seed_bucket_and_queue(b"x", key)
    with patch.object(process_receipt, "_textract") as textract:
        textract.return_value.analyze_expense.side_effect = textract_client_error(
            "UnsupportedDocumentException"
        )
        with patch.dict(os.environ, {"RESULTS_QUEUE_URL": queue_url}):
            process_receipt._sqs.cache_clear()
            result = invoke(s3_event(key), receive_count=1)

    # First attempt, but not re-raised: the batch is clean so SQS won't retry a hopeless file.
    assert result == {"batchItemFailures": []}
    assert read_one_message(queue_url) == {
        "outcome": "failed",
        "household_id": HOUSEHOLD,
        "receipt_id": RECEIPT,
        "error": "UnsupportedDocumentException",
    }

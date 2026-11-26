"""Textract worker: one message per uploaded receipt file (S3 ObjectCreated event).

First stage of the worker split (ADR 0007), runs OUTSIDE the VPC so it can reach Textract and
S3. For each uploaded file it calls AnalyzeExpense, stores the raw JSON in S3 under
textract-results/ and sends an ExtractedResult to the results queue. The database worker
(ProcessResultFunction, inside the VPC) consumes it, categorizes the items, writes the receipt
to PostgreSQL and removes the status=pending tag (#38).

Failures (see ADR 0007):
  - Permanent Textract errors (unsupported/bad document, unreadable file) can't improve on a
    retry, so a FailedResult is sent immediately and the message is acked.
  - Transient errors (throttling) are re-raised so SQS retries, up to MAX_RECEIVE_COUNT. On the
    last attempt a FailedResult is sent AND the error is re-raised, so the receipt becomes
    'failed' and the message still lands in the dead-letter queue.
"""

import hashlib
import json
import os
import time
from functools import cache
from pathlib import Path
from uuid import UUID

import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.batch import (
    BatchProcessor,
    EventType,
    process_partial_response,
)
from aws_lambda_powertools.utilities.batch.types import PartialItemFailureResponse
from aws_lambda_powertools.utilities.data_classes import S3Event
from aws_lambda_powertools.utilities.data_classes.sqs_event import SQSRecord
from aws_lambda_powertools.utilities.typing import LambdaContext
from botocore.config import Config
from botocore.exceptions import ClientError

from bonbon.receipts import storage
from bonbon.receipts.results import ExtractedResult, FailedResult

logger = Logger()
# raise_on_entire_batch_failure=False: with BatchSize 1 a single transient error is the whole
# batch; we want it reported as a batchItemFailure so SQS retries, not raised out of the handler.
processor = BatchProcessor(event_type=EventType.SQS, raise_on_entire_batch_failure=False)

# Textract errors that won't improve on a retry: report the receipt as failed right away.
PERMANENT_ERRORS = frozenset(
    {"UnsupportedDocumentException", "BadDocumentException", "InvalidS3ObjectException"}
)

# The Lambda has a 30 s timeout. boto3's defaults (60 s read + several retries) could outlast
# it, so Lambda would kill the invocation before the except block runs: on the last attempt no
# FailedResult would be sent and the receipt would stay 'uploaded' forever. SQS already retries
# the whole message up to MaxReceiveCount, so we don't retry inside the invocation: one attempt
# caps the worst case at 5 + 15 = 20 s, leaving ~10 s to send the FailedResult. Same idea as the
# S3 client in the database worker (#38).
_CLIENT_CONFIG = Config(
    connect_timeout=5, read_timeout=15, retries={"max_attempts": 1, "mode": "standard"}
)


@cache
def _textract():
    return boto3.client("textract", config=_CLIENT_CONFIG)


# Dev-only Textract mock (#35). Set TEXTRACT_MOCK=1 on the dev stack to skip the real
# AnalyzeExpense call and return a stored real response instead: no Textract cost, a realistic
# payload for the downstream result worker, and a configurable delay that imitates the real
# call so the queue/timeout behaviour stays representative. Off (and unset) everywhere else.
_MOCK_RESULT_PATH = (
    Path(__file__).resolve().parent.parent / "receipts" / "mock_data" / "textract_migros.json"
)
_DEFAULT_MOCK_DELAY_MS = 3300


def _textract_mock_enabled() -> bool:
    # Never mock on prod, regardless of the env var (the template already forces it off there;
    # this is a second line of defence, #35).
    return os.environ.get("STAGE") != "prod" and os.environ.get("TEXTRACT_MOCK", "") == "1"


@cache
def _mock_result() -> dict:
    return json.loads(_MOCK_RESULT_PATH.read_text())


def _analyze_expense(image: bytes) -> dict:
    """Call Textract AnalyzeExpense, or return the stored mock result on the dev stack (#35)."""
    if _textract_mock_enabled():
        delay_ms = int(os.environ.get("TEXTRACT_MOCK_DELAY_MS", _DEFAULT_MOCK_DELAY_MS))
        time.sleep(delay_ms / 1000)
        return _mock_result()
    return _textract().analyze_expense(Document={"Bytes": image})


@cache
def _sqs():
    return boto3.client("sqs", config=_CLIENT_CONFIG)


def _max_receive_count() -> int:
    # Same value as the ReceiptsQueue redrive policy (template Mappings), so "last attempt"
    # here is the delivery on which SQS would otherwise move the message to the DLQ.
    return int(os.environ["MAX_RECEIVE_COUNT"])


def _send(message: ExtractedResult | FailedResult) -> None:
    _sqs().send_message(
        QueueUrl=os.environ["RESULTS_QUEUE_URL"], MessageBody=message.model_dump_json()
    )


def process_record(record: SQSRecord) -> None:
    body = record.json_body
    # S3 sends this once when the bucket notification is created.
    if body.get("Event") == "s3:TestEvent":
        return

    for s3_record in S3Event(body).records:
        key = s3_record.s3.get_object.key
        household_id_str, receipt_id_str = storage.parse_receipt_key(key)
        household_id, receipt_id = UUID(household_id_str), UUID(receipt_id_str)
        try:
            # One download serves both Textract and the duplicate hash.
            image = storage.read_object(key)
            result = _analyze_expense(image)

            result_key = storage.result_key(household_id_str, receipt_id_str)
            storage.put_json(result_key, json.dumps(result).encode())
            _send(
                ExtractedResult(
                    household_id=household_id,
                    receipt_id=receipt_id,
                    result_key=result_key,
                    file_hash=hashlib.sha256(image).hexdigest(),
                )
            )
            logger.info(
                "Receipt extracted",
                household_id=household_id,
                receipt_id=receipt_id,
                result_key=result_key,
            )
        except Exception as exc:
            code = exc.response["Error"]["Code"] if isinstance(exc, ClientError) else ""
            permanent = code in PERMANENT_ERRORS
            attempt = int(record.attributes.approximate_receive_count)
            last_attempt = attempt >= _max_receive_count()

            if not permanent and not last_attempt:
                raise  # transient: let SQS retry, a later attempt may pass

            # Permanent error, or transient error that used up all its retries: mark the receipt
            # failed so it doesn't stay stuck at 'uploaded'.
            logger.exception(
                "Textract failed",
                household_id=household_id,
                receipt_id=receipt_id,
                error_code=code,
                permanent=permanent,
                attempt=attempt,
            )
            _send(
                FailedResult(
                    household_id=household_id, receipt_id=receipt_id, error=code or str(exc)
                )
            )

            if not permanent:
                # Last transient attempt: the error message is sent, now re-raise so the message
                # still lands in the dead-letter queue for inspection (ADR 0007).
                raise


@logger.inject_lambda_context
def handler(event: dict, context: LambdaContext) -> PartialItemFailureResponse:
    return process_partial_response(
        event=event, record_handler=process_record, processor=processor, context=context
    )

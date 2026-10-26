"""SQS worker: one message per uploaded receipt file (S3 ObjectCreated event).

Skeleton: it only logs the receipt. Extraction, categorization and status updates come later
(docs/features/01-upload-processing.md, 02-extraction-categorization.md).
"""

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

from bonbon.receipts.storage import parse_receipt_key

logger = Logger()
processor = BatchProcessor(event_type=EventType.SQS)


def process_record(record: SQSRecord) -> None:
    body = record.json_body
    # S3 sends this once when the bucket notification is created.
    if body.get("Event") == "s3:TestEvent":
        return
    for s3_record in S3Event(body).records:
        household_id, receipt_id = parse_receipt_key(s3_record.s3.get_object.key)
        logger.info("Receipt uploaded", household_id=household_id, receipt_id=receipt_id)


@logger.inject_lambda_context
def handler(event: dict, context: LambdaContext) -> PartialItemFailureResponse:
    # Failed records are retried by SQS and land in the DLQ after 3 attempts.
    return process_partial_response(
        event=event, record_handler=process_record, processor=processor, context=context
    )

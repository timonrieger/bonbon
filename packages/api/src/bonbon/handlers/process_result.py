"""SQS worker: one message per Textract result, read from the results queue (ADR 0007).

Second stage of the worker split. The Textract Lambda (outside the VPC) stores the raw
Textract JSON in S3 and sends its key to the results queue; this Lambda runs inside the VPC
and will read that JSON, categorize the items and write the receipt to PostgreSQL.

Skeleton: it only logs the message. The message format, the S3 read and the database writes
come with the extraction feature (docs/features/01-upload-processing.md,
02-extraction-categorization.md, docs/decisions/0007).
"""

from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.batch import (
    BatchProcessor,
    EventType,
    process_partial_response,
)
from aws_lambda_powertools.utilities.batch.types import PartialItemFailureResponse
from aws_lambda_powertools.utilities.data_classes.sqs_event import SQSRecord
from aws_lambda_powertools.utilities.typing import LambdaContext

logger = Logger()
processor = BatchProcessor(event_type=EventType.SQS)


def process_record(record: SQSRecord) -> None:
    logger.info("Textract result received", body=record.body)


@logger.inject_lambda_context
def handler(event: dict, context: LambdaContext) -> PartialItemFailureResponse:
    # Failed records are retried by SQS and land in the DLQ after 3 attempts.
    return process_partial_response(
        event=event, record_handler=process_record, processor=processor, context=context
    )

"""SQS worker: one message per receipt, read from the results queue (ADR 0007).

Second stage of the worker split. The Textract Lambda (outside the VPC) stores the raw
AnalyzeExpense JSON in S3 and sends an `ExtractedResult`, or a `FailedResult` when Textract
gave up (bonbon/receipts/results.py). This Lambda runs inside the VPC: it reads the JSON
through the S3 gateway endpoint, writes the receipt to PostgreSQL in one transaction and
removes the `status=pending` tag from the original file
(docs/features/01-upload-processing.md, 02-extraction-categorization.md).
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

from bonbon.receipts import repo, storage
from bonbon.receipts.expense import parse_expense
from bonbon.receipts.results import ExtractedResult, parse_result_message

logger = Logger()
processor = BatchProcessor(event_type=EventType.SQS)


def process_record(record: SQSRecord) -> None:
    # An invalid message raises: SQS retries it and moves it to the results DLQ after 3 attempts.
    message = parse_result_message(record.body)
    household_id, receipt_id = str(message.household_id), str(message.receipt_id)
    if isinstance(message, ExtractedResult):
        receipt = parse_expense(storage.read_json(message.result_key))
        outcome = repo.finish_extracted(
            message.household_id, message.receipt_id, message.file_hash, receipt
        )
        logger.info(
            "Receipt processed",
            extra={
                "outcome": outcome,
                "items": len(receipt.items),
                "household_id": household_id,
                "receipt_id": receipt_id,
            },
        )
    else:
        outcome = repo.finish_failed(message.household_id, message.receipt_id)
        logger.warning(
            "Receipt failed in Textract",
            extra={
                "outcome": outcome,
                "error": message.error,
                "household_id": household_id,
                "receipt_id": receipt_id,
            },
        )

    if outcome == "missing":
        # Deleted in the meantime (household or account deletion), together with its file.
        return
    # Also after 'unchanged': if an earlier attempt committed and then crashed, the tag is
    # still there. Every final status keeps its file, so the list can still show it.
    storage.remove_pending_tag(storage.receipt_key(household_id, receipt_id))


@logger.inject_lambda_context
def handler(event: dict, context: LambdaContext) -> PartialItemFailureResponse:
    # Failed records are retried by SQS and land in the DLQ after 3 attempts.
    return process_partial_response(
        event=event, record_handler=process_record, processor=processor, context=context
    )

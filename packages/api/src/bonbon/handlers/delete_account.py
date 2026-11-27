"""Account deletion orchestrator (feature 05, ADR 0007). SQS worker on the deletion queue,
running OUTSIDE the VPC so it can reach Lambda and Cognito. For each job (the message body is the
Cognito sub) it:

  1. invokes the cleanup Lambda (inside the VPC) synchronously for all database and S3 work, and
  2. deletes the Cognito account.

Everything is idempotent and every failure raises, so SQS retries the whole job and, after
MaxReceiveCount attempts, moves it to the DLQ (which the CloudWatch alarm watches).
"""

import json
import os
from functools import cache

import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.batch import (
    BatchProcessor,
    EventType,
    process_partial_response,
)
from aws_lambda_powertools.utilities.batch.types import PartialItemFailureResponse
from aws_lambda_powertools.utilities.data_classes.sqs_event import SQSRecord
from aws_lambda_powertools.utilities.typing import LambdaContext
from botocore.config import Config

logger = Logger()
processor = BatchProcessor(event_type=EventType.SQS, raise_on_entire_batch_failure=False)

# read_timeout must outlast the cleanup Lambda's own timeout (it does the slow S3 deletes) but
# stay under this worker's Lambda timeout, which stays under the queue's visibility timeout
# (docs/features/05-account-deletion.md): cleanup 60 < read 70 < worker 120 < visibility 180.
_LAMBDA_CONFIG = Config(
    connect_timeout=5, read_timeout=70, retries={"max_attempts": 1, "mode": "standard"}
)
_COGNITO_CONFIG = Config(
    connect_timeout=5, read_timeout=15, retries={"max_attempts": 1, "mode": "standard"}
)


@cache
def _lambda():
    return boto3.client("lambda", config=_LAMBDA_CONFIG)


@cache
def _cognito():
    return boto3.client("cognito-idp", config=_COGNITO_CONFIG)


def process_record(record: SQSRecord) -> None:
    user_id = record.body

    # 1. Database + S3 cleanup, inside the VPC. A synchronous invoke returns 200 even when the
    # cleanup raises; the error is only in FunctionError, so check it and raise, or nothing would
    # reach the DLQ.
    response = _lambda().invoke(
        FunctionName=os.environ["CLEANUP_FUNCTION_NAME"],
        Payload=json.dumps({"user_id": user_id}).encode(),
    )
    if error := response.get("FunctionError"):
        payload = response["Payload"].read().decode()
        raise RuntimeError(f"Cleanup failed for {user_id} ({error}): {payload}")

    # 2. Delete the Cognito account last. Already gone (a retry) counts as success.
    cognito = _cognito()
    try:
        cognito.admin_delete_user(UserPoolId=os.environ["USER_POOL_ID"], Username=user_id)
    except cognito.exceptions.UserNotFoundException:
        logger.info("Cognito account already deleted", user_id=user_id)
    logger.info("Account deleted", user_id=user_id)


@logger.inject_lambda_context
def handler(event: dict, context: LambdaContext) -> PartialItemFailureResponse:
    return process_partial_response(
        event=event, record_handler=process_record, processor=processor, context=context
    )

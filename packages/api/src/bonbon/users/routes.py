"""Account endpoints. This router runs in a Lambda OUTSIDE the VPC (feature 05, ADR 0007):

DELETE /users/me reaches Cognito and SQS, which VPC Lambdas can't. It never touches the
database, so it reads the user id straight from the token and leaves all data cleanup to the
deletion worker.
"""

import os
from functools import cache

import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler import Response
from aws_lambda_powertools.event_handler.api_gateway import Router
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from bonbon.auth import user_id_from_token

router = Router()
logger = Logger()

# Bound the AWS calls well within the Lambda's 15 s timeout: read_timeout=5 so a hanging SQS or
# Cognito call returns a clean 5xx instead of a Lambda timeout. There is no in-invocation retry
# and no queue redrive for this endpoint — on a 5xx the user retries the request themselves.
_CLIENT_CONFIG = Config(
    connect_timeout=5, read_timeout=5, retries={"max_attempts": 1, "mode": "standard"}
)


@cache
def _cognito():
    return boto3.client("cognito-idp", config=_CLIENT_CONFIG)


@cache
def _sqs():
    return boto3.client("sqs", config=_CLIENT_CONFIG)


@router.delete(
    "/users/me",
    operation_id="deleteAccount",
    tags=["users"],
    status_code=202,
    responses={202: {"description": "Deletion accepted; account and data are removed shortly"}},
)
def delete_account() -> Response[None]:
    """Delete the signed-in account and all its data (feature 05).

    Queue the deletion job first, then disable the Cognito account, then return 202. The worker
    does the data cleanup and deletes the Cognito account at the end
    (docs/features/05-account-deletion.md).

    Order (team decision, issue #58): queue before disable. If queueing fails, nothing happened
    and the error propagates as a 5xx, so the account stays active and the user can retry. If
    disabling fails after the job is queued, the job is already on its way and the worker both
    tombstones the id and deletes the Cognito account, so we still return 202 and only log it.
    Both the endpoint and the worker are idempotent: a second click just queues a second job,
    which the worker no-ops.
    """
    user_id = user_id_from_token(router)
    _sqs().send_message(QueueUrl=os.environ["DELETION_QUEUE_URL"], MessageBody=user_id)
    try:
        _cognito().admin_disable_user(UserPoolId=os.environ["USER_POOL_ID"], Username=user_id)
    except BotoCoreError, ClientError:
        # The job is queued; the worker tombstones and deletes the account anyway. Don't fail the
        # request, or the user would retry a deletion that is already running.
        logger.exception(
            "Could not disable the account; the worker will handle it", user_id=user_id
        )
    logger.info("Account deletion queued", user_id=user_id)
    return Response(status_code=202)

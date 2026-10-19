import json
import os
from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from moto import mock_aws

os.environ.update(
    TABLE_NAME="bonbon-test",
    AWS_DEFAULT_REGION="us-east-1",
    AWS_ACCESS_KEY_ID="testing",
    AWS_SECRET_ACCESS_KEY="testing",
    POWERTOOLS_SERVICE_NAME="bonbon-test",
)


@pytest.fixture(autouse=True)
def aws() -> Iterator[None]:
    """Fake AWS for every test, with the same table layout as template.yaml."""
    from bonbon import db

    db.table.cache_clear()
    with mock_aws():
        boto3.client("dynamodb").create_table(
            TableName=os.environ["TABLE_NAME"],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield


class LambdaContext:
    function_name = "test"
    memory_limit_in_mb = 128
    invoked_function_arn = "arn:aws:lambda:us-east-1:123456789012:function:test"
    aws_request_id = "test"


def api_request(
    handler: Any,
    method: str,
    path: str,
    *,
    user: str = "user-1",
    body: dict | None = None,
) -> tuple[int, Any]:
    """Call a Lambda handler like API Gateway would, signed in as `user`."""
    event = {
        "httpMethod": method,
        "path": path,
        "resource": path,
        "headers": {"Content-Type": "application/json"},
        "multiValueHeaders": {},
        "queryStringParameters": None,
        "multiValueQueryStringParameters": None,
        "pathParameters": None,
        "body": json.dumps(body) if body is not None else None,
        "isBase64Encoded": False,
        "requestContext": {"authorizer": {"claims": {"sub": user}}, "stage": "api"},
    }
    response = handler(event, LambdaContext())
    return response["statusCode"], json.loads(response["body"]) if response["body"] else None

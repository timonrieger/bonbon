import json
import os
from collections.abc import Iterator
from typing import Any

import pytest
from fakes import FakeDatabase
from moto import mock_aws

os.environ.update(
    AWS_DEFAULT_REGION="us-east-1",
    AWS_ACCESS_KEY_ID="testing",
    AWS_SECRET_ACCESS_KEY="testing",
    POWERTOOLS_SERVICE_NAME="bonbon-test",
)


@pytest.fixture(autouse=True)
def aws() -> Iterator[None]:
    """Fake AWS for every test, so nothing ever reaches a real account."""
    with mock_aws():
        yield


@pytest.fixture(autouse=True)
def database(monkeypatch: pytest.MonkeyPatch) -> FakeDatabase:
    """Replace every SQL function with an in-memory fake (see tests/fakes.py)."""
    from bonbon import auth, db
    from bonbon.households import repo as households

    def no_real_database(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("A test reached the real database; add a fake in tests/fakes.py")

    fake = FakeDatabase()
    monkeypatch.setattr(db, "connect", no_real_database)
    monkeypatch.setattr(auth, "role_in_household", fake.role_in_household)
    monkeypatch.setattr(households, "create", fake.create_household)
    monkeypatch.setattr(households, "get", fake.get_household)
    return fake


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
    query: dict[str, str] | None = None,
) -> tuple[int, Any]:
    """Call a Lambda handler like API Gateway would, signed in as `user`."""
    event = {
        "httpMethod": method,
        "path": path,
        "resource": path,
        "headers": {"Content-Type": "application/json"},
        "multiValueHeaders": {},
        "queryStringParameters": query,
        "multiValueQueryStringParameters": {k: [v] for k, v in query.items()} if query else None,
        "pathParameters": None,
        "body": json.dumps(body) if body is not None else None,
        "isBase64Encoded": False,
        "requestContext": {"authorizer": {"claims": {"sub": user}}, "stage": "api"},
    }
    response = handler(event, LambdaContext())
    return response["statusCode"], json.loads(response["body"]) if response["body"] else None

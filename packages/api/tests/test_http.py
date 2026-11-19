from typing import Any, cast

import pytest
from aws_lambda_powertools.event_handler.api_gateway import Router
from bonbon.http import make_resolver
from conftest import LambdaContext

APP_ORIGIN = "https://d111111abcdef8.cloudfront.net"


def ping_with_origin(origin: str) -> dict[str, list[str]]:
    router = Router()

    @router.get("/ping")
    def ping() -> dict:
        return {}

    event = {
        "httpMethod": "GET",
        "path": "/ping",
        "resource": "/ping",
        "headers": {"Origin": origin},
        "multiValueHeaders": {"Origin": [origin]},
        "queryStringParameters": None,
        "multiValueQueryStringParameters": None,
        "pathParameters": None,
        "body": None,
        "isBase64Encoded": False,
        "requestContext": {"stage": "api"},
    }
    return make_resolver(router).resolve(event, cast(Any, LambdaContext()))["multiValueHeaders"]


def test_cors_allows_the_app_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOWED_ORIGIN", APP_ORIGIN)

    assert ping_with_origin(APP_ORIGIN)["Access-Control-Allow-Origin"] == [APP_ORIGIN]


def test_cors_ignores_other_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOWED_ORIGIN", APP_ORIGIN)

    assert "Access-Control-Allow-Origin" not in ping_with_origin("https://evil.example")

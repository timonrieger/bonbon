import json
from typing import Any

from bonbon.handlers.process_receipt import handler
from bonbon.receipts.storage import parse_receipt_key, receipt_key
from conftest import LambdaContext


def invoke(*bodies: dict) -> Any:
    """Call the worker like the SQS event source would, one message per body."""
    event = {
        "Records": [
            {
                "messageId": f"msg-{i}",
                "body": json.dumps(body),
                "eventSource": "aws:sqs",
                "attributes": {},
                "messageAttributes": {},
            }
            for i, body in enumerate(bodies)
        ]
    }
    context: Any = LambdaContext()
    return handler(event, context)


def s3_created(key: str) -> dict:
    return {
        "Records": [
            {
                "eventName": "ObjectCreated:Put",
                "s3": {"bucket": {"name": "receipts"}, "object": {"key": key, "size": 1}},
            }
        ]
    }


def test_receipt_key_round_trip() -> None:
    assert parse_receipt_key(receipt_key("hh-1", "r-1")) == ("hh-1", "r-1")


def test_processes_receipt_upload() -> None:
    result = invoke(s3_created(receipt_key("hh-1", "r-1")))
    assert result == {"batchItemFailures": []}


def test_ignores_s3_test_event() -> None:
    result = invoke({"Event": "s3:TestEvent"})
    assert result == {"batchItemFailures": []}


def test_reports_unknown_key_as_failure() -> None:
    result = invoke(s3_created(receipt_key("hh-1", "r-1")), s3_created("somewhere/else"))
    assert result == {"batchItemFailures": [{"itemIdentifier": "msg-1"}]}

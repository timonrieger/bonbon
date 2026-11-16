import json
from typing import Any

from bonbon.handlers.process_result import handler
from conftest import LambdaContext


def invoke(*bodies: str) -> Any:
    """Call the worker like the SQS event source would, one message per body."""
    event = {
        "Records": [
            {
                "messageId": f"msg-{i}",
                "body": body,
                "eventSource": "aws:sqs",
                "attributes": {},
                "messageAttributes": {},
            }
            for i, body in enumerate(bodies)
        ]
    }
    context: Any = LambdaContext()
    return handler(event, context)


def test_processes_result_message() -> None:
    result = invoke(json.dumps({"result_key": "results/hh-1/r-1.json"}))
    assert result == {"batchItemFailures": []}


def test_processes_batch_of_messages() -> None:
    result = invoke(
        json.dumps({"result_key": "results/hh-1/r-1.json"}),
        json.dumps({"result_key": "results/hh-1/r-2.json"}),
    )
    assert result == {"batchItemFailures": []}

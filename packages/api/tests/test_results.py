import json
from uuid import uuid4

import pytest
from bonbon.receipts.results import ExtractedResult, FailedResult, parse_result_message
from bonbon.receipts.storage import result_key
from pydantic import ValidationError

HOUSEHOLD, RECEIPT = uuid4(), uuid4()
HASH = "a" * 64


def test_extracted_round_trip() -> None:
    sent = ExtractedResult(
        household_id=HOUSEHOLD,
        receipt_id=RECEIPT,
        result_key=result_key(str(HOUSEHOLD), str(RECEIPT)),
        file_hash=HASH,
    )
    body = sent.model_dump_json()
    assert json.loads(body)["outcome"] == "extracted"
    assert parse_result_message(body) == sent


def test_failed_round_trip() -> None:
    sent = FailedResult(household_id=HOUSEHOLD, receipt_id=RECEIPT, error="BadDocumentException")
    assert parse_result_message(sent.model_dump_json()) == sent


def test_result_key_is_outside_households() -> None:
    """Under households/ the bucket notification would fire again for the result."""
    assert result_key("h", "r") == "textract-results/h/r.json"


@pytest.mark.parametrize(
    "message",
    [
        {"outcome": "done"},
        # No outcome: the consumer must not guess from the fields.
        {"household_id": str(HOUSEHOLD), "receipt_id": str(RECEIPT), "error": "x"},
        {
            "outcome": "failed",
            "household_id": "not-a-uuid",
            "receipt_id": str(RECEIPT),
            "error": "x",
        },
        {
            "outcome": "extracted",
            "household_id": str(HOUSEHOLD),
            "receipt_id": str(RECEIPT),
            "result_key": f"households/{HOUSEHOLD}/receipts/{RECEIPT}",
            "file_hash": HASH,
        },
        {
            "outcome": "extracted",
            "household_id": str(HOUSEHOLD),
            "receipt_id": str(RECEIPT),
            "result_key": result_key(str(HOUSEHOLD), str(RECEIPT)),
            "file_hash": "A" * 64,
        },
    ],
)
def test_invalid_messages_are_rejected(message: dict) -> None:
    with pytest.raises(ValidationError):
        parse_result_message(json.dumps(message))

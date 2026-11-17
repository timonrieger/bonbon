import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import UUID

import boto3
import pytest
from aws_lambda_powertools.utilities.batch.exceptions import BatchProcessingError
from bonbon.handlers.process_result import handler
from bonbon.receipts.results import ExtractedResult, FailedResult
from bonbon.receipts.storage import PENDING_TAG, bucket_name, receipt_key
from conftest import LambdaContext
from fakes import FakeDatabase

MIGROS = json.loads((Path(__file__).parent / "data" / "textract_migros.json").read_text())
HASH = hashlib.sha256(b"photo").hexdigest()


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


@pytest.fixture
def s3() -> Any:
    client = boto3.client("s3")
    client.create_bucket(Bucket=bucket_name())
    return client


@pytest.fixture
def household_id(database: FakeDatabase) -> UUID:
    database.sync_user("user-1", "User 1", None)
    return UUID(database.create_household("WG", "user-1").id)


def upload(database: FakeDatabase, s3: Any, household_id: UUID, **fields: Any) -> UUID:
    """A receipt whose file arrived (tagged pending) and whose Textract result is in S3."""
    receipt_id = database.add_receipt(household_id, "user-1", **fields)
    s3.put_object(
        Bucket=bucket_name(),
        Key=receipt_key(str(household_id), str(receipt_id)),
        Body=b"photo",
        Tagging=PENDING_TAG,
    )
    s3.put_object(
        Bucket=bucket_name(), Key=result_key(household_id, receipt_id), Body=json.dumps(MIGROS)
    )
    return receipt_id


def result_key(household_id: UUID, receipt_id: UUID) -> str:
    return f"textract-results/{household_id}/{receipt_id}.json"


def extracted(household_id: UUID, receipt_id: UUID, file_hash: str = HASH) -> str:
    return ExtractedResult(
        household_id=household_id,
        receipt_id=receipt_id,
        result_key=result_key(household_id, receipt_id),
        file_hash=file_hash,
    ).model_dump_json()


def tags(s3: Any, household_id: UUID, receipt_id: UUID) -> list:
    key = receipt_key(str(household_id), str(receipt_id))
    return s3.get_object_tagging(Bucket=bucket_name(), Key=key)["TagSet"]


def test_extracted_receipt_is_done_with_items_and_keeps_its_file(
    database: FakeDatabase, s3: Any, household_id: UUID
) -> None:
    receipt_id = upload(database, s3, household_id)

    assert invoke(extracted(household_id, receipt_id)) == {"batchItemFailures": []}

    receipt = database.receipts[receipt_id]
    assert (receipt.status, receipt.store, receipt.total_rappen) == ("done", "Migros", 18570)
    assert receipt.purchase_date is None
    assert receipt.file_hash == HASH
    assert len(receipt.items) == 43
    assert {item.category for item in receipt.items} == {"Sonstiges"}
    assert tags(s3, household_id, receipt_id) == []


def test_same_file_in_household_is_a_duplicate_without_items(
    database: FakeDatabase, s3: Any, household_id: UUID
) -> None:
    database.add_receipt(household_id, "user-1", status="done", file_hash=HASH)
    receipt_id = upload(database, s3, household_id)

    invoke(extracted(household_id, receipt_id))

    receipt = database.receipts[receipt_id]
    assert (receipt.status, receipt.store, receipt.items) == ("duplicate", "Migros", [])
    assert tags(s3, household_id, receipt_id) == []


def test_failed_receipt_with_the_same_file_does_not_count_as_duplicate(
    database: FakeDatabase, s3: Any, household_id: UUID
) -> None:
    database.add_receipt(household_id, "user-1", status="failed", file_hash=HASH)
    receipt_id = upload(database, s3, household_id)

    invoke(extracted(household_id, receipt_id))

    assert database.receipts[receipt_id].status == "done"


def test_same_file_in_another_household_is_no_duplicate(
    database: FakeDatabase, s3: Any, household_id: UUID
) -> None:
    other = UUID(database.create_household("Andere WG", "user-1").id)
    database.add_receipt(other, "user-1", status="done", file_hash=HASH)
    receipt_id = upload(database, s3, household_id)

    invoke(extracted(household_id, receipt_id))

    assert database.receipts[receipt_id].status == "done"


def test_textract_failure_sets_failed_and_keeps_the_file(
    database: FakeDatabase, s3: Any, household_id: UUID
) -> None:
    receipt_id = upload(database, s3, household_id)
    message = FailedResult(
        household_id=household_id, receipt_id=receipt_id, error="UnsupportedDocumentException"
    ).model_dump_json()

    assert invoke(message) == {"batchItemFailures": []}

    receipt = database.receipts[receipt_id]
    assert (receipt.status, receipt.items) == ("failed", [])
    assert tags(s3, household_id, receipt_id) == []


def test_second_delivery_changes_nothing_but_still_removes_the_tag(
    database: FakeDatabase, s3: Any, household_id: UUID
) -> None:
    """E.g. the first attempt committed and crashed before it removed the tag."""
    receipt_id = upload(database, s3, household_id, status="done", store="Coop")

    assert invoke(extracted(household_id, receipt_id)) == {"batchItemFailures": []}

    receipt = database.receipts[receipt_id]
    assert (receipt.status, receipt.store, receipt.items) == ("done", "Coop", [])
    assert tags(s3, household_id, receipt_id) == []


def test_deleted_receipt_is_skipped(database: FakeDatabase, s3: Any, household_id: UUID) -> None:
    receipt_id = upload(database, s3, household_id)
    del database.receipts[receipt_id]

    assert invoke(extracted(household_id, receipt_id)) == {"batchItemFailures": []}
    # Untouched: with the receipt, its file would be deleted as well.
    assert tags(s3, household_id, receipt_id) == [{"Key": "status", "Value": "pending"}]


def test_receipt_of_another_household_is_not_touched(
    database: FakeDatabase, s3: Any, household_id: UUID
) -> None:
    receipt_id = upload(database, s3, household_id)
    other = UUID(database.create_household("Andere WG", "user-1").id)

    invoke(FailedResult(household_id=other, receipt_id=receipt_id, error="x").model_dump_json())

    assert database.receipts[receipt_id].status == "uploaded"


@pytest.mark.parametrize(
    "body",
    [
        "not json",
        json.dumps({"result_key": "textract-results/a/b.json"}),
        json.dumps({"outcome": "done", "household_id": str(UUID(int=1))}),
    ],
)
def test_invalid_message_is_retried(body: str) -> None:
    # With every record of the batch failed, the invocation fails and SQS retries the message.
    with pytest.raises(BatchProcessingError):
        invoke(body)


def test_missing_textract_result_is_retried(
    database: FakeDatabase, s3: Any, household_id: UUID
) -> None:
    receipt_id = upload(database, s3, household_id)
    s3.delete_object(Bucket=bucket_name(), Key=result_key(household_id, receipt_id))

    with pytest.raises(BatchProcessingError):
        invoke(extracted(household_id, receipt_id))
    assert database.receipts[receipt_id].status == "uploaded"


def test_one_failed_message_does_not_fail_the_others(
    database: FakeDatabase, s3: Any, household_id: UUID
) -> None:
    receipt_id = upload(database, s3, household_id)

    result = invoke("not json", extracted(household_id, receipt_id))

    assert result == {"batchItemFailures": [{"itemIdentifier": "msg-0"}]}
    assert database.receipts[receipt_id].status == "done"

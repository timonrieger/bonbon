import json
import os
from typing import Any
from uuid import UUID

import boto3
import pytest
from bonbon.handlers import delete_account, delete_cleanup
from conftest import LambdaContext
from fakes import FakeDatabase

# --- Cleanup Lambda (inside the VPC): the database + S3 steps -----------------------------------


def seed_bucket(household_id: str) -> Any:
    """A receipts bucket with one file for the household under both of its prefixes."""
    s3 = boto3.client("s3", region_name="us-east-1")
    bucket = os.environ["RECEIPTS_BUCKET"]
    s3.create_bucket(Bucket=bucket)
    s3.put_object(Bucket=bucket, Key=f"households/{household_id}/r1", Body=b"x")
    s3.put_object(Bucket=bucket, Key=f"textract-results/{household_id}/r1.json", Body=b"{}")
    return s3


def bucket_keys(s3: Any) -> list[str]:
    objects = s3.list_objects_v2(Bucket=os.environ["RECEIPTS_BUCKET"]).get("Contents", [])
    return [o["Key"] for o in objects]


def cleanup(user_id: str) -> dict:
    context: Any = LambdaContext()
    return delete_cleanup.handler({"user_id": user_id}, context)


def test_sole_member_household_is_fully_removed(database: FakeDatabase) -> None:
    database.sync_user("user-1", "Ada", None)
    household_id = database.create_household("H", "user-1").id
    s3 = seed_bucket(household_id)

    cleanup("user-1")

    assert database.is_tombstoned("user-1")
    assert "user-1" not in database.users
    assert database.list_households("user-1") == []
    assert bucket_keys(s3) == []  # S3 files gone


def test_shared_household_keeps_data_and_hands_over(database: FakeDatabase) -> None:
    database.sync_user("user-1", "Ada", None)
    database.sync_user("user-2", "Bo", None)
    household_id = database.create_household("H", "user-1").id
    database.add_member(UUID(household_id), "user-2", "member")
    s3 = seed_bucket(household_id)

    cleanup("user-1")

    assert "user-1" not in database.users  # account gone
    assert database.role_in_household(UUID(household_id), "user-1") is None  # left
    assert database.role_in_household(UUID(household_id), "user-2") == "owner"  # handed over
    assert len(bucket_keys(s3)) == 2  # shared household's files stay


def test_last_other_member_leaves_during_cleanup_deletes_files(
    database: FakeDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Race (Noel's review): the other member leaves between prepare_deletion and remove_member.
    prepare_deletion sees them and returns False (so files aren't deleted up front), but then
    remove_member finds user-1 alone, deletes the household and returns True — so the files must
    be cleaned up afterwards instead of being left orphaned."""
    database.sync_user("user-1", "Ada", None)
    database.sync_user("user-2", "Bo", None)
    household_id = database.create_household("H", "user-1").id
    database.add_member(UUID(household_id), "user-2", "member")
    s3 = seed_bucket(household_id)

    real_prepare = database.prepare_deletion

    def prepare_then_other_leaves(hid: str, uid: str) -> bool:
        result = real_prepare(hid, uid)  # False: user-2 is still a member
        # user-2 leaves right after the check, before remove_member runs.
        database.memberships = {
            k: r for k, r in database.memberships.items() if k != (UUID(hid), "user-2")
        }
        return result

    monkeypatch.setattr(delete_cleanup.households, "prepare_deletion", prepare_then_other_leaves)

    cleanup("user-1")

    assert "user-1" not in database.users  # account gone
    assert UUID(household_id) not in database.households  # household deleted by the race
    assert bucket_keys(s3) == []  # files cleaned up despite prepare_deletion returning False


def test_s3_failure_raises(database: FakeDatabase, monkeypatch: pytest.MonkeyPatch) -> None:
    database.sync_user("user-1", "Ada", None)
    database.create_household("H", "user-1")

    monkeypatch.setattr(
        delete_cleanup.storage, "delete_household_files", lambda hid: (0, [f"households/{hid}/r1"])
    )
    with pytest.raises(RuntimeError):
        cleanup("user-1")
    # The household (and the users row) must still be there, so a retry can finish the job.
    assert "user-1" in database.users


def test_cleanup_is_idempotent(database: FakeDatabase) -> None:
    database.sync_user("user-1", "Ada", None)
    household_id = database.create_household("H", "user-1").id
    seed_bucket(household_id)

    cleanup("user-1")
    cleanup("user-1")  # second run must not raise

    assert "user-1" not in database.users


# --- Orchestrator Lambda (outside the VPC): invoke cleanup, then delete the Cognito account ------


class FakeLambdaClient:
    def __init__(self, function_error: str | None = None) -> None:
        self.function_error = function_error
        self.invoked: list[str] = []

    def invoke(self, *, FunctionName: str, Payload: bytes) -> dict:
        self.invoked.append(json.loads(Payload)["user_id"])

        class _Body:
            def read(self) -> bytes:
                return b'{"errorMessage": "boom"}'

        result: dict[str, Any] = {"Payload": _Body()}
        if self.function_error:
            result["FunctionError"] = self.function_error
        return result


class UserNotFoundException(Exception):
    pass


class FakeCognitoClient:
    class exceptions:
        UserNotFoundException = UserNotFoundException

    def __init__(self, *, missing: bool = False) -> None:
        self.missing = missing
        self.deleted: list[str] = []

    def admin_delete_user(self, *, UserPoolId: str, Username: str) -> None:
        if self.missing:
            raise self.exceptions.UserNotFoundException
        self.deleted.append(Username)


def sqs_event(user_id: str) -> dict:
    return {
        "Records": [
            {
                "messageId": "msg-0",
                "body": user_id,
                "eventSource": "aws:sqs",
                "attributes": {"ApproximateReceiveCount": "1"},
                "messageAttributes": {},
            }
        ]
    }


@pytest.fixture(autouse=True)
def worker_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USER_POOL_ID", "eu-test_pool")
    monkeypatch.setenv("CLEANUP_FUNCTION_NAME", "bonbon-dev-DeleteCleanupFunction")
    delete_account._lambda.cache_clear()
    delete_account._cognito.cache_clear()


def test_worker_invokes_cleanup_then_deletes_cognito(monkeypatch: pytest.MonkeyPatch) -> None:
    lam, cog = FakeLambdaClient(), FakeCognitoClient()
    monkeypatch.setattr(delete_account, "_lambda", lambda: lam)
    monkeypatch.setattr(delete_account, "_cognito", lambda: cog)

    context: Any = LambdaContext()
    result = delete_account.handler(sqs_event("user-1"), context)

    assert result == {"batchItemFailures": []}
    assert lam.invoked == ["user-1"]
    assert cog.deleted == ["user-1"]


def test_worker_raises_when_cleanup_reports_a_function_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lam, cog = FakeLambdaClient(function_error="Unhandled"), FakeCognitoClient()
    monkeypatch.setattr(delete_account, "_lambda", lambda: lam)
    monkeypatch.setattr(delete_account, "_cognito", lambda: cog)

    context: Any = LambdaContext()
    result = delete_account.handler(sqs_event("user-1"), context)

    # The cleanup failed, so the message is a batch failure (SQS retries, then DLQ), and we did
    # NOT delete the Cognito account.
    assert result == {"batchItemFailures": [{"itemIdentifier": "msg-0"}]}
    assert cog.deleted == []


def test_worker_treats_missing_cognito_account_as_success(monkeypatch: pytest.MonkeyPatch) -> None:
    lam, cog = FakeLambdaClient(), FakeCognitoClient(missing=True)
    monkeypatch.setattr(delete_account, "_lambda", lambda: lam)
    monkeypatch.setattr(delete_account, "_cognito", lambda: cog)

    context: Any = LambdaContext()
    result = delete_account.handler(sqs_event("user-1"), context)

    assert result == {"batchItemFailures": []}  # retry-safe, no failure

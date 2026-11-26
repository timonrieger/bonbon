import boto3
import pytest
from bonbon.handlers.households import handler as households_handler
from bonbon.handlers.users import handler as users_handler
from bonbon.users import routes
from botocore.exceptions import ClientError
from conftest import api_request
from fakes import FakeDatabase


class FakeCognito:
    """Records admin_disable_user calls. moto's cognito-idp backend needs joserfc, which we don't
    install just to assert the account is disabled, so the route's client is faked directly."""

    def __init__(self) -> None:
        self.disabled: list[str] = []

    def admin_disable_user(self, *, UserPoolId: str, Username: str) -> None:
        self.disabled.append(Username)


@pytest.fixture
def account(monkeypatch: pytest.MonkeyPatch) -> tuple[str, str, FakeCognito]:
    """The deletion queue (moto) and a fake Cognito client, wired into the route.

    Returns (user_id, queue_url, cognito) so a test can sign in as that account, read the queue
    and check which users were disabled.
    """
    user_id = "user-1"
    monkeypatch.setenv("USER_POOL_ID", "eu-test_pool")

    sqs = boto3.client("sqs", region_name="us-east-1")
    queue_url = sqs.create_queue(QueueName="bonbon-deletion-test")["QueueUrl"]
    monkeypatch.setenv("DELETION_QUEUE_URL", queue_url)

    cognito = FakeCognito()
    monkeypatch.setattr(routes, "_cognito", lambda: cognito)
    # The route memoizes its SQS client; drop it so it binds to the moto mock.
    routes._sqs.cache_clear()
    return user_id, queue_url, cognito


def test_delete_account_disables_cognito_and_queues_the_job(
    account: tuple[str, str, FakeCognito],
) -> None:
    user_id, queue_url, cognito = account
    status, _ = api_request(users_handler, "DELETE", "/users/me", user=user_id)
    assert status == 202

    assert cognito.disabled == [user_id]
    sqs = boto3.client("sqs", region_name="us-east-1")
    messages = sqs.receive_message(QueueUrl=queue_url).get("Messages", [])
    assert [m["Body"] for m in messages] == [user_id]


def test_tombstoned_user_is_rejected(database: FakeDatabase) -> None:
    """Once the account is tombstoned, any authenticated request is 401 — even with a still-valid
    token — so the deletion can't be undone by the user mid-way."""
    database.tombstone("user-1")
    status, _ = api_request(households_handler, "GET", "/households", user="user-1")
    assert status == 401


def test_other_users_are_unaffected_by_a_tombstone(database: FakeDatabase) -> None:
    database.tombstone("user-1")
    status, _ = api_request(households_handler, "GET", "/households", user="user-2")
    assert status == 200


def test_disable_failure_after_queueing_still_returns_202(
    account: tuple[str, str, FakeCognito], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Issue #58 order: once the job is queued, a failed admin_disable_user must not fail the
    request — the worker tombstones and deletes the account anyway."""
    user_id, queue_url, _ = account

    class FailingCognito:
        def admin_disable_user(self, **kwargs: object) -> None:
            raise ClientError({"Error": {"Code": "InternalErrorException"}}, "AdminDisableUser")

    monkeypatch.setattr(routes, "_cognito", FailingCognito)
    status, _ = api_request(users_handler, "DELETE", "/users/me", user=user_id)
    assert status == 202

    # The job was queued before the disable attempt, so it is on the queue.
    sqs = boto3.client("sqs", region_name="us-east-1")
    messages = sqs.receive_message(QueueUrl=queue_url).get("Messages", [])
    assert [m["Body"] for m in messages] == [user_id]


def test_send_message_failure_propagates_and_does_not_disable(
    account: tuple[str, str, FakeCognito], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Issue #58 order (queue first): if queueing the job fails, nothing has happened yet. The
    error propagates (API Gateway turns it into a 5xx and the user retries) and the Cognito
    account is never disabled."""
    user_id, _, cognito = account

    def failing_send_message(**kwargs: object) -> None:
        raise ClientError({"Error": {"Code": "InternalErrorException"}}, "SendMessage")

    monkeypatch.setattr(routes._sqs(), "send_message", failing_send_message)

    with pytest.raises(ClientError):
        api_request(users_handler, "DELETE", "/users/me", user=user_id)

    # Queueing failed before the disable step, so the account was never disabled.
    assert cognito.disabled == []

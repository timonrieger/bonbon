from urllib.parse import parse_qs, urlparse

import pytest
from bonbon.handlers.households import handler as households
from bonbon.handlers.receipts import handler
from conftest import api_request

RECEIPT_ID = "00000000-0000-0000-0000-000000000001"


@pytest.fixture
def household_id() -> str:
    _, created = api_request(households, "POST", "/households", body={"name": "WG Zürich"})
    return created["id"]


def upload(household_id: str, user: str = "user-1", **body: object) -> tuple[int, dict]:
    body = {"content_type": "image/jpeg", "size_bytes": 400_000, **body}
    return api_request(
        handler, "POST", f"/households/{household_id}/receipts", user=user, body=body
    )


def test_member_gets_upload_url(household_id: str) -> None:
    status, created = upload(household_id)
    assert status == 201
    assert created["expires_in"] == 300
    assert created["upload_headers"] == {
        "Content-Type": "image/jpeg",
        "x-amz-tagging": "status=pending",
    }
    url = urlparse(created["upload_url"])
    assert url.path.endswith(f"households/{household_id}/receipts/{created['receipt_id']}")
    # Type, size and the lifecycle tag are part of the signature, so S3 enforces them.
    signed = parse_qs(url.query)["X-Amz-SignedHeaders"][0].split(";")
    assert {"content-type", "content-length", "x-amz-tagging"} <= set(signed)


def test_non_member_cannot_upload(household_id: str) -> None:
    status, _ = upload(household_id, user="stranger")
    assert status == 404


@pytest.mark.parametrize(
    "body",
    [
        {"content_type": "image/gif"},
        {"size_bytes": 0},
        {"size_bytes": 5 * 1024 * 1024 + 1},
    ],
)
def test_rejects_wrong_type_or_size(household_id: str, body: dict) -> None:
    status, _ = upload(household_id, **body)
    assert status == 422


# List and detail only fix the contract so far; members get 501 until the SQL is in place.
@pytest.mark.parametrize(
    ("path", "query"),
    [
        ("/receipts", None),
        ("/receipts", {"month": "2026-11"}),
        (f"/receipts/{RECEIPT_ID}", None),
    ],
)
def test_member_gets_not_implemented(household_id: str, path: str, query: dict | None) -> None:
    status, _ = api_request(handler, "GET", f"/households/{household_id}{path}", query=query)
    assert status == 501


@pytest.mark.parametrize("path", ["/receipts", f"/receipts/{RECEIPT_ID}"])
def test_non_member_gets_404(household_id: str, path: str) -> None:
    status, _ = api_request(handler, "GET", f"/households/{household_id}{path}", user="stranger")
    assert status == 404


@pytest.mark.parametrize("month", ["2026-13", "2026-1", "11-2026", "2026-11-01"])
def test_rejects_malformed_month(household_id: str, month: str) -> None:
    status, _ = api_request(
        handler, "GET", f"/households/{household_id}/receipts", query={"month": month}
    )
    assert status == 422

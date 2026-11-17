from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import pytest
from bonbon.handlers.households import handler as households
from bonbon.handlers.receipts import handler
from bonbon.receipts.models import ReceiptItem
from conftest import api_request
from fakes import FakeDatabase

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


def add_receipt(database: FakeDatabase, household_id: str, **fields: Any) -> str:
    """A receipt as the worker leaves it: done, uploaded by user-1."""
    fields = {"status": "done", "store": "Migros", "total_rappen": 1000, **fields}
    return str(database.add_receipt(UUID(household_id), "user-1", **fields))


def list_receipts(household_id: str, **query: str) -> tuple[int, Any]:
    return api_request(handler, "GET", f"/households/{household_id}/receipts", query=query or None)


def test_list_is_empty_for_a_new_household(household_id: str) -> None:
    assert list_receipts(household_id) == (200, {"receipts": []})


def test_list_shows_receipts_newest_first(database: FakeDatabase, household_id: str) -> None:
    older = add_receipt(database, household_id, purchase_date=date(2026, 10, 30))
    # No recognized date: counts as the day it was uploaded.
    undated = add_receipt(database, household_id, purchase_date=None)
    status, body = list_receipts(household_id)
    assert status == 200
    assert [r["id"] for r in body["receipts"]] == [undated, older]
    first = body["receipts"][0]
    assert first["purchase_date"] is None
    assert first["uploaded_by_name"] == "User-1"
    assert first["possible_duplicate"] is False


def test_list_filters_by_month(database: FakeDatabase, household_id: str) -> None:
    add_receipt(database, household_id, purchase_date=date(2026, 10, 31))
    november = add_receipt(database, household_id, purchase_date=date(2026, 11, 1))
    _, body = list_receipts(household_id, month="2026-11")
    assert [r["id"] for r in body["receipts"]] == [november]


def test_list_leaves_out_uploads_whose_file_never_arrived(
    database: FakeDatabase, household_id: str
) -> None:
    # Still within the 18 minutes the pipeline may take with all retries.
    in_pipeline = add_receipt(
        database,
        household_id,
        status="uploaded",
        created_at=datetime.now(UTC) - timedelta(minutes=29),
    )
    add_receipt(
        database,
        household_id,
        status="uploaded",
        created_at=datetime.now(UTC) - timedelta(minutes=31),
    )
    _, body = list_receipts(household_id)
    assert [r["id"] for r in body["receipts"]] == [in_pipeline]


def test_list_flags_same_store_date_and_total(database: FakeDatabase, household_id: str) -> None:
    same = {"purchase_date": date(2026, 11, 3), "store": "Coop", "total_rappen": 2450}
    add_receipt(database, household_id, **same)
    add_receipt(database, household_id, **same)
    add_receipt(database, household_id, **{**same, "total_rappen": 2451})
    _, body = list_receipts(household_id)
    # Latest upload first.
    assert [r["possible_duplicate"] for r in body["receipts"]] == [False, True, True]


def test_list_shows_only_the_households_receipts(database: FakeDatabase, household_id: str) -> None:
    _, other = api_request(households, "POST", "/households", body={"name": "Andere WG"})
    add_receipt(database, other["id"])
    assert list_receipts(household_id) == (200, {"receipts": []})


def test_detail_has_items_and_image_url(database: FakeDatabase, household_id: str) -> None:
    item = ReceiptItem(
        position=1,
        name="Milch",
        quantity=1,
        unit_price_rappen=165,
        amount_rappen=165,
        category="Sonstiges",
    )
    receipt_id = add_receipt(database, household_id, items=[item])
    status, body = api_request(handler, "GET", f"/households/{household_id}/receipts/{receipt_id}")
    assert status == 200
    assert body["items"] == [item.model_dump()]
    url = urlparse(body["image_url"])
    assert url.path.endswith(f"households/{household_id}/receipts/{receipt_id}")
    assert "X-Amz-Signature" in parse_qs(url.query)


@pytest.mark.parametrize("receipt_id", [RECEIPT_ID, "not-a-uuid"])
def test_detail_of_unknown_receipt_is_404(household_id: str, receipt_id: str) -> None:
    status, _ = api_request(handler, "GET", f"/households/{household_id}/receipts/{receipt_id}")
    assert status == 404


def test_detail_of_another_households_receipt_is_404(
    database: FakeDatabase, household_id: str
) -> None:
    # A member of both households can't read one household's receipt through the other.
    _, other = api_request(households, "POST", "/households", body={"name": "Andere WG"})
    receipt_id = add_receipt(database, other["id"])
    status, _ = api_request(handler, "GET", f"/households/{household_id}/receipts/{receipt_id}")
    assert status == 404


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

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


MILK: dict[str, Any] = {
    "position": 1,
    "name": "Milch",
    "quantity": 1.0,
    "unit_price_rappen": 165,
    "amount_rappen": 165,
    "category": "Sonstiges",
}


def correct(household_id: str, receipt_id: str, user: str = "user-1", **body: Any) -> Any:
    return api_request(
        handler,
        "PATCH",
        f"/households/{household_id}/receipts/{receipt_id}",
        user=user,
        body=body,
    )


def test_any_member_corrects_header_and_items(database: FakeDatabase, household_id: str) -> None:
    database.sync_user("user-2", "User 2", None)
    database.add_member(UUID(household_id), "user-2")
    database.categories.add("Milchprodukte")
    receipt_id = add_receipt(database, household_id, store="MIGROS", total_rappen=None)
    cumulus = {**MILK, "position": 2, "name": "Cumulus-Bon", "amount_rappen": -1000}

    status, body = correct(
        household_id,
        receipt_id,
        user="user-2",
        store="Migros",
        purchase_date="2026-11-06",
        total_rappen=18570,
        items=[cumulus, {**MILK, "category": "Milchprodukte"}],
    )

    assert status == 200
    assert (body["store"], body["purchase_date"], body["total_rappen"]) == (
        "Migros",
        "2026-11-06",
        18570,
    )
    assert [(i["position"], i["category"]) for i in body["items"]] == [
        (1, "Milchprodukte"),
        (2, "Sonstiges"),
    ]
    assert "X-Amz-Signature" in body["image_url"]


def test_fields_left_out_stay_and_null_clears(database: FakeDatabase, household_id: str) -> None:
    item = ReceiptItem(**MILK)
    receipt_id = add_receipt(database, household_id, purchase_date=date(2026, 11, 6), items=[item])

    status, body = correct(household_id, receipt_id, purchase_date=None)

    assert status == 200
    assert (body["store"], body["purchase_date"], body["total_rappen"]) == ("Migros", None, 1000)
    assert body["items"] == [item.model_dump()]


def test_empty_item_list_removes_all_items(database: FakeDatabase, household_id: str) -> None:
    receipt_id = add_receipt(database, household_id, items=[ReceiptItem(**MILK)])
    status, body = correct(household_id, receipt_id, items=[])
    assert (status, body["items"]) == (200, [])


@pytest.mark.parametrize("receipt_status", ["uploaded", "failed", "duplicate"])
def test_only_done_receipts_can_be_corrected(
    database: FakeDatabase, household_id: str, receipt_status: str
) -> None:
    receipt_id = add_receipt(database, household_id, status=receipt_status)
    status, _ = correct(household_id, receipt_id, store="Coop")
    assert status == 409
    assert database.receipts[UUID(receipt_id)].store == "Migros"


def test_unknown_category_is_rejected_and_nothing_changes(
    database: FakeDatabase, household_id: str
) -> None:
    receipt_id = add_receipt(database, household_id)
    status, body = correct(
        household_id, receipt_id, store="Coop", items=[{**MILK, "category": "Erfunden"}]
    )
    assert status == 422
    assert "Erfunden" in body["message"]
    assert database.receipts[UUID(receipt_id)].store == "Migros"


@pytest.mark.parametrize(
    "body",
    [
        {"store": "   "},
        {"total_rappen": 100_000_001},
        {"purchase_date": "06.11.2026"},
        {"items": [{**MILK, "name": ""}]},
        {"items": [{**MILK, "quantity": 0}]},
        {"items": [{**MILK, "position": 0}]},
        {"items": [{**MILK, "category": ""}]},
        {"items": [MILK, MILK]},
    ],
)
def test_rejects_invalid_correction(database: FakeDatabase, household_id: str, body: dict) -> None:
    receipt_id = add_receipt(database, household_id)
    status, _ = correct(household_id, receipt_id, **body)
    assert status == 422


@pytest.mark.parametrize("receipt_id", [RECEIPT_ID, "not-a-uuid"])
def test_correcting_unknown_receipt_is_404(household_id: str, receipt_id: str) -> None:
    status, _ = correct(household_id, receipt_id, store="Coop")
    assert status == 404


def test_correcting_another_households_receipt_is_404(
    database: FakeDatabase, household_id: str
) -> None:
    _, other = api_request(households, "POST", "/households", body={"name": "Andere WG"})
    receipt_id = add_receipt(database, other["id"])
    status, _ = correct(household_id, receipt_id, store="Coop")
    assert status == 404
    assert database.receipts[UUID(receipt_id)].store == "Migros"


def test_non_member_cannot_correct(database: FakeDatabase, household_id: str) -> None:
    receipt_id = add_receipt(database, household_id)
    status, _ = correct(household_id, receipt_id, user="stranger", store="Coop")
    assert status == 404
    assert database.receipts[UUID(receipt_id)].store == "Migros"


def test_categories_are_listed_by_name(database: FakeDatabase) -> None:
    database.categories |= {"Milchprodukte", "Getränke"}
    status, body = api_request(handler, "GET", "/categories")
    assert (status, body) == (200, {"categories": ["Getränke", "Milchprodukte", "Sonstiges"]})

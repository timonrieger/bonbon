import pytest
from bonbon.handlers.households import handler as households
from bonbon.handlers.receipts import handler
from conftest import api_request

RECEIPT_ID = "00000000-0000-0000-0000-000000000001"


@pytest.fixture
def household_id() -> str:
    _, created = api_request(households, "POST", "/households", body={"name": "WG Zürich"})
    return created["id"]


# The routes only fix the contract so far; members get 501 until the SQL is in place.
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

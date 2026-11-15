from datetime import date
from typing import Any
from uuid import UUID

import pytest
from bonbon.handlers.households import handler as households
from bonbon.handlers.reports import handler
from bonbon.receipts.models import ReceiptItem
from bonbon.reports.models import MonthTotal
from conftest import api_request
from fakes import FakeDatabase
from pydantic import ValidationError


@pytest.fixture
def household_id() -> str:
    _, created = api_request(households, "POST", "/households", body={"name": "WG Zürich"})
    return created["id"]


def add_receipt(database: FakeDatabase, household_id: str, day: date, total: int, **fields: Any):
    fields = {"status": "done", "store": "Migros", **fields}
    database.add_receipt(
        UUID(household_id), "user-1", purchase_date=day, total_rappen=total, **fields
    )


def item(category: str, amount: int) -> ReceiptItem:
    return ReceiptItem(
        position=1,
        name="Artikel",
        quantity=1,
        unit_price_rappen=amount,
        amount_rappen=amount,
        category=category,
    )


def monthly(household_id: str, month: str) -> dict:
    status, body = api_request(
        handler, "GET", f"/households/{household_id}/reports/monthly", query={"month": month}
    )
    assert status == 200
    return body


def test_monthly_report_of_an_empty_month(household_id: str) -> None:
    assert monthly(household_id, "2026-11") == {
        "month": "2026-11",
        "total_rappen": 0,
        "receipt_count": 0,
        "previous_month_total_rappen": 0,
        "by_category": [],
        "by_store": [],
    }


def test_monthly_report_sums_done_receipts(database: FakeDatabase, household_id: str) -> None:
    add_receipt(database, household_id, date(2026, 10, 15), 700)
    add_receipt(
        database, household_id, date(2026, 11, 2), 1000, items=[item("Milchprodukte", 1000)]
    )
    add_receipt(
        database,
        household_id,
        date(2026, 11, 20),
        3000,
        store="Coop",
        items=[item("Getränke", 1000), item("Milchprodukte", 2000)],
    )
    # Neither counts.
    add_receipt(database, household_id, date(2026, 11, 3), 9999, status="duplicate")
    add_receipt(database, household_id, date(2026, 11, 3), 9999, status="failed")

    report = monthly(household_id, "2026-11")
    assert report["total_rappen"] == 4000
    assert report["receipt_count"] == 2
    assert report["previous_month_total_rappen"] == 700
    assert report["by_category"] == [
        {"category": "Milchprodukte", "total_rappen": 3000},
        {"category": "Getränke", "total_rappen": 1000},
    ]
    assert report["by_store"] == [
        {"store": "Coop", "total_rappen": 3000},
        {"store": "Migros", "total_rappen": 1000},
    ]


def test_trend_ends_with_the_current_month(database: FakeDatabase, household_id: str) -> None:
    add_receipt(database, household_id, date.today(), 1250)
    status, body = api_request(
        handler, "GET", f"/households/{household_id}/reports/trend", query={"months": "3"}
    )
    assert status == 200
    assert [m["total_rappen"] for m in body["months"]] == [0, 0, 1250]
    assert body["months"][-1]["month"] == date.today().strftime("%Y-%m")
    assert body["months"][0]["month"] < body["months"][1]["month"]


def test_trend_has_six_months_by_default(household_id: str) -> None:
    _, body = api_request(handler, "GET", f"/households/{household_id}/reports/trend")
    assert len(body["months"]) == 6


@pytest.mark.parametrize(
    ("path", "query"),
    [("/reports/monthly", {"month": "2026-11"}), ("/reports/trend", None)],
)
def test_non_member_gets_404(household_id: str, path: str, query: dict | None) -> None:
    status, _ = api_request(
        handler, "GET", f"/households/{household_id}{path}", user="stranger", query=query
    )
    assert status == 404


@pytest.mark.parametrize("query", [None, {"month": "2026-13"}, {"month": "November"}])
def test_monthly_report_needs_a_valid_month(household_id: str, query: dict | None) -> None:
    status, _ = api_request(
        handler, "GET", f"/households/{household_id}/reports/monthly", query=query
    )
    assert status == 422


@pytest.mark.parametrize("months", ["0", "25", "abc"])
def test_trend_rejects_months_out_of_range(household_id: str, months: str) -> None:
    status, _ = api_request(
        handler, "GET", f"/households/{household_id}/reports/trend", query={"months": months}
    )
    assert status == 422


@pytest.mark.parametrize("month", ["2026-13", "2026-1", "11-2026"])
def test_report_models_reject_malformed_month(month: str) -> None:
    with pytest.raises(ValidationError):
        MonthTotal(month=month, total_rappen=0)


def test_report_models_accept_month() -> None:
    assert MonthTotal(month="2026-11", total_rappen=0).month == "2026-11"

import pytest
from bonbon.handlers.households import handler as households
from bonbon.handlers.reports import handler
from bonbon.reports.models import MonthTotal
from conftest import api_request
from pydantic import ValidationError


@pytest.fixture
def household_id() -> str:
    _, created = api_request(households, "POST", "/households", body={"name": "WG Zürich"})
    return created["id"]


# The routes only fix the contract so far; members get 501 until the SQL is in place.
@pytest.mark.parametrize(
    ("path", "query"),
    [
        ("/reports/monthly", {"month": "2026-11"}),
        ("/reports/trend", None),
        ("/reports/trend", {"months": "12"}),
    ],
)
def test_member_gets_not_implemented(household_id: str, path: str, query: dict | None) -> None:
    status, _ = api_request(handler, "GET", f"/households/{household_id}{path}", query=query)
    assert status == 501


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

"""Spending reports for the dashboard (docs/features/03-dashboard.md)."""

from typing import Annotated

from aws_lambda_powertools.event_handler.api_gateway import Router
from aws_lambda_powertools.event_handler.openapi.params import Query

from bonbon.auth import MEMBERSHIP_RESPONSES, current_user_id, require_membership
from bonbon.receipts.models import MONTH_PATTERN
from bonbon.reports import repo
from bonbon.reports.models import MonthlyReport, SpendingTrend

router = Router()


@router.get(
    "/households/<household_id>/reports/monthly",
    operation_id="getMonthlyReport",
    tags=["reports"],
    responses=MEMBERSHIP_RESPONSES,
)
def get_monthly_report(
    household_id: str,
    month: Annotated[str, Query(pattern=MONTH_PATTERN)],
) -> MonthlyReport:
    """Spending in one month (YYYY-MM): total, per category, per store and the previous month."""
    require_membership(household_id, current_user_id(router))
    return repo.monthly(household_id, month)


@router.get(
    "/households/<household_id>/reports/trend",
    operation_id="getSpendingTrend",
    tags=["reports"],
    responses=MEMBERSHIP_RESPONSES,
)
def get_spending_trend(
    household_id: str,
    months: Annotated[int, Query(ge=1, le=24)] = 6,
) -> SpendingTrend:
    """Total spending per month over the last `months` months, including the current one."""
    require_membership(household_id, current_user_id(router))
    return repo.trend(household_id, months)

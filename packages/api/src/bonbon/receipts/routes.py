"""Receipt endpoints for the receipt list and detail view (docs/features/03-dashboard.md).

The contract is fixed so the frontend can generate its types; the SQL comes in a later PR.
Until then the routes check membership and answer 501.
"""

from typing import Annotated

from aws_lambda_powertools.event_handler.api_gateway import Router
from aws_lambda_powertools.event_handler.exceptions import ServiceError
from aws_lambda_powertools.event_handler.openapi.params import Query

from bonbon.auth import MEMBERSHIP_RESPONSES, current_user_id, require_membership
from bonbon.receipts.models import MONTH_PATTERN, ReceiptDetail, ReceiptList

router = Router()


@router.get(
    "/households/<household_id>/receipts",
    operation_id="listReceipts",
    tags=["receipts"],
    responses=MEMBERSHIP_RESPONSES,
)
def list_receipts(
    household_id: str,
    month: Annotated[str | None, Query(pattern=MONTH_PATTERN)] = None,
) -> ReceiptList:
    """All receipts of the household. With `month` (YYYY-MM) only that month.

    Newest first by purchase date; a receipt without one is sorted by its upload date, the same
    date the month filter and the reports use. Receipts on the same day: latest upload first.
    """
    require_membership(household_id, current_user_id(router))
    raise ServiceError(501, "Not implemented yet")


@router.get(
    "/households/<household_id>/receipts/<receipt_id>",
    operation_id="getReceipt",
    tags=["receipts"],
    responses=MEMBERSHIP_RESPONSES,
)
def get_receipt(household_id: str, receipt_id: str) -> ReceiptDetail:
    require_membership(household_id, current_user_id(router))
    raise ServiceError(501, "Not implemented yet")

"""Receipt endpoints: upload (docs/features/01-upload-processing.md), the receipt list and
detail view (docs/features/03-dashboard.md) and corrections with the category list
(docs/features/02-extraction-categorization.md).
"""

from typing import Annotated

from aws_lambda_powertools.event_handler.api_gateway import Router
from aws_lambda_powertools.event_handler.openapi.params import Query

from bonbon.auth import MEMBERSHIP_RESPONSES, current_user_id, require_membership
from bonbon.receipts import repo, storage
from bonbon.receipts.models import (
    MONTH_PATTERN,
    CategoryList,
    CreateReceiptRequest,
    ReceiptCorrection,
    ReceiptDetail,
    ReceiptList,
    ReceiptUpload,
)

router = Router()

UPLOAD_URL_EXPIRES_IN = 300
# Long enough to look at the photo; the detail view fetches a fresh URL when it is opened again.
IMAGE_URL_EXPIRES_IN = 300


@router.post(
    "/households/<household_id>/receipts",
    operation_id="createReceipt",
    tags=["receipts"],
    status_code=201,
    responses={201: {"description": "Receipt created"}, 404: MEMBERSHIP_RESPONSES[404]},
)
def create_receipt(household_id: str, body: CreateReceiptRequest) -> ReceiptUpload:
    """Create a receipt and return a presigned URL to upload its file to.

    The browser PUTs the file to `upload_url` with `upload_headers`, then polls
    `getReceipt` for the status.
    """
    user_id = current_user_id(router)
    require_membership(household_id, user_id)
    receipt_id = repo.create(household_id, uploaded_by=user_id)
    url, headers = storage.presigned_upload(
        storage.receipt_key(household_id, receipt_id),
        content_type=body.content_type,
        size_bytes=body.size_bytes,
        expires_in=UPLOAD_URL_EXPIRES_IN,
    )
    return ReceiptUpload(
        receipt_id=receipt_id,
        upload_url=url,
        upload_headers=headers,
        expires_in=UPLOAD_URL_EXPIRES_IN,
    )


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
    Uploads whose file never arrived are left out.
    """
    require_membership(household_id, current_user_id(router))
    return ReceiptList(receipts=repo.list_for_household(household_id, month))


@router.get(
    "/households/<household_id>/receipts/<receipt_id>",
    operation_id="getReceipt",
    tags=["receipts"],
    responses=MEMBERSHIP_RESPONSES,
)
def get_receipt(household_id: str, receipt_id: str) -> ReceiptDetail:
    """The receipt with its items and a presigned `image_url` for the original file."""
    require_membership(household_id, current_user_id(router))
    return _detail(household_id, receipt_id)


@router.patch(
    "/households/<household_id>/receipts/<receipt_id>",
    operation_id="updateReceipt",
    tags=["receipts"],
    responses={
        **MEMBERSHIP_RESPONSES,
        409: {
            "description": "The receipt is not processed yet, or failed or is a duplicate",
            "content": MEMBERSHIP_RESPONSES[404].get("content", {}),
        },
    },
)
def update_receipt(household_id: str, receipt_id: str, body: ReceiptCorrection) -> ReceiptDetail:
    """Correct store, date, total or items of a processed receipt; any member may.

    Fields left out stay as they are, `null` clears them. `items` replaces all items.
    Returns the corrected receipt, like `getReceipt`; the reports reflect it immediately.
    A category that isn't in `listCategories` is rejected with 422 (`statusCode`, `message`).
    """
    require_membership(household_id, current_user_id(router))
    repo.correct(household_id, receipt_id, body)
    return _detail(household_id, receipt_id)


@router.get("/categories", operation_id="listCategories", tags=["receipts"])
def list_categories() -> CategoryList:
    """All item categories, sorted by name; the same for every household."""
    # No household data, so no membership check; API Gateway still requires a signed-in user.
    return CategoryList(categories=repo.category_names())


def _detail(household_id: str, receipt_id: str) -> ReceiptDetail:
    summary, items = repo.get(household_id, receipt_id)
    image_url = storage.presigned_download(
        storage.receipt_key(household_id, summary.id), expires_in=IMAGE_URL_EXPIRES_IN
    )
    return ReceiptDetail(**summary.model_dump(), image_url=image_url, items=items)

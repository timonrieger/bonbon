from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

ReceiptStatus = Literal["uploaded", "processing", "done", "failed", "duplicate"]

# A calendar month as YYYY-MM, used by the receipt list and the reports.
MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"


class ReceiptSummary(BaseModel):
    id: str
    status: ReceiptStatus
    # Missing until the worker has processed the receipt, or if Textract didn't recognize it.
    store: str | None
    # A receipt without a recognized date counts towards the month it was uploaded in.
    purchase_date: date | None
    total_rappen: int | None
    # None once the uploader has deleted their account.
    uploaded_by_name: str | None
    created_at: datetime


class ReceiptList(BaseModel):
    # Wrapped in an object so pagination can be added later without breaking clients.
    receipts: list[ReceiptSummary]


class ReceiptItem(BaseModel):
    position: int
    name: str
    # Weighed goods have fractional quantities (0.452 kg).
    quantity: float
    unit_price_rappen: int | None
    amount_rappen: int
    category: str


class ReceiptDetail(ReceiptSummary):
    # Presigned GET URL for the original photo or PDF, valid for a few minutes.
    image_url: str
    items: list[ReceiptItem]

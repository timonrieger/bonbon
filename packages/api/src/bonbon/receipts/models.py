from datetime import date, datetime, timedelta
from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, StringConstraints, model_validator

# 'uploaded' lasts until the worker is done; the app shows it as "in Bearbeitung".
ReceiptStatus = Literal["uploaded", "done", "failed", "duplicate"]

# A calendar month as YYYY-MM, used by the receipt list and the reports.
MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"
Month = Annotated[str, Field(pattern=MONTH_PATTERN, examples=["2026-11"])]


def month_bounds(month: str) -> tuple[date, date]:
    """First day of the month and of the next month, for `day >= start AND day < end`."""
    start = date.fromisoformat(f"{month}-01")
    end = (start + timedelta(days=31)).replace(day=1)
    return start, end


# The frontend shrinks photos to ~300-500 KB; PDFs are passed through as they are.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
UploadContentType = Literal["image/jpeg", "image/png", "application/pdf"]


class CreateReceiptRequest(BaseModel):
    content_type: UploadContentType
    # Signed into the upload URL: S3 rejects a file of any other size.
    size_bytes: int = Field(gt=0, le=MAX_UPLOAD_BYTES)


class ReceiptUpload(BaseModel):
    receipt_id: str
    # Presigned S3 URL for one PUT of the file, with exactly the headers in upload_headers.
    upload_url: str
    # Send all of these with the PUT, unchanged; the signature covers them.
    upload_headers: dict[str, str]
    expires_in: int


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
    # Another done receipt in the household has the same store, date and total. Both still
    # count; the UI points it out and the member decides (docs/features/03-dashboard.md#rules).
    possible_duplicate: bool


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


# Bounds for amounts in corrections: well inside the database's integer, far beyond any receipt.
# Negative amounts are allowed: discounts and vouchers are printed as deductions.
Rappen = Annotated[int, Field(ge=-100_000_000, le=100_000_000)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class ItemCorrection(BaseModel):
    position: int = Field(ge=1)
    name: Text
    # numeric(10, 3) in the database, so at most three decimals are kept.
    quantity: float = Field(gt=0, lt=10_000_000)
    unit_price_rappen: Rappen | None = None
    amount_rappen: Rappen
    # A name from listCategories.
    category: Text


class ReceiptCorrection(BaseModel):
    """Fields a member corrects (docs/features/02). Left out = unchanged, null = cleared.

    `items` replaces all items of the receipt; left out or null keeps them. The total is not
    computed from the items: vouchers are often no line items, so the two can differ.
    """

    store: Text | None = None
    purchase_date: date | None = None
    total_rappen: Rappen | None = None
    items: list[ItemCorrection] | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def positions_are_unique(self) -> Self:
        positions = [item.position for item in self.items or []]
        if len(positions) != len(set(positions)):
            raise ValueError("Item positions must be unique")
        return self


class CategoryList(BaseModel):
    # Names, sorted; the same for every household.
    categories: list[str]

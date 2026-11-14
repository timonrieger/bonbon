from pydantic import BaseModel

from bonbon.receipts.models import Month

# Totals count receipts with status 'done' only, so duplicates and failed receipts are left out.
# A receipt without a recognized purchase date counts towards the month it was uploaded in.


class CategoryTotal(BaseModel):
    category: str
    total_rappen: int


class StoreTotal(BaseModel):
    # None for receipts whose store Textract didn't recognize.
    store: str | None
    total_rappen: int


class MonthlyReport(BaseModel):
    month: Month
    total_rappen: int
    receipt_count: int
    previous_month_total_rappen: int
    # Largest total first.
    by_category: list[CategoryTotal]
    by_store: list[StoreTotal]


class MonthTotal(BaseModel):
    month: Month
    total_rappen: int


class SpendingTrend(BaseModel):
    # Oldest month first, ending with the current month; months without spending have 0.
    months: list[MonthTotal]

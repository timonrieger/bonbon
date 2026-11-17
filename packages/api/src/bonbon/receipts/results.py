"""Messages on the results queue, from the Textract Lambda to the database Lambda (ADR 0007).

One message per receipt. The Textract Lambda builds one of these models and sends
`model_dump_json()`; the database Lambda reads it back with `parse_result_message()`, which
rejects anything else (the message is retried and lands in the results DLQ).
"""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, TypeAdapter


class ExtractedResult(BaseModel):
    """Textract read the file; the raw AnalyzeExpense JSON is in S3."""

    outcome: Literal["extracted"] = "extracted"
    household_id: UUID
    receipt_id: UUID
    # textract-results/<household_id>/<receipt_id>.json in the receipts bucket.
    result_key: str = Field(pattern=r"^textract-results/")
    # SHA-256 of the original file, lowercase hex. Same hash in the household → 'duplicate'.
    file_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class FailedResult(BaseModel):
    """Textract failed for good (last attempt or permanent error): the receipt becomes 'failed'."""

    outcome: Literal["failed"] = "failed"
    household_id: UUID
    receipt_id: UUID
    # Only logged, not stored.
    error: str


ResultMessage = Annotated[ExtractedResult | FailedResult, Field(discriminator="outcome")]
_adapter: TypeAdapter[ExtractedResult | FailedResult] = TypeAdapter(ResultMessage)


def parse_result_message(body: str) -> ExtractedResult | FailedResult:
    return _adapter.validate_json(body)

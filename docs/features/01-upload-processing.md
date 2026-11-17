# 01 Upload & asynchronous processing

**Owners:** @timonrieger (S3, bucket policies), @Dam-Mil (SQS, worker), @RR02-rr (upload UI) · **Milestone:** M2, end of SW7 (critical)

The core of the architecture: the upload ends in S3, everything after runs asynchronously through S3 → SQS → Lambda.

## Done when

- [x] Upload a photo (JPG/PNG) from the household page
- [ ] Upload a single-page PDF (optional; the API accepts `application/pdf`, the UI doesn't yet)
- [ ] Frontend shrinks images to ~300–500 KB before upload
- [x] Upload via presigned URL; file type (JPG, PNG, PDF) and size (max. 5 MB) are limited (`createReceipt`)
- [ ] PDFs with more than one page are rejected (synchronous `AnalyzeExpense` only accepts single-page documents; a multi-page PDF raises and the receipt ends up `failed`)
- [x] Processing runs S3 → SQS → Textract Lambda → results queue → database Lambda ([decisions/0007](../decisions/0007-worker-split-and-db-credentials.md)); tested end to end on a dev stack (#41, #38, #27)
- [ ] Status visible in the app: in Bearbeitung (`uploaded`) / fertig / fehlgeschlagen / Duplikat
- [ ] Notification on completion, in-app (required) or e-mail via SNS (optional)
- [x] Failed receipts land in the dead-letter queue after 3 attempts (both queues, partial batch failures)
- [x] Worker is idempotent (one transaction from `uploaded` to the final status; a duplicate delivery changes nothing)
- [x] A receipt that fails for good is set to `failed`, not only dead-lettered
- [x] Same file uploaded twice in a household is detected via file hash → `duplicate`
- [x] Worker reserved concurrency 10; visibility timeout ≥ 6 × Lambda timeout

## Implementation status

### Frontend (`packages/web`) — @RR02-rr

**Implemented** (#16):

- `src/components/ReceiptFilePicker.tsx`: file picker with client-side validation
  - Accepts JPG/PNG only (MIME-type check), rejects all other formats
  - Rejects files larger than 5 MB with a human-readable size in the error message
  - Shows selected filename and size; allows replacing or removing the file
  - Controlled: the parent passes `file` and gets `onChange(file | null)`, so it owns the selection
- `src/api/receipts.ts`: `uploadToS3(receiptUpload, file)`, a plain `fetch` PUT
  without the auth header (S3 rejects it) that forwards every header from `upload_headers`
- `src/pages/HouseholdPage.tsx`: integrates `ReceiptFilePicker` and uploads in one `useMutation`:
  `createReceipt` (generated, from `@/api`), then `uploadToS3`; shows success and error
  messages and clears the selection after a successful upload

**Next:**

- Status polling with `refetchInterval` on `getReceipt`

**Still planned:**
- Status badge: `uploaded` (shown as «in Bearbeitung») / `done` / `failed` / `duplicate` (`listReceipts` and `getReceipt` return `status`)
- Client-side image compression to ~300–500 KB (planned: `browser-image-compression`)
- PDF support (single-page only; rejected with a clear error message)

### Backend / infrastructure — @timonrieger, @Dam-Mil

**Implemented**:
- S3 bucket with lifecycle rules, CORS, and object-created → SQS notification (`template.yaml`)
- Receipts queue + DLQ → `handlers/process_receipt.py`: calls Textract `AnalyzeExpense`, stores the raw JSON under `textract-results/`, sends an `ExtractedResult`/`FailedResult` on the results queue (#41)
- Results queue + DLQ → `handlers/process_result.py` in the VPC (#17, #22): reads the Textract result from S3, writes receipt and items in one transaction (`done`, `duplicate` via file hash, or `failed`), removes the `status=pending` tag. Message format in `bonbon/receipts/results.py`
- `POST /households/{id}/receipts`: inserts the receipt row and returns a presigned PUT URL (see Notes)
- `GET /households/{id}/receipts` and `GET /households/{id}/receipts/{id}` read from PostgreSQL (#18)
- S3 gateway endpoint so the database Lambda reaches S3 without NAT, created only if the default VPC has none (#27)

**Planned**:
- Textract mock mode for the load test

## Notes

- The receipt id is created when the presigned URL is issued and is part of the S3 key. `POST /households/{household_id}/receipts` returns `receipt_id`, `upload_url`, `upload_headers` and `expires_in` (300 s). The browser sends a `PUT` to `upload_url` with every header from `upload_headers` and the file as body. Type, size and tag are signed into the URL, so S3 rejects anything else.
- Every upload is tagged `status=pending` via `upload_headers`. The database worker removes the tag once the receipt has a final status (`done`, `duplicate` or `failed`), otherwise the lifecycle rule deletes the file after 7 days. A failed or duplicate receipt keeps its file too, so the app can still show it.
- S3 lifecycle: Glacier Instant Retrieval after 30 days, delete never-processed uploads (tag `status=pending`) after 7 days, delete raw Textract results (`textract-results/`) after 30 days, abort incomplete multipart uploads after 1 day.
- The worker sets `duplicate` only for the same file hash in the household. A failed receipt doesn't count: uploading the same file again processes it normally. Same store, date and total is not a duplicate; the receipt stays `done` (see [03](03-dashboard.md#rules)).
- A Textract mock mode (realistic delay and rate limit) is needed for the load test.

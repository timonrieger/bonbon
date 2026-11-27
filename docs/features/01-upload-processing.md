# 01 Upload & asynchronous processing

**Owners:** @timonrieger (S3, bucket policies), @Dam-Mil (SQS, worker), @RR02-rr (upload UI) · **Milestone:** M2, end of SW7 (critical)

The core of the architecture: the upload ends in S3, everything after runs asynchronously through S3 → SQS → Lambda.

## Done when

- [x] Upload a photo (JPG/PNG) from the household page
- [ ] Upload a single-page PDF (optional; the API accepts `application/pdf`, the UI doesn't yet)
- [x] Frontend compresses receipt images before upload (#32). Roughly 300–500 KB is a best-effort target, and 5 MB is the strict upload limit.
- [x] Upload via presigned URL; file type (JPG, PNG, PDF) and size (max. 5 MB) are limited (`createReceipt`)
- [ ] PDFs with more than one page are rejected (synchronous `AnalyzeExpense` only accepts single-page documents; a multi-page PDF raises and the receipt ends up `failed`)
- [x] Processing runs S3 → SQS → Textract Lambda → results queue → database Lambda ([decisions/0007](../decisions/0007-worker-split-and-db-credentials.md)); tested end to end on a dev stack (#41, #38, #27)
- [x] Status visible in the app: «In Bearbeitung» (`uploaded`) / «Verarbeitet» (`done`) / «Fehlgeschlagen» (`failed`) / «Duplikat» (`duplicate`)
- [x] The receipt list and detail view update processing status automatically
- [x] In-app notification when a newly uploaded receipt finishes processing or fails (#31)
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
  - Rejects empty files and files larger than 5 MB with a human-readable error message
  - Shows selected filename and size; allows replacing or removing the file
  - Controlled: the parent passes `file` and gets `onChange(file | null)`, so it owns the selection
- `src/api/receipts.ts` exports `uploadToS3(upload: ReceiptUpload, file: File, signal: AbortSignal): Promise<void>`. It sends the prepared file to `upload.upload_url` with a plain `fetch` PUT, forwards `upload.upload_headers` verbatim, and passes the abort signal. The URL supplies authorization. A non-2xx response rejects the upload.
- `HouseholdPage.tsx` composes `ReceiptUploadSection` and `HouseholdReceiptList` and coordinates uploads with leaving the household. `useReceiptUpload` owns image preparation and the authenticated `createReceipt` request followed by the direct S3 PUT. `ReceiptUploadSection` renders the picker, progress and per-receipt completion notices.
- `src/features/receipts/receiptImage.ts`: validates the original type and size, checks its signature and decodes the image with EXIF orientation. Images up to 500 KiB keep their original bytes. Larger images are candidates for JPEG conversion over a white background. Resizing retains the aspect ratio without upscaling and aims for a 2800 px long edge. The preferred short edge adapts to the original width of narrow receipts so they can still be downscaled without losing too much text detail. There are at most three JPEG encodes, including at most one further resize. The best-effort target allows larger outputs when readability needs more pixels. If re-encoding saves less than 10%, the validated original is used. The picker rejects source files over 5 MB before decoding, and the prepared image must also meet the strict 5 MB upload limit.
- The upload signs the prepared file's actual size and type. Decode or encode failures show an error before the API creates a receipt. Changing households during preparation or signing out prevents a new upload from starting. The UI shows preparation progress and reports the size reduction after upload. Leaving a household in the same session is blocked until an active upload settles. Cancelling the browser request cannot undo an upload accepted by S3.
- The authenticated API transport attaches the session's abort signal when requesting the presigned URL. The upload also uses explicit cancellation for local image preparation and the direct S3 PUT.

- The household receipt list refreshes after a successful upload. The list and detail views share German status badges for `uploaded`, `done`, `failed` and `duplicate`.

- The open receipt list polls every 3 seconds while any receipt is awaiting processing. The open detail view polls on the same interval while its receipt is `uploaded`. Polling pauses in hidden tabs and stops when the receipt reaches a final status or the API denies access. Transient errors keep the last successful response visible and slow polling to every 15 seconds.
- The backend omits still-`uploaded` records from the list after 30 minutes. The list allows a 15-second grace period for that final refresh. Direct detail links can still return these records, so detail polling stops based on `created_at` at 30 minutes. If the list refresh immediately after upload fails, the page attempts recovery for up to one minute.
- While the household page remains open, it tracks each successful upload by receipt ID independently of the list's month filter. It polls the receipt until it reaches `done`, `failed`, or `duplicate`, or until tracking times out after 30 minutes. Each final status produces one in-app notice with a link to the receipt. Tracking resets when leaving the page or reloading.

**Browser memory:** The 5 MB file limit bounds compressed bytes. Decoding can allocate a much larger bitmap before resizing. Test long and high-resolution receipts on memory-constrained mobile devices.

**Still planned:**

- PDF support (single-page only; rejected with a clear error message)

### Backend / infrastructure — @timonrieger, @Dam-Mil

**Implemented**:

- S3 bucket with lifecycle rules, CORS, and object-created → SQS notification (`template.yaml`)
- Receipts queue + DLQ → `handlers/process_receipt.py`: calls Textract `AnalyzeExpense`, stores the raw JSON under `textract-results/`, sends an `ExtractedResult`/`FailedResult` on the results queue (#41)
- Results queue + DLQ → `handlers/process_result.py` in the VPC (#17, #22): reads the Textract result from S3, writes receipt and items in one transaction (`done`, `duplicate` via file hash, or `failed`), removes the `status=pending` tag. Message format in `bonbon/receipts/results.py`
- `POST /households/{id}/receipts`: inserts the receipt row and returns a presigned PUT URL (see Notes)
- `GET /households/{id}/receipts` and `GET /households/{id}/receipts/{id}` read from PostgreSQL (#18)
- S3 gateway endpoint so the database Lambda reaches S3 without NAT, created only if the default VPC has none (#27)

**Local load test**:

- Run `mise run load-test` to simulate 200 receipts through both worker record handlers. The
  Textract response reuses `packages/api/tests/data/textract_migros.json`; its delay defaults to
  3.3 seconds and can be changed with `BONBON_TEXTRACT_DELAY_SECONDS=1 mise run load-test`.
- The test uses in-memory S3/SQS substitutes and `FakeDatabase`; it does not create AWS clients
  or call AWS. It reports throughput, total duration, p95 completion time (including local
  executor waiting), and failure rate. The mock tracks concurrent calls, capped at 10.
- This proves the local worker-code path and its behavior under a bounded thread pool. It does
  **not** prove the AWS targets of accepting 200 uploads/minute, processing them within 3 minutes,
  or achieving API p95 below 1 second. It also cannot prove deployed S3/SQS/Lambda behavior,
  CloudWatch metrics, deployed concurrency, Textract's actual throttling behavior, or OCR accuracy.

**AWS E2E load test**:

- Issue #35 adds a separate runner for API-to-S3 upload and receipt-status polling. It is not the
  local worker test above; its task, profiles, measurements and closed live-safety gate are
  documented in [the E2E load-test guide](../guides/e2e-load-test.md).
- No AWS performance result has been established. The synthetic PNGs are for exercising the
  processing path, not for measuring OCR quality.

## Verification

- On 2026-11-20, a manual test on the live `bonbon-dev` stack verified receipt upload to S3, automatic refresh of the household receipt list, asynchronous Textract processing, and automatic status polling.
- The later completion notices (#31) were checked locally in Chromium with mocked responses for success, failure and duplicates, including month changes while processing.
- The [image compression browser fixture](../../packages/web/tests/receipt-image.html) checks wide, tall, narrow and small JPG/PNG files and displays text crops at native output size. To run it locally, start `mise run //packages/web:dev` and open `/tests/receipt-image.html`. The combined path of compressing a large image and processing it with live Textract has yet to be tested separately.

## Notes

- The receipt id is created when the presigned URL is issued and is part of the S3 key. `POST /households/{household_id}/receipts` returns `receipt_id`, `upload_url`, `upload_headers` and `expires_in` (300 s). The browser sends a `PUT` to `upload_url` with every header from `upload_headers` and the file as body. Type, size and tag are signed into the URL, so S3 rejects anything else.
- Every upload is tagged `status=pending` via `upload_headers`. The database worker removes the tag once the receipt has a final status (`done`, `duplicate` or `failed`), otherwise the lifecycle rule deletes the file after 7 days. A failed or duplicate receipt keeps its file too, so the app can still show it.
- S3 lifecycle: Glacier Instant Retrieval after 30 days, delete never-processed uploads (tag `status=pending`) after 7 days, delete raw Textract results (`textract-results/`) after 30 days, abort incomplete multipart uploads after 1 day.
- The worker sets `duplicate` only for the same file hash in the household. A failed receipt doesn't count: uploading the same file again processes it normally. Same store, date and total is not a duplicate; the receipt stays `done` (see [03](03-dashboard.md#rules)).

# 01 Upload & asynchronous processing

**Owners:** @timonrieger (S3, bucket policies), @Dam-Mil (SQS, worker), @RR02-rr (upload UI) · **Milestone:** M2, end of SW7 (critical)

The core of the architecture: the upload ends in S3, everything after runs asynchronously through S3 → SQS → Lambda.

## Done when

- [ ] Upload a photo (JPG/PNG) or a single-page PDF (optional)
- [ ] Frontend shrinks images to ~300–500 KB before upload
- [x] Upload via presigned URL; file type (JPG, PNG, PDF) and size (max. 5 MB) are limited (`createReceipt`)
- [ ] PDFs with more than one page are rejected
- [ ] Processing runs S3 → SQS → worker Lambda
- [ ] Status visible in the app: processing / done / failed / duplicate
- [ ] Notification on completion, in-app (required) or e-mail via SNS (optional)
- [ ] Failed receipts land in the dead-letter queue after 3 attempts
- [ ] Worker is idempotent (conditional status write; a duplicate delivery is dropped)
- [ ] Same file uploaded twice in a household is detected via file hash → `duplicate`
- [x] Worker reserved concurrency 10; visibility timeout ≥ 6 × Lambda timeout

## Notes

- The receipt id is created when the presigned URL is issued and is part of the S3 key. `POST /households/{household_id}/receipts` returns `receipt_id`, `upload_url`, `upload_headers` and `expires_in` (300 s). The browser sends a `PUT` to `upload_url` with every header from `upload_headers` and the file as body. Type, size and tag are signed into the URL, so S3 rejects anything else.
- Every upload is tagged `status=pending` via `upload_headers`. The worker must remove the tag once the receipt is processed, otherwise the lifecycle rule deletes the file after 7 days.
- S3 lifecycle: Glacier Instant Retrieval after 30 days, delete never-processed uploads (tag `status=pending`) after 7 days, abort incomplete multipart uploads after 1 day.
- The worker sets `duplicate` only for the same file hash in the household. Same store, date and total is not a duplicate; the receipt stays `done` (see [03](03-dashboard.md#rules)).
- A Textract mock mode (realistic delay and rate limit) is needed for the load test.

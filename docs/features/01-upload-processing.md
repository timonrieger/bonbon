# 01 Upload & asynchronous processing

**Owners:** P1 (S3, bucket policies), P3 (SQS, worker), P4 (upload UI) · **Milestone:** M2, end of SW7 (critical)

The core of the architecture: the upload ends in S3, everything after runs asynchronously through S3 → SQS → Lambda.

## Done when

- [ ] Upload a photo (JPG/PNG) or a single-page PDF (optional)
- [ ] Frontend shrinks images to ~300–500 KB before upload
- [ ] Upload via presigned URL; file type and size are limited; PDFs with more than one page are rejected
- [ ] Processing runs S3 → SQS → worker Lambda
- [ ] Status visible in the app: processing / done / failed / duplicate
- [ ] Notification on completion, in-app (required) or e-mail via SNS (optional)
- [ ] Failed receipts land in the dead-letter queue after 3 attempts
- [ ] Worker is idempotent (conditional status write; a duplicate delivery is dropped)
- [ ] Same file uploaded twice in a household is detected via file hash → `duplicate`
- [ ] Worker reserved concurrency 10; visibility timeout ≥ 6 × Lambda timeout

## Notes

- The receipt id is created when the presigned URL is issued and is part of the S3 key.
- S3 lifecycle: Glacier Instant Retrieval after 30 days, delete never-processed uploads (tag `status=pending`) after 7 days, abort incomplete multipart uploads after 1 day.
- A Textract mock mode (realistic delay and rate limit) is needed for the load test.

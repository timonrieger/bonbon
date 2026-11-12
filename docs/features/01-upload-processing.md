# 01 Upload & asynchronous processing

**Owners:** @timonrieger (S3, bucket policies), @Dam-Mil (SQS, worker), @RR02-rr (upload UI) · **Milestone:** M2, end of SW7 (critical)

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
- [x] Worker reserved concurrency 10; visibility timeout ≥ 6 × Lambda timeout

## API contract for the presigned URL endpoint

Proposed by @Dam-Mil, 2026-11. Not yet implemented in the backend.

```
POST /households/{household_id}/receipts
operationId: createReceipt

Request body:
{
  "content_type": "image/jpeg" | "image/png",
  "size_bytes": number
}

Response 201:
{
  "receipt_id": string,
  "upload_url": string,   // S3 presigned PUT URL, no Auth header allowed
  "expires_in": 300       // seconds
}

Followed by:
PUT {upload_url}
Headers: Content-Type: <same value as content_type>
Body: raw file bytes
→ 200 from S3 directly
```

After the PUT, poll `GET /households/{household_id}/receipts/{receipt_id}` until
`status` is no longer `"uploaded"` or `"processing"`.

## Implementation status

### Frontend (`packages/web`) — @RR02-rr

**Implemented** (`feat/frontend-rabit`):

- `src/components/ReceiptUpload.tsx`: file picker with client-side validation
  - Accepts JPG/PNG only (MIME-type check), rejects all other formats
  - Rejects files larger than 5 MB with a human-readable size in the error message
  - Shows selected filename and size; allows replacing or removing the file
  - Calls `onFileReady(file | null)` so the parent can hold the file reference
  - No API calls; deliberately decoupled from the presigned-URL flow
- `src/api/receipts.ts`: typed interface for the API contract above
  - `ReceiptContentType`, `CreateReceiptRequest`, `CreateReceiptResponse` types
  - `createReceipt(householdId, req)`: POST with Cognito auth (via `defaults.fetch`)
  - `uploadToS3(uploadUrl, file)`: plain `fetch` PUT, no auth header (required by S3)
  - Both functions are ready; neither is called automatically yet
- `src/pages/HouseholdPage.tsx`: integrates `ReceiptUpload`; holds typed `PendingUpload` state
  - `PendingUpload` captures `file`, `content_type` and `size_bytes` — exactly what `createReceipt` needs
  - Upload button is visible once a file is selected but stays `disabled` until the API exists
  - Accessible: `<section aria-labelledby>`, `role="alert"` on errors, hidden native input with `aria-label`

**To wire up once `POST /households/{id}/receipts` is deployed:**

1. Run `mise run generate` so `createReceipt` appears in `client.gen.ts`
2. Remove the manual types from `src/api/receipts.ts` (or delete the file) and import from `@/api`
3. In `HouseholdPage.tsx`, replace the `disabled` button with a `useMutation` call:
   - `createReceipt(householdId, { content_type, size_bytes })`
   - then `uploadToS3(upload_url, file)`
4. Add status polling with `refetchInterval` on `getReceipt`

**Still planned:**
- Status badge: `processing / done / failed / duplicate` (needs `GET /receipts/{id}` with SQL)
- Client-side image compression to ~300–500 KB (planned: `browser-image-compression`)
- PDF support (single-page only; rejected with a clear error message)

### Backend / infrastructure — @timonrieger, @Dam-Mil

**Implemented**:
- S3 bucket with lifecycle rules, CORS, and object-created → SQS notification (`template.yaml`)
- SQS queue + dead-letter queue; worker skeleton (`handlers/process_receipt.py`)

**Planned**:
- `POST /households/{id}/receipts`: generate UUID as receipt id, insert DB row, return presigned PUT URL (see contract above)
- Worker: Textract call, status writes, duplicate detection via file hash

## Notes

- The receipt id is created when the presigned URL is issued and is part of the S3 key.
- S3 lifecycle: Glacier Instant Retrieval after 30 days, delete never-processed uploads (tag `status=pending`) after 7 days, abort incomplete multipart uploads after 1 day.
- A Textract mock mode (realistic delay and rate limit) is needed for the load test.

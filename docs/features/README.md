# Features (MVP)

One file per MVP feature from the [proposal](../project/kassenzettel.md), chapter 3. Each lists acceptance criteria (the "done when"), owners, and status. Create GitHub issues from these; keep the checkboxes here up to date.

| # | Feature | Owners | Milestone |
|---|---|---|---|
| 01 | [Upload & processing](01-upload-processing.md) | @timonrieger, @Dam-Mil, @RR02-rr | M2 (end SW7) |
| 02 | [Extraction & categorization](02-extraction-categorization.md) | @Dam-Mil, @RR02-rr | M2 / M3 |
| 03 | [Dashboard](03-dashboard.md) | @nosernoel, @schmid277 | M3 (end SW10) |
| 04 | [Households](04-households.md) | @nosernoel, @schmid277 | M3 |
| 05 | [Account deletion](05-account-deletion.md) | @Dam-Mil, @RR02-rr | M3 |

**Cross-cutting (every feature):** Cognito login, strict household isolation, authorization check in every Lambda, private S3 with short-lived presigned URLs. See [architecture.md#security](../architecture.md#security).

**If time runs short**, these optional parts are dropped in this order (decided before M3, recorded in the report):

1. Previous-month comparison in the dashboard
2. E-mail notification (in-app status only)
3. PDF upload (photos only)
4. Correction view limited to categories
5. Households without invite code (join via shared household id)

**Quality goals** (proven with a load test, owner @schmid277): p95 ≤ 10 s from upload to done; a spike of 200 uploads in one minute is fully processed within 3 minutes with nothing lost; API p95 < 1 s during the spike; no receipt in the DLQ because of Textract throttling.

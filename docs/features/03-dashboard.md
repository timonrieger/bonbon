# 03 Dashboard & reports

**Owners:** @nosernoel (report queries in SQL, API), @schmid277 (dashboard UI) · **Milestone:** M3, end of SW10

## Done when

- [x] Spending per month, per category and per store (API #18, charts #10)
- [x] Comparison with the previous month (#63)
- [x] Household receipt list with a detail view (including the original image via presigned URL)
- [x] Filter the household receipt list by month (#30)
- [x] Show possible duplicate and missing purchase date hints in the list and detail view (#30)
- [x] Monthly totals are computed in SQL at query time (`GROUP BY` month, category, store), so corrections, deletions and date changes are reflected immediately ([decisions/0006](../decisions/0006-postgresql-on-rds.md))
- [x] Duplicates are excluded from all totals
- [ ] Totals are current within a few seconds of a change

## Implementation status

- **API** (#18, #26): receipt reads, corrections and reports run on PostgreSQL.
- **UI** (`DashboardPage.tsx`, #8, #10): month navigation, six-month trend chart, charts per category and per store for the selected month.
- The dashboard shares the household access query with the household and receipt pages. It verifies access on entry before showing cached reports. A confirmed access denial hides the dashboard and evicts cached private data for that household.
- **Receipt UI:** `HouseholdPage.tsx` composes `HouseholdReceiptList`, which renders the receipts in API order and links to `ReceiptPage.tsx`. Its companion hook owns the month filter and list polling. The list opens with all months and can be filtered by month using the API's purchase-date and upload-date rules. Uploads and corrections invalidate all cached list variants for that household. The detail view shows the original image and receipt items. Both views flag possible duplicates separately from the processing status and explicitly label missing purchase dates. The list labels the upload timestamp separately.
- **Previous-month comparison** (#63): The dashboard starts on the current month. It shows spending for the selected month and the preceding calendar month, plus the signed difference in CHF and as a percentage of the previous total. The CHF difference remains visible when the previous total is zero, including months without receipts. The API gives the same zero total for both cases, so the UI explains why the percentage is unavailable.
- **Open in the dashboard UI:** receipt count for the month and the receipt list placeholder.

## Verification

- To run the local [dashboard access browser fixture](../../packages/web/tests/dashboard-access.html), start `mise run //packages/web:dev` and open `/tests/dashboard-access.html`. It uses mocked responses and covers previous-month totals, positive and negative changes, and the zero baseline.
- Month selection, duplicate and missing-date hints, and list refresh after uploads and corrections (#30) were checked locally in Chromium with mocked responses.
- On 2026-11-20, a manual test on the live `bonbon-dev` stack verified that the dashboard reflected the [receipt category correction](02-extraction-categorization.md#verification).

## API

All routes check membership (404 for non-members). Amounts are integers in Rappen, months are `YYYY-MM`.

| Route | Frontend function | Returns |
| --- | --- | --- |
| `GET /households/{household_id}/receipts?month=` | `listReceipts` | All receipts, newest purchase date first (upload date if none, then latest upload); `month` is optional. Uploads whose file never arrived (still `uploaded` after 30 minutes) are left out |
| `GET /households/{household_id}/receipts/{receipt_id}` | `getReceipt` | Receipt with items and a presigned `image_url` |
| `PATCH /households/{household_id}/receipts/{receipt_id}` | `updateReceipt` | Corrects a `done` receipt, see [02](02-extraction-categorization.md#api-26) |
| `GET /households/{household_id}/reports/monthly?month=` | `getMonthlyReport` | Total, receipt count, per category, per store, previous month's total |
| `GET /households/{household_id}/reports/trend?months=6` | `getSpendingTrend` | Total per month, oldest first, months without spending as 0 (`months` 1–24) |

A receipt that belongs to another household is a 404 as well.

## Rules

- Only receipts with status `done` count; duplicates and failed receipts are left out.
- Only the same file (file hash) makes a receipt a `duplicate`. Two receipts with the same store, date and total are both kept as `done` and both count, because a household can buy the same thing twice on one day. The API marks such a receipt with `possible_duplicate: true` (list and detail) so the UI can point it out; the member decides. Receipts without store, date or total are never flagged.
- A receipt without a recognized purchase date counts towards the month it was uploaded in (`COALESCE(purchase_date, created_at::date)`, upload date in Swiss time). The current month of the trend is Swiss time as well; the database runs in UTC. The API returns `purchase_date: null` for it, so the UI can point it out. The worker stores `NULL` rather than guessing a date.
- The receipt month filter accepts `0001-01` through `9999-11`. The backend needs a representable first day of the following month as the exclusive upper bound.

## Notes

- Nothing is pre-aggregated; the `(household_id, purchase_date)` index on `receipts` keeps the queries fast.
- Charts with Recharts.

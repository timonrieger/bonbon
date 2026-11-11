# 03 Dashboard & reports

**Owners:** @nosernoel (report queries in SQL, API), @schmid277 (dashboard UI) · **Milestone:** M3, end of SW10

## Done when

- [ ] Spending per month, per category and per store
- [ ] Comparison with the previous month (optional, first to drop)
- [ ] List of all receipts with a detail view (including the original image via presigned URL)
- [ ] Monthly totals are computed in SQL at query time (`GROUP BY` month, category, store), so corrections, deletions and date changes are reflected immediately ([decisions/0006](../decisions/0006-postgresql-on-rds.md))
- [ ] Duplicates are excluded from all totals
- [ ] Totals are current within a few seconds of a change

## API

All routes check membership (404 for non-members). Amounts are integers in Rappen, months are `YYYY-MM`.

| Route | Frontend function | Returns |
|---|---|---|
| `GET /households/{household_id}/receipts?month=` | `listReceipts` | All receipts, newest first; `month` is optional |
| `GET /households/{household_id}/receipts/{receipt_id}` | `getReceipt` | Receipt with items and a presigned `image_url` |
| `GET /households/{household_id}/reports/monthly?month=` | `getMonthlyReport` | Total, receipt count, per category, per store, previous month's total |
| `GET /households/{household_id}/reports/trend?months=6` | `getSpendingTrend` | Total per month, oldest first, months without spending as 0 (`months` 1–24) |

The models are fixed so the dashboard can be built against them; the routes answer 501 until the SQL is in place.

## Rules

- Only receipts with status `done` count; duplicates and failed receipts are left out.
- A receipt without a recognized purchase date counts towards the month it was uploaded in (`COALESCE(purchase_date, created_at::date)`). The API returns `purchase_date: null` for it, so the UI can point it out. The worker stores `NULL` rather than guessing a date.

## Notes

- Nothing is pre-aggregated; the `(household_id, purchase_date)` index on `receipts` keeps the queries fast.
- Charts with Recharts.

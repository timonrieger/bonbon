# 03 Dashboard & reports

**Owners:** @nosernoel (report queries in SQL, API), @schmid277 (dashboard UI) · **Milestone:** M3, end of SW10

## Done when

- [ ] Spending per month, per category and per store
- [ ] Comparison with the previous month (optional, first to drop)
- [ ] List of all receipts with a detail view (including the original image via presigned URL)
- [ ] Monthly totals are computed in SQL at query time (`GROUP BY` month, category, store), so corrections, deletions and date changes are reflected immediately ([decisions/0006](../decisions/0006-postgresql-on-rds.md))
- [ ] Duplicates are excluded from all totals
- [ ] Totals are current within a few seconds of a change

## Notes

- Nothing is pre-aggregated; the `(household_id, purchase_date)` index on `receipts` keeps the queries fast.
- Charts with Recharts.

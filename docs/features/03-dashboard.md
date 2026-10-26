# 03 Dashboard & reports

**Owners:** @nosernoel (aggregation via DynamoDB Streams, API), @schmid277 (dashboard UI) · **Milestone:** M3, end of SW10

## Done when

- [ ] Spending per month, per category and per store
- [ ] Comparison with the previous month (optional, first to drop)
- [ ] List of all receipts with a detail view (including the original image via presigned URL)
- [ ] Monthly totals are pre-computed: every receipt change triggers (via Streams) a full recalculation of the affected month, and on a date correction the previous month too
- [ ] Duplicates are excluded from all totals
- [ ] Totals are current within a few seconds of a change

## Notes

- Recalculate instead of increment/decrement, so corrections, deletions and duplicate events stay correct.
- Charts with Recharts.

# 02 Extraction & categorization (with correction)

**Owners:** P3 (worker, Textract), P4 (correction UI) · **Milestone:** M2 (extraction), M3 (correction)

## Done when

- [ ] Extracts store, date, items, unit prices and total (Textract AnalyzeExpense)
- [ ] Two-line items: if Textract doesn't return a name, use the last line of the row's raw text (`EXPENSE_ROW`)
- [ ] Every item gets a category from the keyword rule table; no match → "Sonstiges"
- [ ] Manual correction of items, prices and categories (optional: categories only)
- [ ] Corrections only update the database; nothing is trained
- [ ] Test set of ~20 real receipts from all four stores; target ≥ 90 % of items correct

## Notes

- Textract is confirmed available in the Learner Lab (SW5 test, ~3.3 s per call, 5 calls/s limit).
- The external AI API is only a fallback, with its key in SSM Parameter Store and a strict cost limit. Don't build it unless the test set shows Textract isn't good enough.

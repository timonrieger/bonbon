# 02 Extraction & categorization (with correction)

**Owners:** @Dam-Mil (worker, Textract), @RR02-rr (correction UI) · **Milestone:** M2 (extraction), M3 (correction)

## Done when

- [x] Extracts store, date, items, unit prices and total (Textract AnalyzeExpense; accuracy is checked with the test set below)
- [x] Two-line items: if Textract doesn't return a name, use the last line of the row's raw text (`EXPENSE_ROW`)
- [x] Every item gets a category from the keyword rule table; no match → "Sonstiges" (rules + `categorize()` in #42; called by the database worker #38)
- [x] Manual correction of store, purchase date, total, items, prices and categories
- [x] Corrections only update the database; nothing is trained
- [ ] Test set of ~20 real receipts from all four stores; target ≥ 90 % of items correct

## Implementation status

### Frontend (`packages/web`) — @RR02-rr

- `ReceiptPage.tsx` displays an extracted receipt and polls while processing is pending. A processed (`done`) receipt can be opened for editing. The page keeps the loaded image preview when renewing the presigned original link on demand.
- `ReceiptCorrectionForm.tsx` edits the store, purchase date, total and existing item rows. Categories use the backend order from `listCategories`, with «Sonstiges» last. The total is edited independently of the items. Amounts accept negative values and are sent as integer Rappen. Quantities allow up to three decimal places within the database range.
- The form compares edits with its starting snapshot. A PATCH omits untouched fields, sends `null` for cleared header fields or unit prices, and replaces the complete item list when an item is edited. A background refresh or a recoverable save failure keeps the draft intact. Cancelling discards the draft. Before replacing items, the frontend fetches the latest item list and refuses to apply an edit based on a changed snapshot. The user can discard the draft and review the current receipt. Another write can still occur between this check and PATCH. Closing that window requires a backend version precondition.
- On success, the detail cache receives the corrected receipt and the household's receipt lists, monthly reports and spending trends are invalidated, including months affected by a purchase date change. Access denial removes the private detail from view.

### API (#26)

| Route | Frontend function | What it does |
|---|---|---|
| `PATCH /households/{household_id}/receipts/{receipt_id}` | `updateReceipt` | Corrects `store`, `purchase_date`, `total_rappen` and `items` of a `done` receipt. Omitted header fields stay unchanged and `null` clears them. An item list replaces all items, including an empty list. Omitted or `null` items stay unchanged. Returns the corrected `ReceiptDetail` |
| `GET /categories` | `listCategories` | All category names, sorted, «Sonstiges» last; the same for every household |

- 404 for non-members and receipts of another household, 409 for receipts that aren't `done` (still processing, failed or duplicate), 422 for an invalid body or a category that isn't in `listCategories`.
- Item names and categories are trimmed and must not be empty; quantity > 0 (three decimals kept); positions unique; amounts may be negative.
- The total is never computed from the items: vouchers are often not line items (see Notes).
- One transaction; the reports sum at query time, so the dashboard shows the correction immediately.

### Backend (`packages/api`) — @nosernoel, @Dam-Mil

**Implemented** (#22): `bonbon/receipts/expense.py` turns the AnalyzeExpense JSON into what the database worker stores. Tested with a real Migros receipt (`tests/data/textract_migros.json`). Nothing is guessed; what can't be read stays `NULL` until a member corrects it.

- Store: `VENDOR_NAME` (or `NAME` in the vendor group). Headers containing Migros, Coop, Aldi or Lidl become exactly that name, so «MIGROS» and «Genossenschaft Migros Ostschweiz» add up in the report per store; any other store keeps its first line as printed.
- Date: `INVOICE_RECEIPT_DATE` as `17.11.2026`, `17.11.26`, `17/11/2026` or ISO, a time after it is ignored; anything else is `NULL`.
- Total: the first `TOTAL` in CHF, else `AMOUNT_PAID`. Totals in another currency (Migros prints «Total in EUR») are skipped by Textract's `Currency` code or the label. Never summed up from the items.
- Amounts in Rappen, also `CHF 12.50`, `12,50`, `1'234.50` and deductions as `-1.20` or `20.00-`.
- Items: name from `ITEM`, else the last line of `EXPENSE_ROW`; `PRICE` is the line amount, `UNIT_PRICE` stays as printed (per kg for weighed goods, before the reduction for reduced items); quantity 1 if missing. Rows without a price are left out.
- Category: `categorize()` from `bonbon/receipts/categories.py` (#42), called before the transaction because it loads its rules from the database once per container.

**Implemented** (@Dam-Mil):
- Textract Lambda: `AnalyzeExpense`, raw JSON to S3, result on the queue (#41)
- Categorization: fixed category list + keyword rules seeded in migration 0006, and
  `categorize()` in `bonbon/receipts/categories.py`; the match ending furthest right wins
  (head noun of a German compound), ties broken by the longer keyword, no match → `Sonstiges` (#42)

**Planned**:
- Tune the rules against the ~20-receipt test set; target ≥ 90 % of items correct (#24)

## Rules

- Every member of the household can correct any receipt, not only the uploader.

## Notes

- Spending per category adds up the items, the month and store totals add up the receipt totals. They can differ: Textract doesn't return vouchers such as Migros Cumulus-Bons as line items (on the test receipt the items add up to 215.70, the total is 185.70). We keep both as read and check how often this happens with the test set (#24).

- Textract is confirmed available in the Learner Lab (SW5 test, ~3.3 s per call, 5 calls/s limit).
- The external AI API is only a fallback, with its key in SSM Parameter Store and a strict cost limit. Don't build it unless the test set shows Textract isn't good enough.

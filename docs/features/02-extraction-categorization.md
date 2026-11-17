# 02 Extraction & categorization (with correction)

**Owners:** @Dam-Mil (worker, Textract), @RR02-rr (correction UI) · **Milestone:** M2 (extraction), M3 (correction)

## Done when

- [ ] Extracts store, date, items, unit prices and total (Textract AnalyzeExpense)
- [ ] Two-line items: if Textract doesn't return a name, use the last line of the row's raw text (`EXPENSE_ROW`)
- [x] Every item gets a category from the keyword rule table; no match → "Sonstiges" (rules + `categorize()` in #42; called by the database worker #38)
- [ ] Manual correction of items, prices and categories (optional: categories only); API done (#26), UI wiring open
- [ ] Corrections only update the database; nothing is trained
- [ ] Test set of ~20 real receipts from all four stores; target ≥ 90 % of items correct

## Implementation status

### Frontend (`packages/web`) — @RR02-rr

**Implemented** (#16):

- `src/components/ReceiptCorrectionForm.tsx`: correction form for auto-extracted receipt data
  - Displays and edits: `store` (text), `purchase_date` (date picker), item rows
  - Each item row edits: `name`, `quantity`, `unit_price_rappen` (CHF), `amount_rappen` (CHF), `category`
  - `total_rappen`, `status`, `image_url`, `position` are read-only (computed or backend-owned)
  - Local validation: empty names/categories, invalid amounts, malformed date
  - Error messages shown per field with `role="alert"`; form re-validates on change after first submit attempt
  - `onSave(correction: ReceiptCorrection)` callback with the validated values converted
    back to API units (Rappen, numbers, `null`) — parent is responsible for the PATCH call
  - Save button is `disabled` until PATCH endpoint exists; no fake save, no mock
  - Keyboard-navigable; each input has an associated `<label>` via `useId()`-based IDs
  - Re-initialises when `receipt.id` changes (e.g. navigation between receipts); a refetch
    of the same receipt keeps unsaved edits
  - Form state (`ReceiptDraft`, prices in CHF) and the `ReceiptCorrection` stand-in for the
    PATCH body live in the component file
- `src/api/receipts.ts`: added the `formatRappen` helper

**Backend ready** (#26): `GET /households/{id}/receipts/{id}` returns the generated
`ReceiptDetail` the form takes (#18); items stay empty until the worker writes them (#22).

**To wire up:**

1. Replace the `ReceiptCorrection` stand-in in the component with the generated
   `ReceiptCorrection` from `@/api`. Same shape, plus an optional `total_rappen`.
2. In `HouseholdPage.tsx` (or a new `ReceiptPage`): render `<ReceiptCorrectionForm>` with
   data from `useQuery(getReceipt)` and an `onSave` from `useMutation(updateReceipt)`; the
   response is the corrected `ReceiptDetail`, so it can go straight into the query cache.
3. Category field as a `<select>` from `useQuery(listCategories)`.
4. Remove the `disabled` from the save button.
5. Allow negative amounts (discounts, vouchers), the API accepts them.

### API (#26)

| Route | Frontend function | What it does |
|---|---|---|
| `PATCH /households/{household_id}/receipts/{receipt_id}` | `updateReceipt` | Corrects `store`, `purchase_date`, `total_rappen` and `items` of a `done` receipt. Fields left out stay, `null` clears them; `items` replaces all items. Returns the corrected `ReceiptDetail` |
| `GET /categories` | `listCategories` | All category names, sorted, «Sonstiges» last; the same for every household |

- 404 for non-members and receipts of another household, 409 for receipts that aren't `done` (still processing, failed or duplicate), 422 for an invalid body or a category that isn't in `listCategories`.
- Item names and categories are trimmed and must not be empty; quantity > 0 (three decimals kept); positions unique; amounts may be negative.
- The total is never computed from the items: vouchers are often not line items (see Notes).
- One transaction; the reports sum at query time, so the dashboard shows the correction immediately.

### Backend (`packages/api`) — @Dam-Mil

**Implemented**:
- Textract Lambda: `AnalyzeExpense`, raw JSON to S3, result on the queue (#41)
- Categorization: fixed category list + keyword rules seeded in migration 0006, and
  `categorize()` in `bonbon/receipts/categories.py`; the match ending furthest right wins
  (head noun of a German compound), ties broken by the longer keyword, no match → `Sonstiges` (#42)

**Planned**:
- Database Lambda writes items with their category via `categorize()` (#38)
- Tune the rules against the ~20-receipt test set; target ≥ 90 % of items correct (#24)

## Rules

- Every member of the household can correct any receipt, not only the uploader.

## Notes

- Textract is confirmed available in the Learner Lab (SW5 test, ~3.3 s per call, 5 calls/s limit).
- The external AI API is only a fallback, with its key in SSM Parameter Store and a strict cost limit. Don't build it unless the test set shows Textract isn't good enough.

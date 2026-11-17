# 02 Extraction & categorization (with correction)

**Owners:** @Dam-Mil (worker, Textract), @RR02-rr (correction UI) · **Milestone:** M2 (extraction), M3 (correction)

## Done when

- [ ] Extracts store, date, items, unit prices and total (Textract AnalyzeExpense)
- [x] Two-line items: if Textract doesn't return a name, use the last line of the row's raw text (`EXPENSE_ROW`)
- [x] Every item gets a category from the keyword rule table; no match → "Sonstiges" (rules + `categorize()` in #42; called by the database worker #38)
- [ ] Manual correction of items, prices and categories (optional: categories only)
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

**Blocked on backend — needed for full integration:**

1. ~~`GET /households/{id}/receipts/{id}` must return real data~~: done (#18). It returns
   the generated `ReceiptDetail` type the form takes; items stay empty until the worker writes them.
2. A `PATCH /households/{id}/receipts/{id}` endpoint is needed to save corrections.
   The request body type is not yet designed. Suggested shape (coordinate with @Dam-Mil):
   ```json
   {
     "store": "string | null",
     "purchase_date": "YYYY-MM-DD | null",
     "items": [
       { "position": 1, "name": "…", "quantity": 1.0,
         "unit_price_rappen": 150, "amount_rappen": 150, "category": "…" }
     ]
   }
   ```
3. Available categories as an API list (`GET /categories` or inline in `ReceiptDetail`)
   would let the category field become a `<select>` instead of a free-text input.
   The fixed category list and keyword rules are seeded by migration 0006 (#42).

**To wire up once PATCH is deployed:**

1. Run `mise run generate` — replace `ReceiptCorrection` with the generated PATCH request type
2. In `HouseholdPage.tsx` (or a new `ReceiptPage`): render `<ReceiptCorrectionForm>` with
   data from `useQuery(getReceipt)` and an `onSave` from `useMutation(patchReceipt)`
3. Remove the `disabled` from the save button

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

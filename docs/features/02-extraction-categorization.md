# 02 Extraction & categorization (with correction)

**Owners:** @Dam-Mil (worker, Textract), @RR02-rr (correction UI) · **Milestone:** M2 (extraction), M3 (correction)

## Done when

- [ ] Extracts store, date, items, unit prices and total (Textract AnalyzeExpense)
- [ ] Two-line items: if Textract doesn't return a name, use the last line of the row's raw text (`EXPENSE_ROW`)
- [ ] Every item gets a category from the keyword rule table; no match → "Sonstiges"
- [ ] Manual correction of items, prices and categories (optional: categories only)
- [ ] Corrections only update the database; nothing is trained
- [ ] Test set of ~20 real receipts from all four stores; target ≥ 90 % of items correct

## Implementation status

### Frontend (`packages/web`) — @RR02-rr

**Implemented** (`feat/frontend-rabit`):

- `src/components/ReceiptCorrectionForm.tsx`: correction form for auto-extracted receipt data
  - Displays and edits: `store` (text), `purchase_date` (date picker), item rows
  - Each item row edits: `name`, `quantity`, `unit_price_rappen` (CHF), `amount_rappen` (CHF), `category`
  - `total_rappen`, `status`, `image_url`, `position` are read-only (computed or backend-owned)
  - Local validation: empty names/categories, invalid amounts, malformed date
  - Error messages shown per field with `role="alert"`; form re-validates on change after first submit attempt
  - `onSave(draft: ReceiptDraft)` callback — parent is responsible for the PATCH call
  - Save button is `disabled` until PATCH endpoint exists; no fake save, no mock
  - Keyboard-navigable; each input has an associated `<label>` via `useId()`-based IDs
  - Re-initialises cleanly when `receipt.id` changes (e.g. navigation between receipts)
- `src/api/receipts.ts`: added `ReceiptItemDraft`, `ReceiptDraft`, `SaveReceiptDraft` types and `formatRappen` helper

**Blocked on backend — needed for full integration:**

1. `GET /households/{id}/receipts/{id}` must return real data (SQL) instead of 501.
   The TypeScript types (`ReceiptDetailProps` in `ReceiptCorrectionForm.tsx`) match
   the `ReceiptDetail` shape from `feat/receipts-reports-contract`.
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
   Currently only `'Sonstiges'` exists in the database.

**To wire up once PATCH is deployed:**

1. Run `mise run generate` — `ReceiptDraft` types will come from `@/api`
2. In `HouseholdPage.tsx` (or a new `ReceiptPage`): render `<ReceiptCorrectionForm>` with
   data from `useQuery(getReceipt)` and an `onSave` from `useMutation(patchReceipt)`
3. Remove the `disabled` from the save button
## Rules

- Every member of the household can correct any receipt, not only the uploader.

## Notes

- Textract is confirmed available in the Learner Lab (SW5 test, ~3.3 s per call, 5 calls/s limit).
- The external AI API is only a fallback, with its key in SSM Parameter Store and a strict cost limit. Don't build it unless the test set shows Textract isn't good enough.

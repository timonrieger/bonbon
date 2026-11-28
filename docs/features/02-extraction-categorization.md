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

**Implemented** (#16, #26):

- `src/components/ReceiptCorrectionForm.tsx`: correction form for auto-extracted receipt data
  - Edits `store`, `purchase_date`, `total_rappen` and existing item rows
  - Each item row edits `name`, `quantity`, `unit_price_rappen`, `amount_rappen` and `category`. The form uses the choices from `listCategories`.
  - Validates fields locally and sends the generated `ReceiptCorrection` shape to `onSave`. Prices are entered in CHF and sent in integer Rappen, including negative amounts.
  - A refetch of the same receipt keeps unsaved edits.
  - Correction mode includes every receipt item, regardless of the read-only table pagination (#62).
- `src/pages/ReceiptPage.tsx` mounts the form for processed (`done`) receipts and saves through `updateReceipt`. The response updates the detail cache and invalidates the household's receipt lists, monthly reports and trends.
- Before replacing items, the frontend checks the current item list against the draft's starting snapshot. A write between that check and PATCH can still overwrite a concurrent edit. Closing that window requires a backend version precondition.

### API (#26)

| Route | Frontend function | What it does |
| --- | --- | --- |
| `PATCH /households/{household_id}/receipts/{receipt_id}` | `updateReceipt` | Corrects `store`, `purchase_date`, `total_rappen` and `items` of a `done` receipt. Omitted fields stay unchanged. `null` clears header fields, and an item list replaces all items. Returns the corrected `ReceiptDetail` |
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
- Categorization uses the fixed category list and keyword rules seeded in migration 0006.
  In `categorize()` (`bonbon/receipts/categories.py`), the match ending furthest right wins
  (head noun of a German compound), ties broken by the longer keyword, no match → `Sonstiges` (#42)

**Recognition quality** (#24): `mise run quality` compares stored Textract responses with
ground truth in `packages/api/tests/data/<name>.expected.json` and reports the share of items
correct per store (target ≥ 90 %) and typical errors. The stored Migros fixture scored
**41/43 items (95 %)**, with the store and total correct. The fixture has no printed date,
so it provides no measure of date recognition. Migration `0007` adds keyword rules for
brands and product lines such as Ragusa, Twist, Bon Chef, Nivea and Cantadou.

- Typical remaining errors (two on the Migros receipt): OCR abbreviations Textract can't expand
  (`F Kug.` for Frey Kugeln → `Sonstiges`), and a descriptive suffix that hijacks the
  rightmost-match rule (`M Apfelmus ohne Zucker` matches `zucker` → Grundnahrungsmittel instead
  of Tiefkühl & Konserven).

**Planned**:

- Run the full ~20-receipt set (#34) for a per-store figure across Migros, Coop, Aldi and Lidl;
  the 95 % above is from the single Migros fixture used to tune the rules.

## Verification

- For #62, the desktop and mobile pagination fixture passed the correction scenario starting on page 3. The form showed all 41 items, the PATCH preserved the complete ordered list with the last item corrected, and saving or cancelling returned to page 1. See [dashboard verification](03-dashboard.md#verification).
- On 2026-11-20, a separate manual test on the live `bonbon-dev` stack verified that a processed Migros receipt showed a purchase date of 09.05.2018 and a total of CHF 26.00. The detail view displayed the original image and extracted items.
- An item category was corrected through the live PATCH API. The correction persisted after a full browser reload and appeared in the [dashboard](03-dashboard.md#verification).

## Rules

- Every member of the household can correct any receipt, not only the uploader.

## Notes

- Spending per category adds up the items, the month and store totals add up the receipt totals. They can differ: Textract doesn't return vouchers such as Migros Cumulus-Bons as line items (on the test receipt the items add up to 215.70, the total is 185.70). We keep both as read and check how often this happens with the test set (#24).

- Textract is confirmed available in the Learner Lab (SW5 test, ~3.3 s per call, 5 calls/s limit).
- The external AI API is only a fallback, with its key in SSM Parameter Store and a strict cost limit. Don't build it unless the test set shows Textract isn't good enough.

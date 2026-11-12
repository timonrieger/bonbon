/**
 * ReceiptCorrectionForm – display and locally edit an auto-extracted receipt.
 *
 * Shows the recognised header (store, date, total) and all line items.
 * Every field that the data model allows to be corrected is an editable input.
 * The component is intentionally decoupled from the API: it validates locally,
 * then calls `onSave(draft)` so the parent can issue the PATCH request once
 * PATCH /households/{id}/receipts/{id} exists.
 *
 * What this component does NOT do:
 *  - Fetch receipt data  (GET /households/{id}/receipts/{id} – returns 501 today)
 *  - Save to the backend (PATCH endpoint not yet designed)
 *
 * See docs/features/02-extraction-categorization.md.
 */
import { useEffect, useId, useState } from 'react';
import type { ReceiptDraft, ReceiptItemDraft, SaveReceiptDraft } from '@/api/receipts';
import { formatRappen } from '@/api/receipts';

// ---------------------------------------------------------------------------
// Types accepted by this component
// ---------------------------------------------------------------------------

/** Read-only receipt data as returned by GET /households/{id}/receipts/{id}. */
export interface ReceiptDetailProps {
  id: string;
  status: 'uploaded' | 'processing' | 'done' | 'failed' | 'duplicate';
  store: string | null;
  purchase_date: string | null; // ISO date "YYYY-MM-DD" or null
  total_rappen: number | null;
  uploaded_by_name: string | null;
  created_at: string; // ISO datetime
  image_url: string;
  items: Array<{
    position: number;
    name: string;
    quantity: number;
    unit_price_rappen: number | null;
    amount_rappen: number;
    category: string;
  }>;
}

export interface ReceiptCorrectionFormProps {
  receipt: ReceiptDetailProps;
  /**
   * Called when the user submits a valid correction.
   * Disabled (button is not interactive) until the PATCH endpoint exists.
   * Pass a no-op `() => {}` for now; wire up `useMutation` later.
   */
  onSave: SaveReceiptDraft;
  /** Whether a save operation is currently in flight (disables the form). */
  isSaving?: boolean;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function rappenToInput(rappen: number | null): string {
  if (rappen === null) return '';
  return (rappen / 100).toFixed(2);
}

function inputToRappen(value: string): number | null {
  if (value.trim() === '') return null;
  const n = Number.parseFloat(value.replace(',', '.'));
  if (Number.isNaN(n) || n < 0) return null;
  return Math.round(n * 100);
}

function itemToDraft(item: ReceiptDetailProps['items'][number]): ReceiptItemDraft {
  return {
    position: item.position,
    name: item.name,
    quantity: String(item.quantity),
    unit_price_rappen: rappenToInput(item.unit_price_rappen),
    amount_rappen: rappenToInput(item.amount_rappen),
    category: item.category
  };
}

// ---------------------------------------------------------------------------
// Sub-component: a single item row
// ---------------------------------------------------------------------------

interface ItemRowProps {
  item: ReceiptItemDraft;
  index: number;
  baseId: string;
  disabled: boolean;
  onChange: (index: number, field: keyof ReceiptItemDraft, value: string) => void;
}

function ItemRow({ item, index, baseId, disabled, onChange }: ItemRowProps) {
  const rowId = `${baseId}-item-${item.position}`;
  return (
    <tr className="border-t border-gray-100">
      {/* Name */}
      <td className="py-1.5 pr-2">
        <label className="sr-only" htmlFor={`${rowId}-name`}>
          Bezeichnung Pos. {item.position}
        </label>
        <input
          id={`${rowId}-name`}
          type="text"
          value={item.name}
          disabled={disabled}
          onChange={(e) => onChange(index, 'name', e.target.value)}
          className="w-full rounded border border-gray-200 px-2 py-1 text-sm disabled:bg-gray-50"
          required
          aria-label={`Bezeichnung Pos. ${item.position}`}
        />
      </td>
      {/* Quantity */}
      <td className="py-1.5 pr-2 w-20">
        <label className="sr-only" htmlFor={`${rowId}-qty`}>
          Menge Pos. {item.position}
        </label>
        <input
          id={`${rowId}-qty`}
          type="number"
          value={item.quantity}
          min="0"
          step="0.001"
          disabled={disabled}
          onChange={(e) => onChange(index, 'quantity', e.target.value)}
          className="w-full rounded border border-gray-200 px-2 py-1 text-sm disabled:bg-gray-50"
        />
      </td>
      {/* Unit price */}
      <td className="py-1.5 pr-2 w-24">
        <label className="sr-only" htmlFor={`${rowId}-unit`}>
          Stückpreis Pos. {item.position} (CHF)
        </label>
        <input
          id={`${rowId}-unit`}
          type="number"
          value={item.unit_price_rappen}
          placeholder="–"
          min="0"
          step="0.05"
          disabled={disabled}
          onChange={(e) => onChange(index, 'unit_price_rappen', e.target.value)}
          className="w-full rounded border border-gray-200 px-2 py-1 text-sm disabled:bg-gray-50"
        />
      </td>
      {/* Amount */}
      <td className="py-1.5 pr-2 w-24">
        <label className="sr-only" htmlFor={`${rowId}-amt`}>
          Betrag Pos. {item.position} (CHF)
        </label>
        <input
          id={`${rowId}-amt`}
          type="number"
          value={item.amount_rappen}
          min="0"
          step="0.05"
          disabled={disabled}
          onChange={(e) => onChange(index, 'amount_rappen', e.target.value)}
          className="w-full rounded border border-gray-200 px-2 py-1 text-sm disabled:bg-gray-50"
          required
        />
      </td>
      {/* Category */}
      <td className="py-1.5 w-32">
        <label className="sr-only" htmlFor={`${rowId}-cat`}>
          Kategorie Pos. {item.position}
        </label>
        <input
          id={`${rowId}-cat`}
          type="text"
          value={item.category}
          disabled={disabled}
          onChange={(e) => onChange(index, 'category', e.target.value)}
          className="w-full rounded border border-gray-200 px-2 py-1 text-sm disabled:bg-gray-50"
          required
        />
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

interface FormErrors {
  store?: string;
  purchase_date?: string;
  items: Record<number, Partial<Record<keyof ReceiptItemDraft, string>>>;
}

function validate(draft: ReceiptDraft): FormErrors {
  const errors: FormErrors = { items: {} };

  if (draft.purchase_date !== '' && !/^\d{4}-\d{2}-\d{2}$/.test(draft.purchase_date)) {
    errors.purchase_date = 'Bitte ein gültiges Datum eingeben (TT.MM.JJJJ).';
  }

  for (const [i, item] of draft.items.entries()) {
    const itemErrors: Partial<Record<keyof ReceiptItemDraft, string>> = {};
    if (item.name.trim() === '') {
      itemErrors.name = 'Bezeichnung darf nicht leer sein.';
    }
    const qty = Number.parseFloat(item.quantity.replace(',', '.'));
    if (item.quantity.trim() !== '' && (Number.isNaN(qty) || qty < 0)) {
      itemErrors.quantity = 'Ungültige Menge.';
    }
    if (inputToRappen(item.amount_rappen) === null) {
      itemErrors.amount_rappen = 'Betrag fehlt oder ist ungültig.';
    }
    if (item.category.trim() === '') {
      itemErrors.category = 'Kategorie darf nicht leer sein.';
    }
    if (Object.keys(itemErrors).length > 0) {
      errors.items[i] = itemErrors;
    }
  }

  return errors;
}

function hasErrors(e: FormErrors): boolean {
  return Boolean(e.store || e.purchase_date || Object.keys(e.items).length > 0);
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function ReceiptCorrectionForm({
  receipt,
  onSave,
  isSaving = false
}: ReceiptCorrectionFormProps) {
  const baseId = useId();

  const [draft, setDraft] = useState<ReceiptDraft>(() => ({
    store: receipt.store ?? '',
    purchase_date: receipt.purchase_date ?? '',
    items: receipt.items.map(itemToDraft)
  }));
  const [errors, setErrors] = useState<FormErrors>({ items: {} });
  const [submitted, setSubmitted] = useState(false);

  // Re-initialise the local draft when the receipt prop changes to a different
  // receipt. Using `receipt` as the single dependency is correct: when id
  // changes a new object is passed, triggering the reset; edits to the local
  // draft (via setDraft) do not involve the `receipt` prop, so user input is
  // not lost on unrelated parent re-renders that pass the same receipt object.
  useEffect(() => {
    setDraft({
      store: receipt.store ?? '',
      purchase_date: receipt.purchase_date ?? '',
      items: receipt.items.map(itemToDraft)
    });
    setErrors({ items: {} });
    setSubmitted(false);
  }, [receipt]);

  const disabled = isSaving;

  function handleHeaderChange(field: 'store' | 'purchase_date', value: string) {
    const next = { ...draft, [field]: value };
    setDraft(next);
    if (submitted) setErrors(validate(next));
  }

  function handleItemChange(index: number, field: keyof ReceiptItemDraft, value: string) {
    const nextItems = draft.items.map((item, i) =>
      i === index ? { ...item, [field]: value } : item
    );
    const next = { ...draft, items: nextItems };
    setDraft(next);
    if (submitted) setErrors(validate(next));
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitted(true);
    const errs = validate(draft);
    setErrors(errs);
    if (hasErrors(errs)) return;
    onSave(draft);
  }

  return (
    <form onSubmit={handleSubmit} noValidate aria-label="Kassenzettel korrigieren">
      {/* ── Header ─────────────────────────────────────────────── */}
      <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:gap-6">
        {/* Store */}
        <div className="flex flex-col gap-1 sm:flex-1">
          <label htmlFor={`${baseId}-store`} className="text-sm font-medium">
            Geschäft
          </label>
          <input
            id={`${baseId}-store`}
            type="text"
            value={draft.store}
            placeholder="Nicht erkannt"
            disabled={disabled}
            onChange={(e) => handleHeaderChange('store', e.target.value)}
            className="rounded border border-gray-300 px-3 py-2 text-sm disabled:bg-gray-50"
          />
          {errors.store && (
            <p role="alert" className="text-xs text-red-600">
              {errors.store}
            </p>
          )}
        </div>

        {/* Purchase date */}
        <div className="flex flex-col gap-1 sm:w-44">
          <label htmlFor={`${baseId}-date`} className="text-sm font-medium">
            Kaufdatum
          </label>
          <input
            id={`${baseId}-date`}
            type="date"
            value={draft.purchase_date}
            disabled={disabled}
            onChange={(e) => handleHeaderChange('purchase_date', e.target.value)}
            className="rounded border border-gray-300 px-3 py-2 text-sm disabled:bg-gray-50"
            aria-describedby={errors.purchase_date ? `${baseId}-date-error` : undefined}
          />
          {errors.purchase_date && (
            <p id={`${baseId}-date-error`} role="alert" className="text-xs text-red-600">
              {errors.purchase_date}
            </p>
          )}
        </div>

        {/* Total – read-only */}
        <div className="flex flex-col gap-1 sm:w-32">
          <span className="text-sm font-medium">Total</span>
          <span className="rounded border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-600">
            {formatRappen(receipt.total_rappen)}
          </span>
          <span className="text-xs text-gray-400">Wird aus den Positionen berechnet</span>
        </div>
      </div>

      {/* ── Line items ─────────────────────────────────────────── */}
      {draft.items.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-sm" aria-label="Positionen">
            <thead>
              <tr className="text-left text-xs text-gray-500">
                <th className="pb-2 pr-2 font-medium">Bezeichnung</th>
                <th className="pb-2 pr-2 font-medium w-20">Menge</th>
                <th className="pb-2 pr-2 font-medium w-24">Stückpreis</th>
                <th className="pb-2 pr-2 font-medium w-24">Betrag</th>
                <th className="pb-2 font-medium w-32">Kategorie</th>
              </tr>
            </thead>
            <tbody>
              {draft.items.map((item, index) => (
                <ItemRow
                  key={item.position}
                  item={item}
                  index={index}
                  baseId={baseId}
                  disabled={disabled}
                  onChange={handleItemChange}
                />
              ))}
            </tbody>
          </table>

          {/* Per-item errors rendered below the table to keep the layout clean */}
          {Object.entries(errors.items).map(([i, itemErrors]) =>
            Object.entries(itemErrors).map(([field, msg]) => (
              <p key={`${i}-${field}`} role="alert" className="mt-1 text-xs text-red-600">
                Pos. {draft.items[Number(i)]?.position}: {msg}
              </p>
            ))
          )}
        </div>
      ) : (
        <p className="text-sm text-gray-500">
          Keine Positionen erkannt. Das Backend hat den Kassenzettel noch nicht verarbeitet oder die
          Extraktion ist fehlgeschlagen.
        </p>
      )}

      {/* ── Save button ────────────────────────────────────────── */}
      <div className="mt-6 flex items-center gap-3">
        {/*
         * The button is disabled until PATCH /households/{id}/receipts/{id} exists.
         * To activate: remove `disabled`, pass a real `onSave` from useMutation.
         * See docs/features/02-extraction-categorization.md.
         */}
        <button
          type="submit"
          disabled
          className="rounded bg-black px-4 py-2 text-sm text-white opacity-50"
          title="Speichern wird verfügbar, sobald der Backend-Endpunkt fertiggestellt ist"
        >
          {isSaving ? 'Wird gespeichert…' : 'Korrekturen speichern'}
        </button>
        <span className="text-xs text-gray-400">Speichern wird demnächst verfügbar</span>
      </div>
    </form>
  );
}

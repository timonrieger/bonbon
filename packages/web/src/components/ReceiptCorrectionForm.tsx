import { useId, useLayoutEffect, useRef, useState } from 'react';
import type { ItemCorrection, ReceiptCorrection, ReceiptDetail } from '@/api';

type ItemDraft = Pick<ItemCorrection, 'position' | 'name' | 'category'> & {
  quantity: string;
  unitPrice: string;
  amount: string;
};

type Draft = {
  store: string;
  date: string;
  total: string;
  items: ItemDraft[];
};

type ItemField = Exclude<keyof ItemDraft, 'position'>;
type ItemErrors = Partial<Record<ItemField, string>>;
type FormErrors = Partial<Record<'store' | 'date' | 'total' | 'items', string>> & {
  rows: Record<number, ItemErrors>;
};

const amountError =
  'Gib einen CHF-Betrag mit höchstens zwei Dezimalstellen ein (maximal ±1 Million CHF).';
const inputClass = 'w-full rounded border border-gray-300 px-2 py-1.5 text-sm disabled:bg-gray-50';

function rappenToInput(rappen: number | null): string {
  return rappen === null ? '' : (rappen / 100).toFixed(2);
}

/** Parse fixed-point input as an integer without rounding fractional digits. */
function parseScaled(value: string, precision: number): number {
  const match = /^(-?)(\d+)(?:[.,](\d+))?$/.exec(value.trim());
  if (!match || (match[3]?.length ?? 0) > precision) return Number.NaN;

  const [, sign, whole, decimal = ''] = match;
  return Number(`${sign}${whole}${decimal.padEnd(precision, '0')}`);
}

function toMoney(value: string): number | null {
  if (!value.trim()) return null;
  const rappen = parseScaled(value, 2);
  return Math.abs(rappen) <= 100_000_000 ? rappen : Number.NaN;
}

function toQuantity(value: string): number {
  const thousandths = parseScaled(value, 3);
  return thousandths >= 1 && thousandths <= 9_999_999_999 ? thousandths / 1000 : Number.NaN;
}

function receiptToDraft(receipt: ReceiptDetail): Draft {
  return {
    store: receipt.store ?? '',
    date: receipt.purchase_date ?? '',
    total: rappenToInput(receipt.total_rappen),
    items: receipt.items.map((item) => ({
      position: item.position,
      name: item.name,
      quantity: String(item.quantity),
      unitPrice: rappenToInput(item.unit_price_rappen),
      amount: rappenToInput(item.amount_rappen),
      category: item.category
    }))
  };
}

function buildCorrection(draft: Draft, original: Draft, categories: readonly string[]) {
  const correction: ReceiptCorrection = {};
  const errors: FormErrors = { rows: {} };

  if (draft.store.trim() !== original.store.trim()) {
    const store = draft.store.trim();
    if ([...store].length > 200) errors.store = 'Das Geschäft darf höchstens 200 Zeichen haben.';
    else correction.store = store || null;
  }
  if (draft.date !== original.date) {
    const date = new Date(`${draft.date}T00:00:00Z`);
    if (
      draft.date &&
      (!/^\d{4}-\d{2}-\d{2}$/.test(draft.date) ||
        draft.date.startsWith('0000-') ||
        Number.isNaN(date.getTime()) ||
        date.toISOString().slice(0, 10) !== draft.date)
    ) {
      errors.date = 'Gib ein gültiges Kaufdatum ein.';
    } else correction.purchase_date = draft.date || null;
  }
  if (draft.total !== original.total) {
    const total = toMoney(draft.total);
    if (Number.isNaN(total)) errors.total = amountError;
    else if (total !== toMoney(original.total)) correction.total_rappen = total;
  }

  // A header-only PATCH keeps the original items, including older API data.
  if (JSON.stringify(draft.items) !== JSON.stringify(original.items)) {
    if (draft.items.length > 500)
      errors.items = 'Es können höchstens 500 Positionen gespeichert werden.';
    const items: ItemCorrection[] = [];
    for (const item of draft.items) {
      const row: ItemErrors = {};
      const name = item.name.trim();
      const quantity = toQuantity(item.quantity);
      const unitPrice = toMoney(item.unitPrice);
      const amount = toMoney(item.amount);
      if (!name || [...name].length > 200) row.name = 'Gib 1 bis 200 Zeichen ein.';
      if (Number.isNaN(quantity))
        row.quantity = 'Erlaubt sind 0.001 bis 9’999’999.999 mit höchstens drei Dezimalstellen.';
      if (Number.isNaN(unitPrice)) row.unitPrice = amountError;
      if (amount === null || Number.isNaN(amount)) row.amount = amountError;
      if (!categories.includes(item.category)) row.category = 'Wähle eine verfügbare Kategorie.';
      if (Object.keys(row).length) {
        errors.rows[item.position] = row;
      } else if (amount !== null) {
        items.push({
          position: item.position,
          name,
          quantity,
          unit_price_rappen: unitPrice,
          amount_rappen: amount,
          category: item.category
        });
      }
    }
    correction.items = items;
  }

  return {
    correction,
    errors,
    valid: Object.keys(errors).length === 1 && !Object.keys(errors.rows).length
  };
}

function FieldError({ id, error }: { id: string; error?: string }) {
  return (
    error && (
      <p id={id} className="mt-1 text-xs text-red-700">
        {error}
      </p>
    )
  );
}

const itemFields = [
  { name: 'name', label: 'Bezeichnung', inputMode: 'text' },
  { name: 'quantity', label: 'Menge', inputMode: 'decimal' },
  { name: 'unitPrice', label: 'Stückpreis (CHF)', inputMode: 'decimal' },
  { name: 'amount', label: 'Betrag (CHF)', inputMode: 'decimal' }
] as const;

function ItemRow({
  item,
  baseId,
  categories,
  errors,
  onChange
}: {
  item: ItemDraft;
  baseId: string;
  categories: readonly string[];
  errors?: ItemErrors;
  onChange: (field: ItemField, value: string) => void;
}) {
  const rowId = `${baseId}-item-${item.position}`;
  const categoryId = `${rowId}-category`;
  return (
    <tr className="border-t border-gray-100 align-top">
      {itemFields.map(({ name, label, inputMode }) => {
        const id = `${rowId}-${name}`;
        const error = errors?.[name];
        return (
          <td key={name} className="p-2">
            <label className="sr-only" htmlFor={id}>
              {label}, Position {item.position}
            </label>
            <input
              id={id}
              inputMode={inputMode}
              value={item[name]}
              onChange={(event) => onChange(name, event.target.value)}
              aria-invalid={Boolean(error)}
              aria-describedby={error ? `${id}-error` : undefined}
              className={inputClass}
            />
            <FieldError id={`${id}-error`} error={error} />
          </td>
        );
      })}
      <td className="p-2">
        <label className="sr-only" htmlFor={categoryId}>
          Kategorie, Position {item.position}
        </label>
        <select
          id={categoryId}
          value={item.category}
          onChange={(event) => onChange('category', event.target.value)}
          disabled={!categories.length}
          aria-invalid={Boolean(errors?.category)}
          aria-describedby={errors?.category ? `${categoryId}-error` : undefined}
          className={inputClass}
        >
          {!categories.includes(item.category) && (
            <option value={item.category}>{item.category || 'Kategorie wählen'}</option>
          )}
          {categories.map((category) => (
            <option key={category} value={category}>
              {category}
            </option>
          ))}
        </select>
        <FieldError id={`${categoryId}-error`} error={errors?.category} />
      </td>
    </tr>
  );
}

export function ReceiptCorrectionForm({
  receipt,
  categories,
  canSave,
  isSaving,
  onSave,
  onCancel
}: {
  receipt: ReceiptDetail;
  categories: readonly string[];
  canSave: boolean;
  isSaving: boolean;
  onSave: (correction: ReceiptCorrection) => void;
  onCancel: () => void;
}) {
  const baseId = useId();
  const storeInput = useRef<HTMLInputElement>(null);
  // This snapshot belongs to the edit session. Refetches must not replace it.
  const [original] = useState(() => receiptToDraft(receipt));
  const [draft, setDraft] = useState(original);
  const [submitted, setSubmitted] = useState(false);
  const result = buildCorrection(draft, original, categories);
  const errors: FormErrors = submitted ? result.errors : { rows: {} };
  const dirty = Object.keys(result.correction).length > 0 || !result.valid;

  useLayoutEffect(() => {
    storeInput.current?.focus();
  }, []);

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!canSave || isSaving || !dirty) return;
    setSubmitted(true);
    if (result.valid) onSave(result.correction);
  }

  return (
    <form onSubmit={handleSubmit} noValidate aria-label="Kassenzettel korrigieren">
      <fieldset disabled={isSaving} className="min-w-0">
        <div className="grid gap-4 sm:grid-cols-3">
          {(
            [
              { field: 'store', label: 'Geschäft', type: 'text' },
              { field: 'date', label: 'Kaufdatum', type: 'date' },
              { field: 'total', label: 'Total (CHF)', type: 'text' }
            ] as const
          ).map(({ field, label, type }) => {
            const id = `${baseId}-${field}`;
            const error = errors[field];
            return (
              <div key={field} className="min-w-0">
                <label htmlFor={id} className="mb-1 block text-sm font-medium">
                  {label}
                </label>
                <input
                  id={id}
                  ref={field === 'store' ? storeInput : undefined}
                  type={type}
                  inputMode={field === 'total' ? 'decimal' : undefined}
                  value={draft[field]}
                  onChange={(event) => setDraft({ ...draft, [field]: event.target.value })}
                  aria-invalid={Boolean(error)}
                  aria-describedby={error ? `${id}-error` : undefined}
                  className={inputClass}
                />
                <FieldError id={`${id}-error`} error={error} />
              </div>
            );
          })}
        </div>

        {draft.items.length > 0 ? (
          <section
            className="mt-4 overflow-x-auto"
            // biome-ignore lint/a11y/noNoninteractiveTabindex: keyboard users need to scroll the table on narrow screens
            tabIndex={0}
            aria-label="Belegpositionen bearbeiten"
          >
            <table className="w-full min-w-[40rem] text-sm">
              <thead>
                <tr className="text-left text-xs text-gray-600">
                  {itemFields.map(({ name, label }) => (
                    <th key={name} scope="col" className="p-2">
                      {label}
                    </th>
                  ))}
                  <th scope="col" className="p-2">
                    Kategorie
                  </th>
                </tr>
              </thead>
              <tbody>
                {draft.items.map((item, index) => (
                  <ItemRow
                    key={item.position}
                    item={item}
                    baseId={baseId}
                    categories={categories}
                    errors={errors.rows[item.position]}
                    onChange={(field, value) =>
                      setDraft({
                        ...draft,
                        items: draft.items.map((row, i) =>
                          i === index ? { ...row, [field]: value } : row
                        )
                      })
                    }
                  />
                ))}
              </tbody>
            </table>
          </section>
        ) : (
          <p className="mt-4 text-sm text-gray-600">Keine Positionen vorhanden.</p>
        )}
        <FieldError id={`${baseId}-items-error`} error={errors.items} />

        {submitted && !result.valid && (
          <p role="alert" className="mt-4 text-sm text-red-700">
            Prüfe die markierten Eingaben.
          </p>
        )}
        <div className="mt-4 flex flex-wrap gap-3">
          <button
            type="submit"
            disabled={!canSave || !dirty || isSaving}
            className="rounded bg-black px-4 py-2 text-sm text-white disabled:opacity-50"
          >
            {isSaving ? 'Wird gespeichert…' : 'Korrekturen speichern'}
          </button>
          <button type="button" onClick={onCancel} className="rounded border px-4 py-2 text-sm">
            Abbrechen
          </button>
        </div>
      </fieldset>
    </form>
  );
}

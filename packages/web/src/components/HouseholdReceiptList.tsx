import { skipToken, useQuery, useQueryClient } from '@tanstack/react-query';
import { useId, useState } from 'react';
import { Link } from 'react-router';
import { listReceipts } from '@/api';
import {
  formatDate,
  formatRappen,
  formatUploadTimestamp,
  isReceiptProcessing,
  RECEIPT_POLL_ERROR_INTERVAL,
  RECEIPT_POLL_INTERVAL
} from '@/api/receipts';
import { ReceiptStatusBadge } from '@/components/ReceiptStatusBadge';
import { readHouseholdResource } from '@/features/households/householdAccess';

// The backend needs both the first day of this month and the first day of the next one.
const FIRST_RECEIPT_MONTH = '0001-01';
const LAST_RECEIPT_MONTH = '9999-11';

export function useHouseholdReceiptList(
  householdId: string,
  hasHouseholdAccess: boolean,
  uploadCompletedAt: number | undefined
) {
  const queryClient = useQueryClient();
  const [selectedMonth, setSelectedMonth] = useState('');
  const invalidMonth =
    selectedMonth !== '' &&
    (selectedMonth.length !== 7 ||
      !/^\d{4}-(0[1-9]|1[0-2])$/.test(selectedMonth) ||
      selectedMonth < FIRST_RECEIPT_MONTH ||
      selectedMonth > LAST_RECEIPT_MONTH);
  const receipts = useQuery({
    queryKey: ['receipts', householdId, selectedMonth],
    queryFn: invalidMonth
      ? skipToken
      : ({ signal }) =>
          readHouseholdResource(
            queryClient,
            householdId,
            (options) => listReceipts({ householdId, month: selectedMonth || undefined }, options),
            signal
          ),
    enabled: hasHouseholdAccess && !invalidMonth,
    retry: false,
    refetchIntervalInBackground: false,
    refetchInterval: ({ state }) => {
      // Leave time for a final list request after the server's abandonment cutoff.
      const processing = state.data?.receipts.some((item) =>
        isReceiptProcessing(item, RECEIPT_POLL_ERROR_INTERVAL)
      );
      const refreshFailed = state.status === 'error';
      const recoveringAfterUpload =
        refreshFailed &&
        state.data !== null &&
        uploadCompletedAt !== undefined &&
        state.dataUpdatedAt < uploadCompletedAt &&
        Date.now() - uploadCompletedAt < 60_000;

      if (!processing && !recoveringAfterUpload) return false;
      return refreshFailed ? RECEIPT_POLL_ERROR_INTERVAL : RECEIPT_POLL_INTERVAL;
    }
  });

  return { selectedMonth, setSelectedMonth, invalidMonth, receipts };
}

export function HouseholdReceiptList({
  householdId,
  list
}: {
  householdId: string;
  list: ReturnType<typeof useHouseholdReceiptList>;
}) {
  const { selectedMonth, setSelectedMonth, invalidMonth, receipts } = list;
  const monthInputId = useId();
  const monthErrorId = `${monthInputId}-error`;
  const receiptRows = receipts.data?.receipts;

  return (
    <section aria-labelledby="receipts-heading">
      <h2 id="receipts-heading" className="mb-3 text-lg font-medium">
        Kassenzettel
      </h2>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <label htmlFor={monthInputId} className="text-sm font-medium">
          Monat auswählen
        </label>
        <input
          id={monthInputId}
          type="month"
          min={FIRST_RECEIPT_MONTH}
          max={LAST_RECEIPT_MONTH}
          placeholder="JJJJ-MM"
          value={selectedMonth}
          onChange={(event) => setSelectedMonth(event.currentTarget.value)}
          aria-invalid={invalidMonth}
          aria-describedby={invalidMonth ? monthErrorId : undefined}
          className="rounded border border-gray-300 px-3 py-2 text-sm"
        />
        <button
          type="button"
          disabled={selectedMonth === ''}
          onClick={() => setSelectedMonth('')}
          className="rounded border border-gray-300 px-3 py-2 text-sm hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Alle Monate
        </button>
      </div>
      {invalidMonth && (
        <p id={monthErrorId} role="alert" className="text-sm text-red-600">
          Gib einen Monat von 0001-01 bis 9999-11 im Format JJJJ-MM ein.
        </p>
      )}

      {receipts.isPending && !invalidMonth && (
        <p role="status" className="text-sm text-gray-600">
          Kassenzettel werden geladen…
        </p>
      )}

      {(receipts.isError || receipts.data === null) && (
        <p role={receiptRows ? 'status' : 'alert'} className="text-sm text-red-600">
          {receiptRows
            ? 'Die Kassenzettel konnten nicht aktualisiert werden.'
            : 'Die Kassenzettel konnten nicht geladen werden.'}
        </p>
      )}

      {receiptRows?.length === 0 && (
        <p className="text-sm text-gray-500">
          {selectedMonth
            ? 'Keine Kassenzettel in diesem Monat.'
            : 'Noch keine Kassenzettel vorhanden.'}
        </p>
      )}

      {receiptRows && receiptRows.length > 0 && (
        <ul className="flex flex-col gap-2">
          {receiptRows.map((receipt) => {
            const store = receipt.store?.trim();
            const uploadedAt =
              !store || !receipt.purchase_date || receipt.total_rappen === null
                ? formatUploadTimestamp(receipt.created_at)
                : null;
            return (
              <li key={receipt.id}>
                <Link
                  to={`/households/${householdId}/receipts/${receipt.id}`}
                  className="flex flex-col gap-1 rounded border border-gray-200 px-4 py-3 hover:bg-gray-50 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="flex min-w-0 flex-col gap-0.5">
                    <span className="break-words font-medium">
                      {store || 'Geschäft nicht erkannt'}
                    </span>
                    <span className="text-sm text-gray-500">
                      <span className="sr-only">Kaufdatum: </span>
                      {receipt.purchase_date
                        ? formatDate(receipt.purchase_date)
                        : 'Kein Kaufdatum erkannt'}
                    </span>
                    {uploadedAt && (
                      <span className="text-sm text-gray-500">
                        Hochgeladen am <time dateTime={receipt.created_at}>{uploadedAt}</time>
                      </span>
                    )}
                    {receipt.possible_duplicate && (
                      <span className="self-start rounded bg-yellow-50 px-2 py-0.5 text-xs font-medium text-yellow-800">
                        Mögliches Duplikat
                      </span>
                    )}
                  </div>
                  <div className="flex shrink-0 flex-wrap items-center gap-3 sm:gap-4">
                    <span className="text-sm font-medium">
                      <span className="sr-only">Total: </span>
                      {formatRappen(receipt.total_rappen)}
                    </span>
                    <ReceiptStatusBadge status={receipt.status} />
                  </div>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

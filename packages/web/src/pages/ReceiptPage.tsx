import { HttpError } from '@oazapfts/runtime';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useLayoutEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router';
import {
  getReceipt,
  listCategories,
  type ReceiptCorrection,
  type ReceiptDetail,
  Status,
  updateReceipt
} from '@/api';
import { isPrivateResourceUnavailable, requestPrivateResource } from '@/api/privateQuery';
import {
  formatDate,
  formatRappen,
  isReceiptProcessing,
  RECEIPT_POLL_ERROR_INTERVAL,
  RECEIPT_POLL_INTERVAL
} from '@/api/receipts';
import { useSessionMutation, useSessionSignal } from '@/components/AuthenticatedSession';
import { ReceiptCorrectionForm } from '@/components/ReceiptCorrectionForm';
import { ReceiptOriginal } from '@/components/ReceiptOriginal';
import { ReceiptStatusBadge } from '@/components/ReceiptStatusBadge';
import {
  handleHouseholdAccessError,
  householdAccessKey
} from '@/features/households/householdAccess';
import { useHouseholdAccess } from '@/features/households/useHouseholdAccess';

function ReceiptItems({
  items,
  status,
  processing
}: Pick<ReceiptDetail, 'items' | 'status'> & { processing: boolean }) {
  if (items.length === 0) {
    return (
      <p className="text-sm text-gray-600">
        {processing && 'Die Verarbeitung läuft automatisch im Hintergrund.'}
        {!processing &&
          status === Status.Uploaded &&
          'Die automatische Aktualisierung ist beendet.'}
        {status !== Status.Uploaded && 'Keine Positionen vorhanden.'}
      </p>
    );
  }

  return (
    // biome-ignore lint/a11y/noNoninteractiveTabindex: keyboard users need to scroll the table on narrow screens
    <section className="overflow-x-auto" tabIndex={0} aria-label="Belegpositionen">
      <table className="w-full text-left text-sm">
        <thead className="text-gray-600">
          <tr>
            <th scope="col" className="p-2">
              Bezeichnung
            </th>
            <th scope="col" className="p-2 text-right">
              Menge
            </th>
            <th scope="col" className="p-2 text-right">
              Stückpreis
            </th>
            <th scope="col" className="p-2 text-right">
              Betrag
            </th>
            <th scope="col" className="p-2">
              Kategorie
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.position} className="border-t border-gray-200">
              <th scope="row" className="p-2 font-medium">
                {item.name || '–'}
              </th>
              <td className="p-2 text-right">{item.quantity}</td>
              <td className="whitespace-nowrap p-2 text-right">
                {formatRappen(item.unit_price_rappen)}
              </td>
              <td className="whitespace-nowrap p-2 text-right">
                {formatRappen(item.amount_rappen)}
              </td>
              <td className="p-2">{item.category || '–'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

class ReceiptItemsConflict extends Error {}

function correctionErrorMessage(error: Error) {
  if (error instanceof ReceiptItemsConflict) {
    return 'Die Positionen wurden inzwischen geändert. Dein Entwurf wurde nicht gespeichert.';
  }
  if (error instanceof HttpError) {
    switch (error.status) {
      case 401:
        return 'Deine Anmeldung ist abgelaufen. Melde dich erneut an.';
      case 403:
        return 'Du hast keinen Zugriff mehr auf diesen Kassenzettel.';
      case 404:
        return 'Dieser Kassenzettel ist nicht mehr verfügbar.';
      case 409:
        return 'Der Kassenzettel kann in seinem aktuellen Status nicht korrigiert werden.';
      case 422:
        return 'Die Korrekturen konnten nicht übernommen werden. Prüfe die Eingaben und Kategorien.';
    }
  }
  if (isPrivateResourceUnavailable(error))
    return 'Deine Anmeldung ist abgelaufen. Melde dich erneut an.';
  return 'Die Korrekturen konnten nicht gespeichert werden. Bitte versuche es erneut.';
}

export function ReceiptPage() {
  // biome-ignore lint/style/noNonNullAssertion: the route always has :householdId
  const householdId = useParams().householdId!;
  // biome-ignore lint/style/noNonNullAssertion: the route always has :receiptId
  const receiptId = useParams().receiptId!;
  return (
    <ReceiptContent
      key={`${householdId}/${receiptId}`}
      householdId={householdId}
      receiptId={receiptId}
    />
  );
}

function ReceiptContent({ householdId, receiptId }: { householdId: string; receiptId: string }) {
  const [editSnapshot, setEditSnapshot] = useState<ReceiptDetail | null>(null);
  const [renewing, setRenewing] = useState(false);
  const [originalRevision, setOriginalRevision] = useState(0);
  const renewingOriginal = useRef(false);
  const editing = editSnapshot !== null;
  const submitting = useRef(false);
  const editButton = useRef<HTMLButtonElement>(null);
  const restoreEditFocus = useRef(false);
  const queryClient = useQueryClient();
  const getSessionSignal = useSessionSignal();
  const detailKey = ['receipt', householdId, receiptId] as const;
  const accessKey = householdAccessKey(householdId);
  const [initialAccessVersion] = useState(
    () => queryClient.getQueryState(accessKey)?.dataUpdateCount ?? 0
  );
  const access = useHouseholdAccess(householdId);
  const accessVerified = Boolean(
    access.data &&
      access.isFetchedAfterMount &&
      (queryClient.getQueryState(accessKey)?.dataUpdateCount ?? 0) > initialAccessVersion
  );

  function handleReceiptDenial(error: unknown, signal: AbortSignal) {
    signal.throwIfAborted();
    if (error instanceof HttpError && error.status === 404) {
      // A missing receipt and loss of household membership both return 404.
      // Let the detail query clear its cached data without waiting for this check.
      void access.refetch({ cancelRefetch: false });
    } else {
      handleHouseholdAccessError(queryClient, householdId, error, signal);
    }
  }

  function getDetail(signal?: AbortSignal) {
    return requestPrivateResource(
      (options) => getReceipt({ householdId, receiptId }, options),
      signal
    );
  }

  const receipt = useQuery({
    queryKey: detailKey,
    queryFn: async ({ signal }) => {
      try {
        return await getDetail(signal);
      } catch (error) {
        if (!isPrivateResourceUnavailable(error)) throw error;
        handleReceiptDenial(error, signal);
        return null;
      }
    },
    enabled: accessVerified,
    retry: false,
    refetchIntervalInBackground: false,
    refetchInterval: ({ state }) => {
      if (!state.data || !isReceiptProcessing(state.data)) return false;
      return state.status === 'error' ? RECEIPT_POLL_ERROR_INTERVAL : RECEIPT_POLL_INTERVAL;
    }
  });

  const data = accessVerified ? receipt.data : undefined;
  const processing = Boolean(data && isReceiptProcessing(data));

  const categories = useQuery({
    queryKey: ['receiptCategories'],
    queryFn: ({ signal }) => requestPrivateResource((options) => listCategories(options), signal),
    enabled: editing && data?.status === Status.Done,
    staleTime: 5 * 60_000,
    retry: false
  });

  function isCurrentDetail(entry: object, signal: AbortSignal) {
    return (
      !signal.aborted &&
      Boolean(queryClient.getQueryData(accessKey)) &&
      queryClient.getQueryCache().find({ queryKey: detailKey, exact: true }) === entry &&
      Boolean(queryClient.getQueryData(detailKey))
    );
  }

  const save = useSessionMutation({
    mutationFn: async ({
      correction,
      originalItems,
      entry
    }: {
      correction: ReceiptCorrection;
      originalItems: ReceiptDetail['items'];
      entry: object;
    }) => {
      const signal = getSessionSignal();
      if (!isCurrentDetail(entry, signal))
        throw new DOMException('Receipt access changed', 'AbortError');
      if (correction.items !== undefined) {
        const latest = await getDetail();
        if (!isCurrentDetail(entry, signal))
          throw new DOMException('Receipt access changed', 'AbortError');
        if (
          latest.status !== Status.Done ||
          JSON.stringify(latest.items) !== JSON.stringify(originalItems)
        ) {
          await queryClient.cancelQueries({ queryKey: detailKey, exact: true });
          if (isCurrentDetail(entry, signal)) queryClient.setQueryData(detailKey, latest);
          throw new ReceiptItemsConflict();
        }
      }
      return requestPrivateResource((options) =>
        updateReceipt({ householdId, receiptId, receiptCorrection: correction }, options)
      );
    },
    retry: false,
    // Cancel reads before applying the PATCH result so an older GET cannot overwrite it.
    onSuccess: async (updated, { entry }) => {
      const signal = getSessionSignal();
      if (!isCurrentDetail(entry, signal)) return;
      await queryClient.cancelQueries({ queryKey: detailKey, exact: true });
      if (!isCurrentDetail(entry, signal)) return;
      queryClient.setQueryData(detailKey, updated);
      restoreEditFocus.current = true;
      setEditSnapshot(null);
      void queryClient.invalidateQueries({ queryKey: ['receipts', householdId] });
      // A date change may move the receipt between months, including the upload-date fallback.
      void queryClient.invalidateQueries({ queryKey: ['monthlyReport', householdId] });
      void queryClient.invalidateQueries({ queryKey: ['spendingTrend', householdId] });
    },
    onError: async (error, { entry }) => {
      const signal = getSessionSignal();
      if (error instanceof HttpError && error.status === 409) {
        void queryClient.invalidateQueries({ queryKey: detailKey, exact: true });
      }
      if (error instanceof HttpError && error.status === 422) {
        void queryClient.invalidateQueries({ queryKey: ['receiptCategories'] });
      }
      if (!isPrivateResourceUnavailable(error)) return;
      await queryClient.cancelQueries({ queryKey: detailKey, exact: true });
      if (!isCurrentDetail(entry, signal)) return;
      queryClient.setQueryData(detailKey, null);
      queryClient.removeQueries({ queryKey: ['receipts', householdId], type: 'inactive' });
      setEditSnapshot(null);
      handleReceiptDenial(error, signal);
    },
    onSettled: () => {
      submitting.current = false;
    }
  });

  function submitCorrection(correction: ReceiptCorrection) {
    const current = queryClient.getQueryData<ReceiptDetail | null>(detailKey);
    const entry = queryClient.getQueryCache().find({ queryKey: detailKey, exact: true });
    if (
      !editSnapshot ||
      !entry ||
      submitting.current ||
      current?.status !== Status.Done ||
      !categories.isSuccess
    )
      return;
    const signal = getSessionSignal();
    if (!isCurrentDetail(entry, signal)) return;
    submitting.current = true;
    save.mutate({ correction, originalItems: editSnapshot.items, entry });
  }

  function cancelCorrection() {
    if (submitting.current) return;
    save.reset();
    restoreEditFocus.current = true;
    setEditSnapshot(null);
  }

  useLayoutEffect(() => {
    if (!editing && restoreEditFocus.current) {
      editButton.current?.focus();
      restoreEditFocus.current = false;
    }
  }, [editing]);

  useLayoutEffect(() => {
    if (access.data === null || receipt.data === null) setEditSnapshot(null);
  }, [access.data, receipt.data]);

  const accessDenied = save.isError && isPrivateResourceUnavailable(save.error);
  const editAllowed = !accessDenied && data?.status === Status.Done;

  return (
    <main className="flex flex-col gap-6">
      <div>
        <Link to={`/households/${householdId}`} className="text-sm underline">
          Zur Haushaltsseite
        </Link>
        <h1 className="mt-2 text-2xl font-semibold">Kassenzettel</h1>
      </div>

      {access.data !== null && !access.isError && (!accessVerified || receipt.isPending) && (
        <p role="status">Kassenzettel wird geladen…</p>
      )}
      {!accessDenied && !accessVerified && (access.data === null || access.isError) && (
        <p role="alert" className="text-red-600">
          Der Zugriff auf diesen Haushalt konnte nicht bestätigt werden.
        </p>
      )}
      {!accessDenied && accessVerified && (receipt.isError || data === null) && (
        <p role={data ? 'status' : 'alert'} className="text-red-600">
          {data
            ? 'Der Kassenzettel konnte nicht aktualisiert werden.'
            : 'Der Kassenzettel konnte nicht geladen werden.'}
        </p>
      )}
      {save.isError && (
        <p role="alert" className="text-sm text-red-700">
          {correctionErrorMessage(save.error)}
          {save.error instanceof ReceiptItemsConflict && (
            <button type="button" className="mt-1 block underline" onClick={cancelCorrection}>
              Entwurf verwerfen und aktuellen Stand anzeigen
            </button>
          )}
        </p>
      )}
      {save.isSuccess && data && (
        <p role="status" className="text-sm text-green-700">
          Die Korrekturen wurden gespeichert.
        </p>
      )}
      {data && !accessDenied && (
        <>
          <dl className="grid grid-cols-2 gap-4 break-words rounded border border-gray-200 p-4 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-gray-600">Geschäft</dt>
              <dd>{data.store?.trim() || 'Nicht erkannt'}</dd>
            </div>
            <div>
              <dt className="text-gray-600">Kaufdatum</dt>
              <dd>
                {data.purchase_date ? formatDate(data.purchase_date) : 'Kein Kaufdatum erkannt'}
              </dd>
            </div>
            <div>
              <dt className="text-gray-600">Total</dt>
              <dd>{formatRappen(data.total_rappen)}</dd>
            </div>
            <div>
              <dt className="text-gray-600">Status</dt>
              <dd aria-live="polite">
                <ReceiptStatusBadge status={data.status} />
              </dd>
            </div>
            <div>
              <dt className="text-gray-600">Hochgeladen von</dt>
              <dd>{data.uploaded_by_name?.trim() || 'Unbekannt'}</dd>
            </div>
          </dl>

          {data.possible_duplicate && (
            <p className="rounded bg-yellow-50 p-3 text-sm text-yellow-800">
              Mögliches Duplikat: Ein anderer Beleg hat dasselbe Geschäft, Kaufdatum und Total.
            </p>
          )}

          <section aria-labelledby="receipt-image-heading">
            <h2 id="receipt-image-heading" className="mb-3 text-lg font-medium">
              Originalbeleg
            </h2>
            <ReceiptOriginal
              householdId={householdId}
              receiptId={receiptId}
              revision={originalRevision}
              url={data.image_url}
              processing={processing}
              renewing={renewing}
              onRenew={() => {
                if (renewingOriginal.current) return;
                renewingOriginal.current = true;
                setRenewing(true);
                const signal = getSessionSignal();
                void receipt.refetch({ cancelRefetch: false }).then((result) => {
                  if (signal.aborted) return;
                  if (result.isSuccess && result.data)
                    setOriginalRevision((current) => current + 1);
                  renewingOriginal.current = false;
                  setRenewing(false);
                });
              }}
            />
          </section>

          <section aria-labelledby="receipt-items-heading">
            <h2 id="receipt-items-heading" className="mb-3 text-lg font-medium">
              Positionen
            </h2>
            {editSnapshot ? (
              <>
                {categories.isPending && editAllowed && (
                  <p role="status" className="mb-3 text-sm text-gray-600">
                    Kategorien werden geladen…
                  </p>
                )}
                {categories.isError && editAllowed && (
                  <div className="mb-3 text-sm">
                    <p role="alert" className="text-red-700">
                      Die Kategorien konnten nicht geladen werden.
                    </p>
                    <button
                      type="button"
                      className="mt-1 underline"
                      onClick={() => void categories.refetch()}
                    >
                      Erneut laden
                    </button>
                  </div>
                )}
                {!editAllowed && (
                  <p role="status" className="mb-3 text-sm text-gray-600">
                    Der Kassenzettel kann in seinem aktuellen Status nicht gespeichert werden.
                  </p>
                )}
                <ReceiptCorrectionForm
                  receipt={editSnapshot}
                  categories={categories.data?.categories ?? []}
                  canSave={editAllowed && categories.isSuccess}
                  isSaving={save.isPending}
                  onSave={submitCorrection}
                  onCancel={cancelCorrection}
                />
              </>
            ) : (
              <>
                <ReceiptItems items={data.items} status={data.status} processing={processing} />
                {editAllowed && (
                  <button
                    ref={editButton}
                    type="button"
                    className="mt-4 rounded border px-4 py-2 text-sm"
                    onClick={() => {
                      save.reset();
                      setEditSnapshot(data);
                    }}
                  >
                    Kassenzettel korrigieren
                  </button>
                )}
              </>
            )}
          </section>
        </>
      )}
    </main>
  );
}

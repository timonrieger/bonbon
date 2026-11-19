import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useLayoutEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router';
import { createReceipt, getHousehold, listReceipts } from '@/api';
import { readPrivateResource } from '@/api/privateQuery';
import { formatBytes, prepareReceiptImage } from '@/api/receiptImage';
import {
  formatDate,
  formatRappen,
  formatUploadTimestamp,
  isReceiptProcessing,
  RECEIPT_POLL_ERROR_INTERVAL,
  RECEIPT_POLL_INTERVAL,
  uploadToS3
} from '@/api/receipts';
import { useUploadSignal } from '@/components/AuthenticatedSession';
import { ReceiptFilePicker } from '@/components/ReceiptFilePicker';
import { ReceiptStatusBadge } from '@/components/ReceiptStatusBadge';

export function HouseholdPage() {
  // biome-ignore lint/style/noNonNullAssertion: the route always has :householdId
  const householdId = useParams().householdId!;
  return <HouseholdContent key={householdId} householdId={householdId} />;
}

function HouseholdContent({ householdId }: { householdId: string }) {
  const queryClient = useQueryClient();
  const getUploadSignal = useUploadSignal();

  const household = useQuery({
    queryKey: ['household', householdId, 'receipt-page'],
    queryFn: ({ signal }) =>
      readPrivateResource((options) => getHousehold({ householdId }, options), signal)
  });

  const [file, setFile] = useState<File | null>(null);
  const [preparing, setPreparing] = useState(false);
  const preparation = useRef<AbortController | null>(null);
  const submitting = useRef(false);

  useLayoutEffect(() => {
    const controller = new AbortController();
    preparation.current = controller;
    return () => controller.abort();
  }, []);

  const upload = useMutation({
    mutationFn: async ({
      householdId,
      file,
      signal,
      preparationSignal
    }: {
      householdId: string;
      file: File;
      signal: AbortSignal;
      preparationSignal: AbortSignal;
    }) => {
      const prepared = await prepareReceiptImage(file, preparationSignal);
      preparationSignal.throwIfAborted();
      setPreparing(false);

      // Sign the exact MIME type and size of the file sent to S3.
      const receiptUpload = await createReceipt(
        {
          householdId,
          createReceiptRequest: {
            content_type: prepared.contentType,
            size_bytes: prepared.file.size
          }
        },
        { signal }
      );

      // Step 2: unauthenticated PUT — send raw bytes to S3 with all backend-supplied headers.
      signal.throwIfAborted();
      await uploadToS3(receiptUpload, prepared.file, signal);
      return { completedAt: Date.now(), originalSize: file.size, uploadedSize: prepared.file.size };
    },
    onSettled: () => {
      submitting.current = false;
      setPreparing(false);
    },
    onSuccess: (_, { householdId }) => {
      setFile(null);
      void queryClient.invalidateQueries({ queryKey: ['receipts', householdId] });
    }
  });

  const receipts = useQuery({
    queryKey: ['receipts', householdId],
    queryFn: ({ signal }) =>
      readPrivateResource((options) => listReceipts({ householdId }, options), signal),
    enabled: Boolean(household.data),
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
        upload.data !== undefined &&
        state.dataUpdatedAt < upload.data.completedAt &&
        Date.now() - upload.data.completedAt < 60_000;

      if (!processing && !recoveringAfterUpload) return false;
      return refreshFailed ? RECEIPT_POLL_ERROR_INTERVAL : RECEIPT_POLL_INTERVAL;
    }
  });

  function handleUpload() {
    if (!file || !preparation.current || submitting.current || upload.isPending) return;

    const signal = getUploadSignal();
    submitting.current = true;
    setPreparing(true);
    upload.mutate({
      householdId,
      file,
      signal,
      preparationSignal: AbortSignal.any([signal, preparation.current.signal])
    });
  }

  function handleFileChange(next: File | null) {
    upload.reset();
    setFile(next);
  }

  if (household.isPending) return <p>Laden…</p>;
  if (!household.data) {
    return (
      <p role="alert" className="text-red-600">
        Der Haushalt konnte nicht geladen werden.
      </p>
    );
  }

  const receiptRows = receipts.data?.receipts;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold">{household.data.name}</h1>
        {household.isError && (
          <p role="status" className="text-sm text-red-600">
            Der Haushalt konnte nicht aktualisiert werden.
          </p>
        )}
        <p className="text-sm text-gray-600">Deine Rolle: {household.data.my_role}</p>
        <Link
          to={`/households/${householdId}/dashboard`}
          className="mt-2 inline-block text-sm underline"
        >
          Zum Dashboard
        </Link>
      </div>

      <section aria-labelledby="upload-heading">
        <h2 id="upload-heading" className="mb-3 text-lg font-medium">
          Kassenzettel hochladen
        </h2>

        <ReceiptFilePicker file={file} onChange={handleFileChange} disabled={upload.isPending} />

        {file && (
          <button
            type="button"
            onClick={handleUpload}
            disabled={upload.isPending}
            className="mt-3 w-full rounded bg-black px-4 py-2 text-sm text-white sm:w-auto disabled:opacity-50"
          >
            {upload.isPending ? 'Upload läuft…' : 'Hochladen'}
          </button>
        )}

        {upload.isPending && (
          <p role="status" className="mt-2 text-sm text-gray-600">
            {upload.isPaused
              ? 'Der Upload wartet auf eine Verbindung.'
              : preparing
                ? 'Das Bild wird vorbereitet…'
                : 'Der Kassenzettel wird hochgeladen…'}
          </p>
        )}

        {upload.isSuccess && (
          <p role="status" className="mt-2 text-sm text-green-700">
            Kassenzettel erfolgreich hochgeladen. Die Verarbeitung läuft automatisch im Hintergrund.
            {upload.data.uploadedSize < upload.data.originalSize && (
              <span className="block">
                Bildgrösse von {formatBytes(upload.data.originalSize)} auf{' '}
                {formatBytes(upload.data.uploadedSize)} reduziert.
              </span>
            )}
          </p>
        )}

        {upload.isError && (
          <p role="alert" className="mt-2 text-sm text-red-600">
            {upload.error.message}
          </p>
        )}
      </section>

      <section aria-labelledby="receipts-heading">
        <h2 id="receipts-heading" className="mb-3 text-lg font-medium">
          Kassenzettel
        </h2>

        {receipts.isPending && (
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
          <p className="text-sm text-gray-500">Noch keine Kassenzettel vorhanden.</p>
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
                        {formatDate(receipt.purchase_date)}
                      </span>
                      {uploadedAt && (
                        <span className="text-sm text-gray-500">
                          Hochgeladen am <time dateTime={receipt.created_at}>{uploadedAt}</time>
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
    </div>
  );
}

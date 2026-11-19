import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useParams } from 'react-router';
import { getReceipt, type ReceiptDetail, Status } from '@/api';
import { readPrivateResource } from '@/api/privateQuery';
import {
  formatDate,
  formatRappen,
  isReceiptProcessing,
  RECEIPT_POLL_ERROR_INTERVAL,
  RECEIPT_POLL_INTERVAL
} from '@/api/receipts';
import { ReceiptStatusBadge } from '@/components/ReceiptStatusBadge';

function isPreviewUrl(url: string): boolean {
  return URL.canParse(url) && new URL(url).protocol === 'https:';
}

function ReceiptImage({
  url,
  processing
}: {
  url: ReceiptDetail['image_url'];
  processing: boolean;
}) {
  const [initialUrl] = useState(url);
  const [loadedUrl, setLoadedUrl] = useState<string>();
  const [failedUrl, setFailedUrl] = useState<string>();
  // A poll can issue a fresh signature for the same file. Keep a loaded preview.
  const previewUrl = loadedUrl ?? (processing ? initialUrl : url);

  if (!isPreviewUrl(url)) {
    return <p className="text-sm text-gray-600">Der Originalbeleg ist nicht verfügbar.</p>;
  }

  return (
    <div className="flex flex-col items-start gap-2">
      {failedUrl === previewUrl || !isPreviewUrl(previewUrl) ? (
        <p className="text-sm text-gray-600">Die Vorschau ist nicht verfügbar.</p>
      ) : (
        <img
          src={previewUrl}
          alt="Original des Kassenzettels"
          referrerPolicy="no-referrer"
          onLoad={() => setLoadedUrl(previewUrl)}
          onError={() => setFailedUrl(previewUrl)}
          className="max-h-[36rem] max-w-full rounded object-contain"
        />
      )}
      <a href={url} target="_blank" rel="noopener noreferrer" className="text-sm underline">
        Original öffnen <span className="sr-only">(neuer Tab)</span>
      </a>
    </div>
  );
}

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

export function ReceiptPage() {
  // biome-ignore lint/style/noNonNullAssertion: the route always has :householdId
  const householdId = useParams().householdId!;
  // biome-ignore lint/style/noNonNullAssertion: the route always has :receiptId
  const receiptId = useParams().receiptId!;
  const receipt = useQuery({
    queryKey: ['receipt', householdId, receiptId],
    queryFn: ({ signal }) =>
      readPrivateResource((options) => getReceipt({ householdId, receiptId }, options), signal),
    retry: false,
    refetchIntervalInBackground: false,
    refetchInterval: ({ state }) => {
      if (!state.data || !isReceiptProcessing(state.data)) return false;
      return state.status === 'error' ? RECEIPT_POLL_ERROR_INTERVAL : RECEIPT_POLL_INTERVAL;
    }
  });

  const data = receipt.data;
  const processing = Boolean(data && isReceiptProcessing(data));

  return (
    <main className="flex flex-col gap-6">
      <div>
        <Link to={`/households/${householdId}`} className="text-sm underline">
          Zur Haushaltsseite
        </Link>
        <h1 className="mt-2 text-2xl font-semibold">Kassenzettel</h1>
      </div>

      {receipt.isPending && <p role="status">Kassenzettel wird geladen…</p>}
      {(receipt.isError || data === null) && (
        <p role={data ? 'status' : 'alert'} className="text-red-600">
          {data
            ? 'Der Kassenzettel konnte nicht aktualisiert werden.'
            : 'Der Kassenzettel konnte nicht geladen werden.'}
        </p>
      )}
      {data && (
        <>
          <dl className="grid grid-cols-2 gap-4 break-words rounded border border-gray-200 p-4 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-gray-600">Geschäft</dt>
              <dd>{data.store?.trim() || 'Nicht erkannt'}</dd>
            </div>
            <div>
              <dt className="text-gray-600">Kaufdatum</dt>
              <dd>{formatDate(data.purchase_date)}</dd>
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
            <ReceiptImage
              key={`${householdId}/${receiptId}`}
              url={data.image_url}
              processing={processing}
            />
          </section>

          <section aria-labelledby="receipt-items-heading">
            <h2 id="receipt-items-heading" className="mb-3 text-lg font-medium">
              Positionen
            </h2>
            <ReceiptItems items={data.items} status={data.status} processing={processing} />
          </section>
        </>
      )}
    </main>
  );
}

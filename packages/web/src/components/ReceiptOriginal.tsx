import { useQuery } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { ContentType, type ReceiptDetail } from '@/api';
import { useSessionSignal } from '@/components/AuthenticatedSession';

function isOriginalUrl(url: string): boolean {
  if (!URL.canParse(url)) return false;
  const { protocol, hostname, username, password, port } = new URL(url);
  return (
    protocol === 'https:' &&
    !username &&
    !password &&
    !port &&
    /^(?:[\w.-]+\.)?s3(?:[.-][a-z0-9-]+)?\.amazonaws\.com$/.test(hostname)
  );
}

async function probeOriginal(
  url: string,
  signal: AbortSignal
): Promise<ContentType | 'unclassified' | null> {
  if (!isOriginalUrl(url)) return null;
  const response = await fetch(url, {
    headers: { Range: 'bytes=0-0' },
    credentials: 'omit',
    cache: 'no-store',
    referrerPolicy: 'no-referrer',
    redirect: 'error',
    signal
  });
  // A server may ignore Range. The response headers are sufficient, so never read its body.
  void response.body?.cancel().catch(() => {});
  signal.throwIfAborted();
  if (!response.ok) throw new Error('Original document unavailable');
  const type = response.headers.get('content-type')?.split(';')[0].trim().toLowerCase();
  if (!type || type === 'application/octet-stream') return 'unclassified';
  return type === ContentType.ApplicationPdf ||
    type === ContentType.ImageJpeg ||
    type === ContentType.ImagePng
    ? type
    : null;
}

function ReceiptImage({ url, processing }: { url: string; processing: boolean }) {
  const [initialUrl] = useState(url);
  const [loadedUrl, setLoadedUrl] = useState<string>();
  const [failedUrl, setFailedUrl] = useState<string>();
  const previewUrl = loadedUrl ?? (processing ? initialUrl : url);
  if (failedUrl === previewUrl || !isOriginalUrl(previewUrl)) {
    return (
      <p role="status" className="text-sm text-gray-600">
        Die Vorschau ist nicht verfügbar.
      </p>
    );
  }
  return (
    <img
      src={previewUrl}
      alt="Original des Kassenzettels"
      referrerPolicy="no-referrer"
      onLoad={() => setLoadedUrl(previewUrl)}
      onError={() => setFailedUrl(previewUrl)}
      className="max-h-[36rem] max-w-full rounded object-contain"
    />
  );
}

function ReceiptPdfFrame({ url }: { url: string }) {
  // Keep the viewer open when a receipt poll rotates its presigned URL.
  const [previewUrl] = useState(url);
  if (!navigator.pdfViewerEnabled) {
    return <p className="text-sm text-gray-600">Öffne das PDF in einem neuen Tab.</p>;
  }
  return (
    <iframe
      src={previewUrl}
      title="PDF-Vorschau des Kassenzettels"
      referrerPolicy="no-referrer"
      className="h-[65vh] min-h-64 w-full rounded border border-gray-200"
    />
  );
}

export function ReceiptOriginal({
  householdId,
  receiptId,
  revision,
  url,
  processing,
  renewing,
  onRenew
}: {
  householdId: string;
  receiptId: string;
  revision: number;
  url: ReceiptDetail['image_url'];
  processing: boolean;
  renewing: boolean;
  onRenew: () => void;
}) {
  const getSessionSignal = useSessionSignal();
  const {
    data: type,
    isPending,
    isError,
    refetch
  } = useQuery({
    queryKey: ['receipt', householdId, receiptId, 'originalType', revision],
    queryFn: ({ signal }) => probeOriginal(url, AbortSignal.any([signal, getSessionSignal()])),
    gcTime: 0,
    staleTime: Infinity,
    retry: false,
    networkMode: 'always',
    refetchOnWindowFocus: false,
    refetchOnReconnect: false
  });
  const retryAfterProcessing = useRef<number>(undefined);

  useEffect(() => {
    if (processing) retryAfterProcessing.current = revision;
    else if (retryAfterProcessing.current === revision && isError) {
      retryAfterProcessing.current = undefined;
      void refetch();
    }
  }, [processing, isError, refetch, revision]);

  return (
    <div className="flex flex-col items-start gap-2">
      <div role="status" className="text-sm text-gray-600">
        {isPending && 'Das Original wird geladen…'}
        {type === null && 'Die Vorschau ist nicht verfügbar.'}
      </div>
      {isOriginalUrl(url) && type === ContentType.ApplicationPdf && (
        <ReceiptPdfFrame key={revision} url={url} />
      )}
      {isOriginalUrl(url) &&
        (isError ||
          type === 'unclassified' ||
          type === ContentType.ImageJpeg ||
          type === ContentType.ImagePng) && (
          <ReceiptImage key={revision} url={url} processing={processing} />
        )}
      <div className="flex flex-wrap gap-x-4 gap-y-2 text-sm">
        {isOriginalUrl(url) && (
          <a href={url} target="_blank" rel="noopener noreferrer" className="underline">
            {type === ContentType.ApplicationPdf ? 'PDF öffnen' : 'Original öffnen'}{' '}
            <span className="sr-only">(neuer Tab)</span>
          </a>
        )}
        <button
          type="button"
          aria-disabled={renewing}
          onClick={onRenew}
          className="underline aria-disabled:opacity-50"
        >
          {renewing ? 'Link wird erneuert…' : 'Original-Link erneuern'}
        </button>
      </div>
    </div>
  );
}

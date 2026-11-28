import { ContentType } from '@/api';
import { formatBytes, MAX_UPLOAD_BYTES } from './receiptImage';

export function isPdfCandidate(file: File): boolean {
  return file.type === ContentType.ApplicationPdf || file.name.toLowerCase().endsWith('.pdf');
}

export async function validateReceiptPdf(file: File, signal: AbortSignal): Promise<void> {
  signal.throwIfAborted();
  if (
    file.type &&
    file.type !== ContentType.ApplicationPdf &&
    file.type !== 'application/octet-stream'
  ) {
    throw new Error('Dateityp und PDF-Dateiendung passen nicht zusammen.');
  }
  if (!file.size) throw new Error('Die PDF-Datei ist leer.');
  if (file.size > MAX_UPLOAD_BYTES) {
    throw new Error(
      `Das PDF ist zu gross (${formatBytes(file.size)}). Erlaubt sind höchstens 5 MB.`
    );
  }

  // Vite bundles the parser in this worker, which is loaded only for a PDF selection.
  let worker: Worker;
  try {
    worker = new Worker(new URL('./receiptPdf.worker.ts', import.meta.url), { type: 'module' });
  } catch {
    throw new Error('Die PDF-Prüfung konnte nicht gestartet werden.');
  }
  let timeout: ReturnType<typeof setTimeout> | undefined;
  let abort: (() => void) | undefined;
  try {
    await new Promise<void>((resolve, reject) => {
      abort = () => reject(signal.reason);
      signal.addEventListener('abort', abort, { once: true });
      timeout = setTimeout(
        () => reject(new Error('Die PDF-Prüfung dauert zu lange. Bitte wähle ein anderes PDF.')),
        10_000
      );
      worker.onmessage = ({ data }: MessageEvent<string | null>) => {
        if (data === null) resolve();
        else reject(new Error(data));
      };
      worker.onerror = (event) => {
        event.preventDefault();
        reject(new Error('Die PDF-Prüfung konnte nicht gestartet werden.'));
      };
      worker.postMessage(file);
    });
  } finally {
    worker.terminate();
    clearTimeout(timeout);
    if (abort) signal.removeEventListener('abort', abort);
  }
}

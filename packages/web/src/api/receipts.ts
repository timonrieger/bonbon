/**
 * Receipt helpers that the generated client in @/api doesn't cover.
 *
 * See docs/features/01-upload-processing.md.
 */

import { type ReceiptSummary, type ReceiptUpload, Status } from '@/api';

export const RECEIPT_POLL_INTERVAL = 3_000;
export const RECEIPT_POLL_ERROR_INTERVAL = 15_000;
const ABANDONED_UPLOAD_AGE = 30 * 60_000;

export function isReceiptProcessing(
  receipt: Pick<ReceiptSummary, 'status' | 'created_at'>,
  graceMs = 0
): boolean {
  return (
    receipt.status === Status.Uploaded &&
    Date.now() < Date.parse(receipt.created_at) + ABANDONED_UPLOAD_AGE + graceMs
  );
}

const chf = new Intl.NumberFormat('de-CH', { style: 'currency', currency: 'CHF' });
const uploadTimestamp = new Intl.DateTimeFormat('de-CH', {
  dateStyle: 'medium',
  timeStyle: 'medium',
  timeZone: 'Europe/Zurich'
});

export function formatUploadTimestamp(isoTimestamp: string): string | null {
  const date = new Date(isoTimestamp);
  return Number.isNaN(date.getTime()) ? null : uploadTimestamp.format(date);
}

/** Format an amount in Rappen as Swiss francs. */
export function formatRappen(rappen: number | null): string {
  if (rappen === null) return '–';
  return chf.format(rappen / 100);
}

/**
 * Format an ISO date string (YYYY-MM-DD) for display in Swiss German.
 * Returns '–' for null or undefined.
 */
export function formatDate(isoDate: string | null | undefined): string {
  if (!isoDate) return '–';
  const date = new Date(`${isoDate}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return '–';
  return new Intl.DateTimeFormat('de-CH', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    timeZone: 'UTC'
  }).format(date);
}

/**
 * Upload a file directly to S3 using the presigned PUT URL from createReceipt.
 *
 * S3 presigned URLs must NOT carry an Authorization header — the credentials
 * are already embedded in the URL as query parameters. Plain `fetch` is used
 * intentionally here (no defaults.fetch, no Cognito token).
 *
 * All headers returned by the backend in `upload_headers` (including
 * `x-amz-tagging` and any others) are forwarded verbatim. The backend is
 * the authority on what S3 expects; we do not add or override anything.
 *
 * @throws {Error} when the PUT does not return 200.
 */
export async function uploadToS3(
  upload: ReceiptUpload,
  file: File,
  signal: AbortSignal
): Promise<void> {
  const response = await fetch(upload.upload_url, {
    method: 'PUT',
    headers: upload.upload_headers,
    body: file,
    signal
  });

  if (!response.ok) {
    throw new Error(`Upload fehlgeschlagen (${response.status}). Bitte versuche es erneut.`);
  }
}

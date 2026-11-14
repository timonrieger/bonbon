/**
 * Receipt helpers.
 *
 * createReceipt is now generated in client.gen.ts and re-exported from @/api.
 * This file keeps the S3 upload helper and the correction-form types.
 *
 * See docs/features/01-upload-processing.md for the full planned flow.
 */
import type { ReceiptItem } from '@/api';

// ---------------------------------------------------------------------------
// Correction types
// ---------------------------------------------------------------------------

/**
 * An editable snapshot of one receipt item (form state of ReceiptCorrectionForm).
 * Numeric fields are strings so HTML inputs don't lose the user's partial input
 * mid-edit; prices are in CHF (e.g. "1.50"), not Rappen.
 */
export interface ReceiptItemDraft {
  position: number; // read-only; identifies the item
  name: string;
  quantity: string;
  unit_price_chf: string; // empty string means null
  amount_chf: string; // required
  category: string;
}

/**
 * Editable header fields of a receipt (ReceiptDetail top-level fields).
 * `total_rappen`, `status`, `image_url`, `created_at`, `uploaded_by_name`
 * are read-only and not part of the draft.
 */
export interface ReceiptDraft {
  store: string; // empty string means null in the DB
  purchase_date: string; // ISO date string "YYYY-MM-DD", empty means null
  items: ReceiptItemDraft[];
}

/**
 * A validated correction, converted back to the API's units (Rappen, numbers, null).
 *
 * TODO: replace with the generated PATCH request type once
 *       PATCH /households/{id}/receipts/{id} exists and `mise run generate` ran.
 */
export interface ReceiptCorrection {
  store: string | null;
  purchase_date: string | null;
  items: ReceiptItem[];
}

/** Callback for ReceiptCorrectionForm's onSave prop; the parent issues the PATCH request. */
export type SaveReceiptCorrection = (correction: ReceiptCorrection) => void;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Convert Rappen (integer) to a display string "CHF 12.50". */
export function formatRappen(rappen: number | null): string {
  if (rappen === null) return '–';
  return `CHF\u00a0${(rappen / 100).toFixed(2)}`;
}

/**
 * Upload a file directly to S3 using a presigned PUT URL.
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
  uploadUrl: string,
  uploadHeaders: Record<string, string>,
  file: File
): Promise<void> {
  const response = await fetch(uploadUrl, {
    method: 'PUT',
    headers: uploadHeaders,
    body: file
  });

  if (!response.ok) {
    throw new Error(`Upload fehlgeschlagen (${response.status}). Bitte versuche es erneut.`);
  }
}

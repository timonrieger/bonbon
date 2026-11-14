/**
 * Receipt helpers.
 *
 * createReceipt is now generated in client.gen.ts and re-exported from @/api.
 * This file keeps the S3 upload helper and the correction-form types.
 *
 * See docs/features/01-upload-processing.md for the full planned flow.
 */

// ---------------------------------------------------------------------------
// Correction types
// ---------------------------------------------------------------------------

/**
 * An editable snapshot of one receipt item.
 * Mirrors ReceiptItem from the contract branch (feat/receipts-reports-contract),
 * but with `position` omitted (read-only display only) and all numeric fields as
 * strings so HTML inputs don't lose the user's partial input mid-edit.
 *
 * TODO: once GET /households/{id}/receipts/{id} returns real data and a PATCH
 *       endpoint exists, align with the generated types from client.gen.ts.
 */
export interface ReceiptItemDraft {
  position: number; // read-only; identifies the item
  name: string;
  quantity: string; // number stored as string for <input> editing
  unit_price_rappen: string; // empty string means null
  amount_rappen: string; // required; must be a positive integer
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
 * Callback type for the ReceiptCorrectionForm's onSave prop.
 *
 * The parent is responsible for the actual PATCH request once
 * PATCH /households/{id}/receipts/{id} exists.
 * Until then, the button that triggers this remains disabled.
 *
 * TODO: replace `ReceiptDraft` with the generated PATCH request type
 *       after `mise run generate`.
 */
export type SaveReceiptDraft = (draft: ReceiptDraft) => void;

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

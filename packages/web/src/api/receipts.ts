/**
 * Receipt upload API – typed interface for Noel's proposed contract.
 *
 * NOT using the generated client (client.gen.ts) because
 * POST /households/{household_id}/receipts does not exist in the backend yet.
 * Once the endpoint is implemented and `mise run generate` is run, replace
 * createReceipt with the generated function and delete this file.
 *
 * API contract (proposed by @Dam-Mil, 2026-11):
 *
 *   POST /households/{household_id}/receipts
 *   Body:  { content_type: "image/jpeg"|"image/png", size_bytes: number }
 *   → 201 { receipt_id: string, upload_url: string, expires_in: 300 }
 *
 *   PUT {upload_url}
 *   Headers: Content-Type: <same content_type>
 *   Body: raw file bytes
 *   → 200 (S3 direct, no auth header)
 *
 * See docs/features/01-upload-processing.md for the full planned flow.
 */
import { defaults } from '@/api';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** MIME types accepted for receipt uploads. */
export type ReceiptContentType = 'image/jpeg' | 'image/png';

/** Request body for POST /households/{household_id}/receipts. */
export interface CreateReceiptRequest {
  content_type: ReceiptContentType;
  size_bytes: number;
}

/** Response from POST /households/{household_id}/receipts (HTTP 201). */
export interface CreateReceiptResponse {
  receipt_id: string;
  /** S3 presigned PUT URL. Valid for `expires_in` seconds. No auth header allowed. */
  upload_url: string;
  /** Seconds until the presigned URL expires. */
  expires_in: number;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/**
 * Request a presigned S3 upload URL from the API.
 *
 * Uses the same authenticated fetch wrapper as the generated client
 * (via `defaults.fetch`), so the Cognito ID token is included automatically.
 *
 * @throws {Error} when the server returns a non-2xx status.
 *
 * TODO: replace with the generated `createReceipt` once the backend is deployed
 *       and `mise run generate` has been run.
 */
export async function createReceipt(
  householdId: string,
  req: CreateReceiptRequest
): Promise<CreateReceiptResponse> {
  const url = `${defaults.baseUrl}/households/${encodeURIComponent(householdId)}/receipts`;

  // defaults.fetch is patched in api/index.ts to inject the Cognito ID token.
  const fetcher = defaults.fetch ?? fetch;
  const response = await fetcher(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req)
  });

  if (!response.ok) {
    const text = await response.text().catch(() => '');
    throw new Error(
      `Fehler beim Anfordern der Upload-URL (${response.status})${text ? `: ${text}` : ''}.`
    );
  }

  return response.json() as Promise<CreateReceiptResponse>;
}

/**
 * Upload a file directly to S3 using a presigned PUT URL.
 *
 * S3 presigned URLs must NOT carry an Authorization header – the credentials
 * are already embedded in the URL as query parameters. A plain `fetch` is used
 * here intentionally (no defaults.fetch, no Cognito token).
 *
 * @throws {Error} when the PUT does not return 200.
 */
export async function uploadToS3(uploadUrl: string, file: File): Promise<void> {
  const response = await fetch(uploadUrl, {
    method: 'PUT',
    headers: { 'Content-Type': file.type },
    body: file
  });

  if (!response.ok) {
    throw new Error(`Upload fehlgeschlagen (${response.status}). Bitte versuche es erneut.`);
  }
}

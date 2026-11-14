/**
 * Receipt helpers that the generated client in @/api doesn't cover.
 *
 * See docs/features/01-upload-processing.md.
 */

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

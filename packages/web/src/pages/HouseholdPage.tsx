import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useParams } from 'react-router';
import { getHousehold } from '@/api';
import type { ReceiptContentType } from '@/api/receipts';
import { ReceiptUpload } from '@/components/ReceiptUpload';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * Everything the upload flow needs once it is wired up:
 *   1. POST /households/{id}/receipts  →  createReceipt(householdId, { content_type, size_bytes })
 *   2. PUT {upload_url}                →  uploadToS3(upload_url, file)
 *   3. Poll GET /households/{id}/receipts/{receipt_id} until status ≠ "uploaded|processing"
 *
 * See docs/features/01-upload-processing.md and src/api/receipts.ts.
 */
interface PendingUpload {
  file: File;
  content_type: ReceiptContentType;
  size_bytes: number;
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function HouseholdPage() {
  // biome-ignore lint/style/noNonNullAssertion: the route always has :householdId
  const householdId = useParams().householdId!;
  const household = useQuery({
    queryKey: ['household', householdId],
    queryFn: () => getHousehold({ householdId })
  });

  /**
   * Holds the validated file until the user clicks "Hochladen".
   * Null when no file is selected or after a successful upload.
   *
   * The upload action itself (createReceipt + uploadToS3) is not yet wired up:
   * POST /households/{id}/receipts does not exist in the backend.
   * When it does, replace the disabled button below with a useMutation call.
   */
  const [pending, setPending] = useState<PendingUpload | null>(null);

  function handleFileReady(file: File | null) {
    if (!file) {
      setPending(null);
      return;
    }
    setPending({
      file,
      // ReceiptUpload already validated the type; cast is safe.
      content_type: file.type as ReceiptContentType,
      size_bytes: file.size
    });
  }

  if (household.isPending) return <p>Laden…</p>;
  if (household.isError) return <p className="text-red-600">{household.error.message}</p>;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold">{household.data.name}</h1>
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

        <ReceiptUpload onFileReady={handleFileReady} />

        {/*
         * Upload button – shown once a file is selected.
         *
         * Stays disabled until POST /households/{id}/receipts is implemented.
         * To wire up: remove `disabled`, add onClick that calls
         *   createReceipt(householdId, { content_type, size_bytes })
         *   then uploadToS3(upload_url, file)
         * Both are ready in src/api/receipts.ts.
         */}
        {pending && (
          <button
            type="button"
            disabled
            className="mt-3 w-full rounded bg-black px-4 py-2 text-sm text-white opacity-50 sm:w-auto"
            title="Upload-Funktion wird demnächst verfügbar"
          >
            Hochladen
          </button>
        )}

        {pending && (
          <p className="mt-2 text-xs text-gray-500">
            Der Upload wird verfügbar, sobald die Funktion fertiggestellt ist.
          </p>
        )}
      </section>
    </div>
  );
}

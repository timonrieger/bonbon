import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useParams } from 'react-router';
import { type ContentType, createReceipt, getHousehold } from '@/api';
import { uploadToS3 } from '@/api/receipts';
import { ReceiptUpload } from '@/components/ReceiptUpload';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface PendingUpload {
  file: File;
  content_type: ContentType;
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

  const [pending, setPending] = useState<PendingUpload | null>(null);

  const upload = useMutation({
    mutationFn: async (p: PendingUpload) => {
      // Step 1: authenticated POST — get presigned URL + headers from the backend.
      const { receipt_id, upload_url, upload_headers } = await createReceipt({
        householdId,
        createReceiptRequest: {
          content_type: p.content_type,
          size_bytes: p.size_bytes
        }
      });

      // Step 2: unauthenticated PUT — send raw bytes to S3 with all backend-supplied headers.
      await uploadToS3(upload_url, upload_headers, p.file);

      return receipt_id;
    },
    onSuccess: () => {
      setPending(null);
    }
  });

  function handleFileReady(file: File | null) {
    upload.reset();
    if (!file) {
      setPending(null);
      return;
    }
    setPending({
      file,
      // ReceiptUpload already validated the type; cast is safe.
      content_type: file.type as ContentType,
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

        <ReceiptUpload onFileReady={handleFileReady} disabled={upload.isPending} />

        {pending && (
          <button
            type="button"
            onClick={() => upload.mutate(pending)}
            disabled={upload.isPending}
            className="mt-3 w-full rounded bg-black px-4 py-2 text-sm text-white sm:w-auto disabled:opacity-50"
          >
            {upload.isPending ? 'Wird hochgeladen…' : 'Hochladen'}
          </button>
        )}

        {upload.isSuccess && (
          <p role="status" className="mt-2 text-sm text-green-700">
            Kassenzettel erfolgreich hochgeladen. Er wird jetzt verarbeitet.
          </p>
        )}

        {upload.isError && (
          <p role="alert" className="mt-2 text-sm text-red-600">
            {upload.error instanceof Error
              ? upload.error.message
              : 'Upload fehlgeschlagen. Bitte versuche es erneut.'}
          </p>
        )}
      </section>
    </div>
  );
}

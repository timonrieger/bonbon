import { ReceiptFilePicker } from '@/components/ReceiptFilePicker';
import { ReceiptProcessingNotice } from '@/components/ReceiptProcessingNotice';
import { formatBytes } from '@/features/receipts/receiptImage';
import type { useReceiptUpload } from '@/features/receipts/useReceiptUpload';

export function ReceiptUploadSection({
  householdId,
  disabled,
  workflow
}: {
  householdId: string;
  disabled: boolean;
  workflow: ReturnType<typeof useReceiptUpload>;
}) {
  const {
    file,
    fileError,
    validatingPdf,
    preparing,
    upload,
    trackedUploads,
    handleUpload,
    handleFileChange
  } = workflow;

  return (
    <section aria-labelledby="upload-heading">
      <h2 id="upload-heading" className="mb-3 text-lg font-medium">
        Kassenzettel hochladen
      </h2>

      <ReceiptFilePicker
        file={file}
        onChange={(next) => void handleFileChange(next)}
        disabled={disabled}
        error={fileError}
        validating={validatingPdf}
      />

      {file && (
        <button
          type="button"
          onClick={handleUpload}
          disabled={disabled || validatingPdf || Boolean(fileError)}
          className="mt-3 w-full rounded bg-black px-4 py-2 text-sm text-white sm:w-auto disabled:opacity-50"
        >
          {upload.isPending ? 'Upload läuft…' : 'Hochladen'}
        </button>
      )}

      {upload.isPending && (
        <p role="status" className="mt-2 text-sm text-gray-600">
          {upload.isPaused
            ? 'Der Upload wartet auf eine Verbindung.'
            : preparing
              ? 'Das Bild wird vorbereitet…'
              : 'Der Kassenzettel wird hochgeladen…'}
        </p>
      )}

      {upload.isSuccess && (
        <p role="status" className="mt-2 text-sm text-green-700">
          Kassenzettel erfolgreich hochgeladen.
          {upload.data.uploadedSize < upload.data.originalSize && (
            <span className="block">
              Bildgrösse von {formatBytes(upload.data.originalSize)} auf{' '}
              {formatBytes(upload.data.uploadedSize)} reduziert.
            </span>
          )}
        </p>
      )}

      {upload.isError && (
        <p role="alert" className="mt-2 text-sm text-red-600">
          {upload.error.message}
        </p>
      )}
      {trackedUploads.map(({ id, uploadedAt }) => (
        <ReceiptProcessingNotice
          key={id}
          householdId={householdId}
          receiptId={id}
          uploadedAt={uploadedAt}
        />
      ))}
    </section>
  );
}

/**
 * ReceiptFilePicker – file selection and validation for receipt photos.
 *
 * Controlled: the parent owns the selected file and does the upload.
 * See docs/features/01-upload-processing.md.
 */
import { useId } from 'react';
import { ContentType } from '@/api';
import { formatBytes, RECEIPT_IMAGE_TYPES } from '@/features/receipts/receiptImage';

interface ReceiptFilePickerProps {
  file: File | null;
  onChange: (file: File | null) => void;
  disabled?: boolean;
  error?: string;
  validating?: boolean;
}

export function ReceiptFilePicker({
  file: selectedFile,
  onChange,
  disabled = false,
  error,
  validating = false
}: ReceiptFilePickerProps) {
  function handleChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (file) onChange(file);
  }

  const inputId = useId();

  return (
    <div className="flex flex-col gap-2">
      {/* Hidden native file input */}
      <input
        id={inputId}
        type="file"
        accept={[...RECEIPT_IMAGE_TYPES, ContentType.ApplicationPdf, '.pdf'].join(',')}
        disabled={disabled}
        className="peer sr-only"
        aria-label="Kassenzettel-Datei auswählen"
        onChange={handleChange}
      />

      {selectedFile ? (
        /* Selected state */
        <div className="flex items-center justify-between rounded border border-gray-300 bg-gray-50 px-3 py-2 text-sm">
          <span className="truncate text-gray-800" title={selectedFile.name}>
            {selectedFile.name}{' '}
            <span className="text-gray-500">({formatBytes(selectedFile.size)})</span>
          </span>
          <button
            type="button"
            onClick={() => onChange(null)}
            disabled={disabled}
            className="ml-3 shrink-0 text-gray-500 hover:text-gray-800 disabled:opacity-50"
            aria-label="Ausgewählte Datei entfernen"
          >
            ✕
          </button>
        </div>
      ) : (
        /* Empty state – click-to-browse trigger */
        <label
          htmlFor={inputId}
          className={`flex cursor-pointer flex-col items-center justify-center rounded border-2 border-dashed border-gray-300 px-4 py-6 text-center text-sm text-gray-500 hover:border-gray-400 hover:text-gray-700 peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 ${disabled ? 'cursor-not-allowed opacity-50' : ''}`}
        >
          <span className="text-2xl" aria-hidden="true">
            📄
          </span>
          <span className="mt-1">JPG, PNG oder einseitiges PDF auswählen</span>
          <span className="text-xs text-gray-400">Maximal 5 MB</span>
        </label>
      )}

      {/* Replace link – only shown when a file is selected */}
      {selectedFile && !disabled && (
        <label
          htmlFor={inputId}
          className="cursor-pointer text-xs text-gray-500 underline hover:text-gray-700 peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2"
        >
          Andere Datei auswählen
        </label>
      )}

      <div role="status" className="text-sm text-gray-600">
        {validating && 'Das PDF wird geprüft…'}
      </div>
      {error && (
        <p role="alert" className="text-sm text-red-600">
          {error}
        </p>
      )}
    </div>
  );
}

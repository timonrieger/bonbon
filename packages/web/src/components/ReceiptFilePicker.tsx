/**
 * ReceiptFilePicker – file selection and validation for receipt photos.
 *
 * Controlled: the parent owns the selected file and does the upload.
 * See docs/features/01-upload-processing.md.
 */
import { useId, useState } from 'react';
import {
  formatBytes,
  RECEIPT_IMAGE_TYPES,
  validateReceiptImage
} from '@/features/receipts/receiptImage';

export interface ReceiptFilePickerProps {
  /** The selected, already validated file; null when nothing is selected. */
  file: File | null;
  /** Called with a valid file, or null when the selection is cleared or invalid. */
  onChange: (file: File | null) => void;
  /** Disables the control, e.g. while an upload is in progress. */
  disabled?: boolean;
}

export function ReceiptFilePicker({
  file: selectedFile,
  onChange,
  disabled = false
}: ReceiptFilePickerProps) {
  const [error, setError] = useState<string | null>(null);

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0] ?? null;
    // Reset so the same file can be re-selected after a removal.
    e.target.value = '';

    if (!file) return;

    const validation = validateReceiptImage(file);
    if ('error' in validation) {
      setError(validation.error);
      onChange(null);
      return;
    }

    setError(null);
    onChange(file);
  }

  function handleRemove() {
    setError(null);
    onChange(null);
  }

  const inputId = useId();

  return (
    <div className="flex flex-col gap-2">
      {/* Hidden native file input */}
      <input
        id={inputId}
        type="file"
        accept={RECEIPT_IMAGE_TYPES.join(',')}
        disabled={disabled}
        className="sr-only"
        aria-label="Kassenzettel-Foto auswählen"
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
            onClick={handleRemove}
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
          className={`flex cursor-pointer flex-col items-center justify-center rounded border-2 border-dashed border-gray-300 px-4 py-6 text-center text-sm text-gray-500 hover:border-gray-400 hover:text-gray-700 ${disabled ? 'cursor-not-allowed opacity-50' : ''}`}
        >
          <span className="text-2xl" aria-hidden="true">
            📄
          </span>
          <span className="mt-1">JPG oder PNG auswählen</span>
          <span className="text-xs text-gray-400">Maximal 5 MB</span>
        </label>
      )}

      {/* Replace link – only shown when a file is selected */}
      {selectedFile && !disabled && (
        <label
          htmlFor={inputId}
          className="cursor-pointer text-xs text-gray-500 underline hover:text-gray-700"
        >
          Andere Datei auswählen
        </label>
      )}

      {/* Validation error */}
      {error && (
        <p role="alert" className="text-sm text-red-600">
          {error}
        </p>
      )}
    </div>
  );
}

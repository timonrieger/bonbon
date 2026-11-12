/**
 * ReceiptUpload – file selection and validation for receipt photos.
 *
 * Intentionally decoupled from the API: it validates the file locally and
 * calls `onFileReady` with the selected File so the parent can issue the
 * presigned-URL request once that endpoint exists.
 *
 * What this component does NOT do:
 *  - Request a presigned URL   (POST /households/{id}/receipts – not yet built)
 *  - Upload to S3
 *  - Show processing status
 *
 * See docs/features/01-upload-processing.md for the full planned flow.
 */
import { useId, useRef, useState } from 'react';

const ACCEPTED_TYPES: Record<string, string> = {
  'image/jpeg': '.jpg/.jpeg',
  'image/png': '.png'
};

const MAX_SIZE_BYTES = 5 * 1024 * 1024; // 5 MB

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function validate(file: File): string | null {
  if (!Object.hasOwn(ACCEPTED_TYPES, file.type)) {
    return 'Nur JPG- und PNG-Dateien sind erlaubt.';
  }
  if (file.size > MAX_SIZE_BYTES) {
    return `Die Datei ist zu gross (${formatBytes(file.size)}). Maximal erlaubt: 5 MB.`;
  }
  return null;
}

export interface ReceiptUploadProps {
  /** Called when a valid file is selected. Null means the selection was cleared. */
  onFileReady: (file: File | null) => void;
  /** Disables the control, e.g. while an upload is in progress. */
  disabled?: boolean;
}

export function ReceiptUpload({ onFileReady, disabled = false }: ReceiptUploadProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0] ?? null;
    // Reset so the same file can be re-selected after a removal.
    e.target.value = '';

    if (!file) return;

    const validationError = validate(file);
    if (validationError) {
      setError(validationError);
      setSelectedFile(null);
      onFileReady(null);
      return;
    }

    setError(null);
    setSelectedFile(file);
    onFileReady(file);
  }

  function handleRemove() {
    setSelectedFile(null);
    setError(null);
    onFileReady(null);
    // Allow the same file to be selected again.
    if (inputRef.current) inputRef.current.value = '';
  }

  const inputId = useId();

  return (
    <div className="flex flex-col gap-2">
      {/* Hidden native file input */}
      <input
        ref={inputRef}
        id={inputId}
        type="file"
        accept={Object.keys(ACCEPTED_TYPES).join(',')}
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
          className={[
            'flex cursor-pointer flex-col items-center justify-center rounded border-2 border-dashed border-gray-300 px-4 py-6 text-center text-sm text-gray-500',
            'hover:border-gray-400 hover:text-gray-700',
            disabled ? 'cursor-not-allowed opacity-50' : ''
          ]
            .filter(Boolean)
            .join(' ')}
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

import { HttpError } from '@oazapfts/runtime';
import { useEffect, useId, useRef, useState } from 'react';
import { defaults, deleteAccount } from '@/api';
import { useSessionMutation } from '@/components/AuthenticatedSession';
import { useDeletionPreview } from '@/features/account/useDeletionPreview';

const deletionTimeoutMs = 20_000;

async function requestDeletion() {
  const authenticatedFetch = defaults.fetch;
  if (!authenticatedFetch) throw new Error('The authenticated API client is unavailable.');

  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const deadline = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      const error = new DOMException('Account deletion request timed out', 'TimeoutError');
      controller.abort(error);
      reject(error);
    }, deletionTimeoutMs);
  });

  try {
    await Promise.race([
      deadline,
      deleteAccount({
        signal: controller.signal,
        fetch: async (input, options) => {
          const response = await authenticatedFetch(input, options);
          // The generated client unwraps all successful statuses. Only 202 confirms acceptance.
          if (response.status !== 202) {
            throw new HttpError(response.status, undefined, response.headers);
          }
          return response;
        }
      })
    ]);
  } finally {
    clearTimeout(timer);
  }
}

function deletionErrorMessage(error: unknown) {
  if (error instanceof DOMException && error.name === 'TimeoutError') {
    return 'Die Anfrage hat zu lange gedauert. Ob der Löschauftrag angenommen wurde, ist unklar. Du kannst es erneut versuchen.';
  }
  if (error instanceof HttpError) {
    return 'Die Annahme des Löschauftrags konnte nicht bestätigt werden. Du kannst es erneut versuchen.';
  }
  return 'Die Anfrage konnte nicht abgeschlossen werden. Ob der Löschauftrag angenommen wurde, ist unklar. Du kannst es erneut versuchen.';
}

interface DeleteAccountDialogProps {
  userId: string;
  userEmail: string;
  onClose: () => void;
  onAccepted: () => void;
  triggerRef: React.RefObject<HTMLButtonElement | null>;
}

export function DeleteAccountDialog({
  userId,
  userEmail,
  onClose,
  onAccepted,
  triggerRef
}: DeleteAccountDialogProps) {
  const id = useId();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const submitted = useRef(false);
  const [confirmedPreview, setConfirmedPreview] = useState<string | null>(null);
  const { preview, loading, ready, reload } = useDeletionPreview(userId);
  const previewKey = JSON.stringify(preview);
  const acknowledged = confirmedPreview === previewKey;
  const deletion = useSessionMutation({
    mutationFn: requestDeletion,
    networkMode: 'always',
    retry: false,
    onSuccess: onAccepted,
    onError: () => {
      submitted.current = false;
    }
  });
  const locked = deletion.isPending || deletion.isSuccess;

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    dialog.showModal();
    cancelRef.current?.focus();
    return () => {
      if (dialog.open) dialog.close();
    };
  }, []);

  function close() {
    if (submitted.current || locked) return;
    dialogRef.current?.close();
    onClose();
    triggerRef.current?.focus();
  }

  function submit() {
    if (!ready || !acknowledged || locked || submitted.current) return;
    submitted.current = true;
    deletion.mutate();
  }

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby={`${id}-title`}
      aria-describedby={`${id}-description`}
      onCancel={(event) => {
        event.preventDefault();
        close();
      }}
      className="m-auto max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] max-w-md overflow-y-auto rounded-lg bg-white p-6 shadow-lg backdrop:bg-black/40"
    >
      <h2 id={`${id}-title`} className="text-lg font-semibold">
        Konto löschen
      </h2>
      <p id={`${id}-description`} className="mt-3 break-words text-sm text-gray-700">
        Dein Konto{userEmail && <> ({userEmail})</>} wird unwiderruflich gelöscht.
      </p>

      {loading ? (
        <p role="status" className="mt-3 text-sm text-gray-700">
          Haushalte und Mitgliedschaften werden geladen…
        </p>
      ) : !ready ? (
        <div className="mt-3 text-sm">
          <p role="alert" className="text-red-700">
            Die Folgen für deine Haushalte konnten nicht vollständig geladen werden.
          </p>
          <button
            type="button"
            disabled={locked}
            className="mt-2 underline disabled:opacity-50"
            onClick={() => {
              setConfirmedPreview(null);
              void reload();
            }}
          >
            Vorschau erneut laden
          </button>
        </div>
      ) : preview.length === 0 ? (
        <p className="mt-3 text-sm text-gray-700">Du bist in keinem Haushalt Mitglied.</p>
      ) : (
        <ul className="mt-3 list-disc space-y-2 pl-5 text-sm text-gray-700">
          {preview.map(({ id: householdId, name, consequence, transfersOwnership }) => (
            <li key={householdId} className="break-words">
              <strong>{name}</strong>
              <p>{consequence}</p>
              {transfersOwnership && (
                <p>
                  Die Eigentümerrolle geht an das verbleibende Mitglied, das am längsten dabei ist.
                </p>
              )}
            </li>
          ))}
        </ul>
      )}

      <label className="mt-5 flex items-start gap-2 text-sm text-gray-700">
        <input
          type="checkbox"
          checked={acknowledged}
          disabled={!ready || locked}
          onChange={(event) => setConfirmedPreview(event.target.checked ? previewKey : null)}
          className="mt-0.5 h-4 w-4 shrink-0 accent-red-600 disabled:opacity-50"
        />
        Ich habe die Folgen gelesen und möchte mein Konto endgültig löschen.
      </label>

      {deletion.isError && (
        <p role="alert" className="mt-3 text-sm text-red-700">
          {deletionErrorMessage(deletion.error)}
        </p>
      )}
      {locked && (
        <p role="status" className="mt-3 text-sm text-gray-700">
          {deletion.isSuccess
            ? 'Löschauftrag angenommen. Du wirst abgemeldet.'
            : 'Löschauftrag wird gesendet…'}
        </p>
      )}

      <div className="mt-6 flex flex-col gap-2 sm:flex-row sm:justify-end">
        <button
          ref={cancelRef}
          type="button"
          disabled={locked}
          onClick={close}
          className="rounded border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
        >
          Abbrechen
        </button>
        <button
          type="button"
          disabled={!ready || !acknowledged || locked}
          onClick={submit}
          className="rounded bg-red-600 px-4 py-2 text-sm font-medium text-white enabled:hover:bg-red-700 disabled:opacity-50"
        >
          Konto endgültig löschen
        </button>
      </div>
    </dialog>
  );
}

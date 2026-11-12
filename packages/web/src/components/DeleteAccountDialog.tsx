/**
 * DeleteAccountDialog – confirmation dialog for account deletion.
 *
 * Shows the consequences and asks the user to confirm explicitly.
 * No authentication call is made here: the user is already signed in,
 * and calling signIn() on an active Amplify v6 session throws
 * UserAlreadyAuthenticatedException. The backend endpoint (DELETE /users/me)
 * receives the existing Cognito ID token from the shared fetch wrapper.
 *
 * What this component does NOT do:
 *  - Delete the Cognito account directly (would leave household data orphaned).
 *  - Call the backend deletion endpoint.
 *    DELETE /users/me (queues a deletion job) does not exist yet.
 *
 * To activate the actual deletion:
 *  1. Noel (@Dam-Mil) implements the deletion worker and DELETE /users/me.
 *  2. Run `mise run generate` so the endpoint appears in client.gen.ts.
 *  3. In App.tsx, pass a real `onConfirmed` from useMutation(deleteAccount).
 *  4. Remove `disabled` and the `acknowledged` guard from the confirm button.
 *  5. After the API responds, call signOut() so the session is cleaned up.
 *
 * See docs/features/05-account-deletion.md.
 */
import { useEffect, useId, useRef, useState } from 'react';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface DeleteAccountDialogProps {
  /** Email address of the currently signed-in user, shown for clarity. */
  userEmail: string;
  /** Called when the user closes or cancels the dialog. */
  onClose: () => void;
  /** Whether a deletion request is currently in flight (disables the form). */
  isSaving?: boolean;
  /**
   * Ref to the element that opened the dialog, so focus can be returned on close.
   * Pass `useRef<HTMLButtonElement>(null)` from the parent and attach it to the
   * trigger button.
   */
  triggerRef?: React.RefObject<HTMLButtonElement | null>;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function DeleteAccountDialog({
  userEmail,
  onClose,
  isSaving = false,
  triggerRef
}: DeleteAccountDialogProps) {
  const id = useId();
  const titleId = `${id}-title`;
  const descId = `${id}-desc`;

  // The user must tick the checkbox before the confirm button becomes clickable.
  const [acknowledged, setAcknowledged] = useState(false);

  // The dialog container itself needs tabIndex={-1} so it can receive
  // programmatic focus and relay keyboard events reliably.
  const dialogRef = useRef<HTMLDivElement>(null);

  // Move focus into the dialog when it opens (ARIA requirement for modal dialogs).
  useEffect(() => {
    dialogRef.current?.focus();
  }, []);

  function handleClose() {
    setAcknowledged(false);
    onClose();
    // Return focus to the element that opened the dialog.
    triggerRef?.current?.focus();
  }

  // Close on Escape unless a deletion is already in flight.
  function handleKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    if (e.key === 'Escape' && !isSaving) handleClose();
  }

  const checkboxId = `${id}-ack`;

  return (
    /* Backdrop */
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      aria-describedby={descId}
      // tabIndex + ref: makes the container focusable so focus() on mount works
      // and onKeyDown fires reliably for Escape regardless of inner focus target.
      tabIndex={-1}
      ref={dialogRef}
      onKeyDown={handleKeyDown}
    >
      <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-lg">
        <h2 id={titleId} className="text-lg font-semibold">
          Konto löschen
        </h2>

        <p id={descId} className="mt-3 text-sm text-gray-700">
          Das Konto von <span className="font-medium">{userEmail || 'deinem Account'}</span> wird
          unwiderruflich gelöscht. Das bedeutet:
        </p>

        <ul className="mt-2 list-disc pl-5 text-sm text-gray-700 space-y-1">
          <li>
            Haushalte, in denen du das einzige Mitglied bist, werden mit allen Belegen und Bildern
            gelöscht.
          </li>
          <li>
            In geteilten Haushalten bleiben deine Belege bestehen, dein Name wird entfernt. Die
            Eigentümerrolle geht an das dienstälteste Mitglied über.
          </li>
          <li>
            Diese Aktion kann <strong>nicht rückgängig</strong> gemacht werden.
          </li>
        </ul>

        {/* Explicit acknowledgement checkbox */}
        <div className="mt-5 flex items-start gap-2">
          <input
            id={checkboxId}
            type="checkbox"
            checked={acknowledged}
            disabled={isSaving}
            onChange={(e) => setAcknowledged(e.target.checked)}
            className="mt-0.5 h-4 w-4 shrink-0 accent-red-600 disabled:opacity-50"
          />
          <label htmlFor={checkboxId} className="text-sm text-gray-700">
            Ich habe die Konsequenzen gelesen und möchte mein Konto endgültig löschen.
          </label>
        </div>

        {/* Visible notice that the action is not yet functional */}
        <p className="mt-3 rounded bg-gray-50 px-3 py-2 text-xs text-gray-500">
          Die Kontolöschung ist noch nicht verfügbar. Der Button wird freigeschaltet, sobald die
          Funktion fertiggestellt ist.
        </p>

        <div className="mt-6 flex flex-col gap-2 sm:flex-row-reverse sm:gap-3">
          {/*
           * Confirm button – two layers of protection:
           *   1. `acknowledged` must be true (checkbox above).
           *   2. `disabled` hardcoded until DELETE /users/me is implemented.
           * When wiring up: add `onClick={onConfirmed}`, remove the hardcoded
           * `disabled`, and wire `onConfirmed` back into the props interface.
           */}
          <button
            type="button"
            disabled
            aria-disabled="true"
            className="rounded bg-red-600 px-4 py-2 text-sm font-medium text-white opacity-50"
          >
            {isSaving ? 'Wird gelöscht…' : 'Konto endgültig löschen'}
          </button>
          <button
            type="button"
            disabled={isSaving}
            onClick={handleClose}
            className="rounded border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            Abbrechen
          </button>
        </div>
      </div>
    </div>
  );
}

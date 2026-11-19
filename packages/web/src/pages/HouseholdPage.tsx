import { useAuthenticator } from '@aws-amplify/ui-react';
import { HttpError } from '@oazapfts/runtime';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import {
  createInvite,
  createReceipt,
  getHousehold,
  type HouseholdList,
  type InviteCode,
  leaveHousehold,
  listMembers,
  listReceipts
} from '@/api';
import { readPrivateResource } from '@/api/privateQuery';
import { formatBytes, prepareReceiptImage } from '@/api/receiptImage';
import {
  formatDate,
  formatRappen,
  formatUploadTimestamp,
  isReceiptProcessing,
  RECEIPT_POLL_ERROR_INTERVAL,
  RECEIPT_POLL_INTERVAL,
  uploadToS3
} from '@/api/receipts';
import { useUploadSignal } from '@/components/AuthenticatedSession';
import { ReceiptFilePicker } from '@/components/ReceiptFilePicker';
import { ReceiptStatusBadge } from '@/components/ReceiptStatusBadge';
import { householdRoleLabel } from '@/householdRoleLabel';

export function HouseholdPage() {
  // biome-ignore lint/style/noNonNullAssertion: the route always has :householdId
  const householdId = useParams().householdId!;
  return <HouseholdContent key={householdId} householdId={householdId} />;
}

function HouseholdContent({ householdId }: { householdId: string }) {
  const { user } = useAuthenticator((context) => [context.user]);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const getUploadSignal = useUploadSignal();

  const household = useQuery({
    queryKey: ['household', householdId, 'receipt-page'],
    queryFn: ({ signal }) =>
      readPrivateResource((options) => getHousehold({ householdId }, options), signal)
  });

  const members = useQuery({
    queryKey: ['householdMembers', householdId],
    queryFn: ({ signal }) =>
      readPrivateResource((options) => listMembers({ householdId }, options), signal),
    enabled: Boolean(household.data)
  });

  const [showLeaveDialog, setShowLeaveDialog] = useState(false);
  const leaveButtonRef = useRef<HTMLButtonElement>(null);
  const leaveSubmissionRef = useRef(false);
  const [file, setFile] = useState<File | null>(null);
  const [preparing, setPreparing] = useState(false);
  const preparation = useRef<AbortController | null>(null);
  const submitting = useRef(false);

  useLayoutEffect(() => {
    const controller = new AbortController();
    preparation.current = controller;
    return () => controller.abort();
  }, []);

  const upload = useMutation({
    mutationFn: async ({
      householdId,
      file,
      signal,
      preparationSignal
    }: {
      householdId: string;
      file: File;
      signal: AbortSignal;
      preparationSignal: AbortSignal;
    }) => {
      const prepared = await prepareReceiptImage(file, preparationSignal);
      preparationSignal.throwIfAborted();
      setPreparing(false);

      // Sign the exact MIME type and size of the file sent to S3.
      const receiptUpload = await createReceipt(
        {
          householdId,
          createReceiptRequest: {
            content_type: prepared.contentType,
            size_bytes: prepared.file.size
          }
        },
        { signal }
      );

      // Step 2: unauthenticated PUT — send raw bytes to S3 with all backend-supplied headers.
      signal.throwIfAborted();
      await uploadToS3(receiptUpload, prepared.file, signal);
      return { completedAt: Date.now(), originalSize: file.size, uploadedSize: prepared.file.size };
    },
    onSettled: () => {
      submitting.current = false;
      setPreparing(false);
    },
    onSuccess: (_, { householdId }) => {
      setFile(null);
      void queryClient.invalidateQueries({ queryKey: ['receipts', householdId] });
    }
  });

  const receipts = useQuery({
    queryKey: ['receipts', householdId],
    queryFn: ({ signal }) =>
      readPrivateResource((options) => listReceipts({ householdId }, options), signal),
    enabled: Boolean(household.data),
    retry: false,
    refetchIntervalInBackground: false,
    refetchInterval: ({ state }) => {
      // Leave time for a final list request after the server's abandonment cutoff.
      const processing = state.data?.receipts.some((item) =>
        isReceiptProcessing(item, RECEIPT_POLL_ERROR_INTERVAL)
      );
      const refreshFailed = state.status === 'error';
      const recoveringAfterUpload =
        refreshFailed &&
        state.data !== null &&
        upload.data !== undefined &&
        state.dataUpdatedAt < upload.data.completedAt &&
        Date.now() - upload.data.completedAt < 60_000;

      if (!processing && !recoveringAfterUpload) return false;
      return refreshFailed ? RECEIPT_POLL_ERROR_INTERVAL : RECEIPT_POLL_INTERVAL;
    }
  });

  function handleUpload() {
    if (!file || !preparation.current || submitting.current || upload.isPending) return;

    const signal = getUploadSignal();
    submitting.current = true;
    setPreparing(true);
    upload.mutate({
      householdId,
      file,
      signal,
      preparationSignal: AbortSignal.any([signal, preparation.current.signal])
    });
  }

  const leave = useMutation({
    mutationFn: (signal: AbortSignal) => leaveHousehold({ householdId }, { signal }),
    retry: false,
    onSuccess: () => {
      preparation.current?.abort();
      const householdsQueryKey = ['households', user?.userId] as const;
      queryClient.setQueryData<HouseholdList>(householdsQueryKey, (current) =>
        current
          ? {
              ...current,
              households: current.households.filter((item) => item.id !== householdId)
            }
          : current
      );
      queryClient.removeQueries({ queryKey: ['household', householdId] });
      queryClient.removeQueries({ queryKey: ['householdMembers', householdId] });
      queryClient.removeQueries({ queryKey: ['receipts', householdId] });
      queryClient.removeQueries({ queryKey: ['receipt', householdId] });
      queryClient.removeQueries({ queryKey: ['monthlyReport', householdId] });
      queryClient.removeQueries({ queryKey: ['spendingTrend', householdId] });
      navigate('/', { replace: true });
      void queryClient.invalidateQueries({
        queryKey: householdsQueryKey
      });
    },
    onSettled: () => {
      leaveSubmissionRef.current = false;
    }
  });

  function confirmLeave() {
    if (leaveSubmissionRef.current || leave.isPending) return;

    leaveSubmissionRef.current = true;
    leave.mutate(getUploadSignal());
  }

  function handleFileChange(next: File | null) {
    upload.reset();
    setFile(next);
  }

  if (household.isPending) return <p>Laden…</p>;
  if (household.data === null) {
    return (
      <div className="text-red-600">
        <p role="alert">Dieser Haushalt ist nicht verfügbar.</p>
        <Link to="/" className="underline">
          Zu meinen Haushalten
        </Link>
      </div>
    );
  }
  if (!household.data) {
    return (
      <p role="alert" className="text-red-600">
        Der Haushalt konnte nicht geladen werden.
      </p>
    );
  }

  const receiptRows = receipts.data?.receipts;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold">{household.data.name}</h1>
        {household.isError && (
          <p role="status" className="text-sm text-red-600">
            Der Haushalt konnte nicht aktualisiert werden.
          </p>
        )}
        <p className="text-sm text-gray-600">
          Deine Rolle: {householdRoleLabel(household.data.my_role)}
        </p>
        <Link
          to={`/households/${householdId}/dashboard`}
          className="mt-2 inline-block text-sm underline"
        >
          Zum Dashboard
        </Link>
        <button
          ref={leaveButtonRef}
          type="button"
          onClick={() => {
            leave.reset();
            setShowLeaveDialog(true);
          }}
          className="mt-3 block rounded border border-red-300 px-3 py-2 text-sm text-red-700 hover:bg-red-50"
        >
          Haushalt verlassen
        </button>
      </div>

      <section aria-labelledby="members-heading">
        <h2 id="members-heading" className="mb-3 text-lg font-medium">
          Mitglieder
        </h2>

        {members.isPending && <p className="text-sm text-gray-600">Mitglieder werden geladen…</p>}
        {(members.isError || members.data === null) && (
          <p role="alert" className="text-sm text-red-600">
            {members.error?.message ?? 'Die Mitglieder sind nicht verfügbar.'}
          </p>
        )}
        {members.data?.members.length === 0 && (
          <p className="text-sm text-gray-600">Keine Mitglieder gefunden.</p>
        )}
        {members.data && members.data.members.length > 0 && (
          <ul className="divide-y divide-gray-200 rounded border border-gray-200">
            {members.data.members.map((member) => (
              <li key={member.user_id} className="flex justify-between gap-4 px-3 py-2 text-sm">
                <span>{member.display_name}</span>
                <span className="text-gray-600">{householdRoleLabel(member.role)}</span>
              </li>
            ))}
          </ul>
        )}

        <InviteCodeSection key={householdId} householdId={householdId} />
      </section>

      <section aria-labelledby="upload-heading">
        <h2 id="upload-heading" className="mb-3 text-lg font-medium">
          Kassenzettel hochladen
        </h2>

        <ReceiptFilePicker file={file} onChange={handleFileChange} disabled={upload.isPending} />

        {file && (
          <button
            type="button"
            onClick={handleUpload}
            disabled={upload.isPending}
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
            Kassenzettel erfolgreich hochgeladen. Die Verarbeitung läuft automatisch im Hintergrund.
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
      </section>

      <section aria-labelledby="receipts-heading">
        <h2 id="receipts-heading" className="mb-3 text-lg font-medium">
          Kassenzettel
        </h2>

        {receipts.isPending && (
          <p role="status" className="text-sm text-gray-600">
            Kassenzettel werden geladen…
          </p>
        )}

        {(receipts.isError || receipts.data === null) && (
          <p role={receiptRows ? 'status' : 'alert'} className="text-sm text-red-600">
            {receiptRows
              ? 'Die Kassenzettel konnten nicht aktualisiert werden.'
              : 'Die Kassenzettel konnten nicht geladen werden.'}
          </p>
        )}

        {receiptRows?.length === 0 && (
          <p className="text-sm text-gray-500">Noch keine Kassenzettel vorhanden.</p>
        )}

        {receiptRows && receiptRows.length > 0 && (
          <ul className="flex flex-col gap-2">
            {receiptRows.map((receipt) => {
              const store = receipt.store?.trim();
              const uploadedAt =
                !store || !receipt.purchase_date || receipt.total_rappen === null
                  ? formatUploadTimestamp(receipt.created_at)
                  : null;
              return (
                <li key={receipt.id}>
                  <Link
                    to={`/households/${householdId}/receipts/${receipt.id}`}
                    className="flex flex-col gap-1 rounded border border-gray-200 px-4 py-3 hover:bg-gray-50 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <div className="flex min-w-0 flex-col gap-0.5">
                      <span className="break-words font-medium">
                        {store || 'Geschäft nicht erkannt'}
                      </span>
                      <span className="text-sm text-gray-500">
                        <span className="sr-only">Kaufdatum: </span>
                        {formatDate(receipt.purchase_date)}
                      </span>
                      {uploadedAt && (
                        <span className="text-sm text-gray-500">
                          Hochgeladen am <time dateTime={receipt.created_at}>{uploadedAt}</time>
                        </span>
                      )}
                    </div>
                    <div className="flex shrink-0 flex-wrap items-center gap-3 sm:gap-4">
                      <span className="text-sm font-medium">
                        <span className="sr-only">Total: </span>
                        {formatRappen(receipt.total_rappen)}
                      </span>
                      <ReceiptStatusBadge status={receipt.status} />
                    </div>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </section>
      {showLeaveDialog && (
        <LeaveHouseholdDialog
          error={leave.isError ? leaveErrorMessage(leave.error) : null}
          isPending={leave.isPending}
          onClose={() => setShowLeaveDialog(false)}
          onConfirm={confirmLeave}
          triggerRef={leaveButtonRef}
        />
      )}
    </div>
  );
}

function leaveErrorMessage(error: Error) {
  if (!(error instanceof HttpError)) {
    return 'Haushalt konnte nicht verlassen werden. Bitte versuche es erneut.';
  }

  switch (error.status) {
    case 404:
      return 'Du hast keinen Zugriff mehr auf diesen Haushalt.';
    case 409:
      return 'Du musst zuerst die Haushaltsleitung an ein anderes Mitglied übergeben, bevor du den Haushalt verlassen kannst.';
    default:
      return 'Haushalt konnte nicht verlassen werden. Bitte versuche es erneut.';
  }
}

function LeaveHouseholdDialog({
  error,
  isPending,
  onClose,
  onConfirm,
  triggerRef
}: {
  error: string | null;
  isPending: boolean;
  onClose: () => void;
  onConfirm: () => void;
  triggerRef: React.RefObject<HTMLButtonElement | null>;
}) {
  const id = useId();
  const titleId = `${id}-title`;
  const warningId = `${id}-warning`;
  const dialogRef = useRef<HTMLDialogElement>(null);
  const cancelButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    dialog.showModal();
    cancelButtonRef.current?.focus();

    return () => {
      if (dialog.open) dialog.close();
    };
  }, []);

  function close() {
    onClose();
    window.requestAnimationFrame(() => triggerRef.current?.focus());
  }

  function handleCancel(event: React.SyntheticEvent<HTMLDialogElement>) {
    event.preventDefault();
    if (!isPending) close();
  }

  return (
    <dialog
      className="m-auto w-full max-w-md rounded-lg bg-white p-6 shadow-lg backdrop:bg-black/40"
      aria-labelledby={titleId}
      aria-describedby={warningId}
      ref={dialogRef}
      onCancel={handleCancel}
    >
      <h2 id={titleId} className="text-lg font-semibold">
        Haushalt verlassen?
      </h2>
      <p className="mt-3 text-sm text-gray-700">
        Du verlierst sofort den Zugriff auf diesen Haushalt.
      </p>
      <p id={warningId} className="mt-3 rounded bg-red-50 px-3 py-2 text-sm text-red-800">
        Falls du das letzte Mitglied bist, wird der Haushalt samt Belegen und Bildern gelöscht.
      </p>

      {error && (
        <p role="alert" className="mt-3 text-sm text-red-600">
          {error}
        </p>
      )}

      <div className="mt-6 flex flex-col gap-2 sm:flex-row-reverse sm:gap-3">
        <button
          type="button"
          disabled={isPending}
          onClick={onConfirm}
          className="rounded bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
        >
          {isPending ? 'Wird verlassen…' : 'Haushalt verlassen'}
        </button>
        <button
          ref={cancelButtonRef}
          type="button"
          disabled={isPending}
          onClick={close}
          className="rounded border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
        >
          Abbrechen
        </button>
      </div>
    </dialog>
  );
}

function InviteCodeSection({ householdId }: { householdId: string }) {
  const getUploadSignal = useUploadSignal();
  const [copyStatus, setCopyStatus] = useState<{
    invite: InviteCode;
    status: 'copied' | 'error';
  } | null>(null);
  const inviteMutation = useMutation({
    mutationFn: (signal: AbortSignal) => createInvite({ householdId }, { signal }),
    onMutate: () => setCopyStatus(null)
  });
  const invite = inviteMutation.data;
  const displayedCopyStatus =
    invite && copyStatus && copyStatus.invite === invite ? copyStatus.status : null;

  async function copyInviteCode() {
    if (!invite) return;

    try {
      await navigator.clipboard.writeText(invite.code);
      setCopyStatus({ invite, status: 'copied' });
    } catch {
      setCopyStatus({ invite, status: 'error' });
    }
  }

  return (
    <div className="mt-4">
      <button
        type="button"
        onClick={() => inviteMutation.mutate(getUploadSignal())}
        disabled={inviteMutation.isPending}
        className="rounded border border-gray-300 px-3 py-2 text-sm hover:bg-gray-100 disabled:opacity-50"
      >
        {inviteMutation.isPending ? 'Wird erstellt…' : 'Einladungscode erstellen'}
      </button>

      {inviteMutation.isError && (
        <p role="alert" className="mt-2 text-sm text-red-600">
          Einladungscode konnte nicht erstellt werden: {inviteMutation.error.message}
        </p>
      )}

      {invite && (
        <div className="mt-3 rounded border border-gray-200 p-3">
          <p className="text-sm font-medium">Einladungscode</p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <code className="select-all rounded bg-gray-100 px-2 py-1 font-mono">
              {invite.code}
            </code>
            <button
              type="button"
              onClick={copyInviteCode}
              className="rounded border border-gray-300 px-3 py-1 text-sm hover:bg-gray-100"
            >
              Code kopieren
            </button>
          </div>
          <p className="mt-2 text-sm text-gray-600">
            Gültig bis{' '}
            <time dateTime={invite.expires_at}>
              {new Intl.DateTimeFormat('de-CH', {
                dateStyle: 'medium',
                timeStyle: 'short'
              }).format(new Date(invite.expires_at))}
            </time>
          </p>
          <p className="mt-2 text-sm text-gray-600">
            Der Code kann nur einmal eingelöst werden und wird nur direkt nach dem Erstellen
            angezeigt. Speichere ihn jetzt.
          </p>
          {displayedCopyStatus === 'copied' && (
            <p role="status" className="mt-2 text-sm text-green-700">
              Einladungscode kopiert.
            </p>
          )}
          {displayedCopyStatus === 'error' && (
            <p role="alert" className="mt-2 text-sm text-red-600">
              Kopieren nicht möglich. Bitte markiere den Code und kopiere ihn manuell.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

import { useAuthenticator } from '@aws-amplify/ui-react';
import { HttpError } from '@oazapfts/runtime';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useId, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import {
  type ContentType,
  createInvite,
  createReceipt,
  getHousehold,
  type HouseholdList,
  type InviteCode,
  leaveHousehold,
  listMembers
} from '@/api';
import { uploadToS3 } from '@/api/receipts';
import { ReceiptFilePicker } from '@/components/ReceiptFilePicker';
import { householdRoleLabel } from '@/householdRoleLabel';

export function HouseholdPage() {
  // biome-ignore lint/style/noNonNullAssertion: the route always has :householdId
  const householdId = useParams().householdId!;
  const { user } = useAuthenticator((context) => [context.user]);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const household = useQuery({
    queryKey: ['household', householdId],
    queryFn: () => getHousehold({ householdId })
  });
  const members = useQuery({
    queryKey: ['householdMembers', householdId],
    queryFn: () => listMembers({ householdId }),
    enabled: household.isSuccess
  });

  const [file, setFile] = useState<File | null>(null);
  const [showLeaveDialog, setShowLeaveDialog] = useState(false);
  const leaveButtonRef = useRef<HTMLButtonElement>(null);
  const leaveSubmissionRef = useRef(false);

  const upload = useMutation({
    mutationFn: async (photo: File) => {
      // Step 1: authenticated POST — get presigned URL + headers from the backend.
      const receiptUpload = await createReceipt({
        householdId,
        // ReceiptFilePicker only lets accepted content types through.
        createReceiptRequest: { content_type: photo.type as ContentType, size_bytes: photo.size }
      });

      // Step 2: unauthenticated PUT — send raw bytes to S3 with all backend-supplied headers.
      await uploadToS3(receiptUpload, photo);
    },
    onSuccess: () => setFile(null)
  });

  const leave = useMutation({
    mutationFn: () => leaveHousehold({ householdId }),
    retry: false,
    onSuccess: () => {
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
    leave.mutate();
  }

  function handleFileChange(next: File | null) {
    upload.reset();
    setFile(next);
  }

  if (household.isPending) return <p>Laden…</p>;
  if (household.isError) {
    if (household.error instanceof HttpError && household.error.status === 404) {
      return (
        <div className="text-red-600">
          <p>Dieser Haushalt ist nicht verfügbar.</p>
          <Link to="/" className="underline">
            Zu meinen Haushalten
          </Link>
        </div>
      );
    }

    return <p className="text-red-600">{household.error.message}</p>;
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold">{household.data.name}</h1>
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
        {members.isError && (
          <p role="alert" className="text-sm text-red-600">
            {members.error.message}
          </p>
        )}
        {members.isSuccess && members.data.members.length === 0 && (
          <p className="text-sm text-gray-600">Keine Mitglieder gefunden.</p>
        )}
        {members.isSuccess && members.data.members.length > 0 && (
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
            onClick={() => upload.mutate(file)}
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
            {upload.error.message}
          </p>
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
  const [copyStatus, setCopyStatus] = useState<{
    invite: InviteCode;
    status: 'copied' | 'error';
  } | null>(null);
  const inviteMutation = useMutation({
    mutationFn: () => createInvite({ householdId }),
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
        onClick={() => inviteMutation.mutate()}
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

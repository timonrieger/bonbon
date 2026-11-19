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
  type Household,
  type HouseholdList,
  type InviteCode,
  leaveHousehold,
  listMembers,
  type Member,
  type MemberList,
  MyRole,
  Role,
  removeMember,
  transferOwnership
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
  const [selectedMember, setSelectedMember] = useState<Member | null>(null);
  const transferButtonRef = useRef<HTMLButtonElement>(null);
  const transferSubmissionRef = useRef(false);
  const [memberToRemove, setMemberToRemove] = useState<Member | null>(null);
  const removeMemberButtonRef = useRef<HTMLButtonElement>(null);
  const removeMemberSubmissionRef = useRef(false);
  const membersHeadingRef = useRef<HTMLHeadingElement>(null);

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
  const transfer = useMutation({
    mutationFn: (userId: string) =>
      transferOwnership({ householdId, transferOwnerRequest: { user_id: userId } }),
    retry: false,
    onSuccess: async (updatedMembers) => {
      const membersQueryKey = ['householdMembers', householdId] as const;
      const householdQueryKey = ['household', householdId] as const;
      const householdsQueryKey = ['households', user?.userId] as const;

      await Promise.all([
        queryClient.cancelQueries({ queryKey: membersQueryKey }),
        queryClient.cancelQueries({ queryKey: householdQueryKey }),
        queryClient.cancelQueries({ queryKey: householdsQueryKey })
      ]);

      queryClient.setQueryData<MemberList>(membersQueryKey, updatedMembers);

      const ownMembership = updatedMembers.members.find(
        (member) => member.user_id === user?.userId
      );
      if (ownMembership) {
        const myRole = ownMembership.role === Role.Owner ? MyRole.Owner : MyRole.Member;
        queryClient.setQueryData<Household>(householdQueryKey, (current) =>
          current ? { ...current, my_role: myRole } : current
        );
        queryClient.setQueryData<HouseholdList>(householdsQueryKey, (current) =>
          current
            ? {
                ...current,
                households: current.households.map((item) =>
                  item.id === householdId ? { ...item, my_role: myRole } : item
                )
              }
            : current
        );
      } else {
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: householdQueryKey }),
          queryClient.invalidateQueries({ queryKey: householdsQueryKey })
        ]);
      }

      setSelectedMember(null);
    },
    onSettled: () => {
      transferSubmissionRef.current = false;
    }
  });
  const remove = useMutation({
    mutationFn: (userId: string) => removeMember({ householdId, userId }),
    retry: false,
    onSuccess: async (_, userId) => {
      const membersQueryKey = ['householdMembers', householdId] as const;
      await queryClient.cancelQueries({ queryKey: membersQueryKey });
      queryClient.setQueryData<MemberList>(membersQueryKey, (current) =>
        current
          ? {
              ...current,
              members: current.members.filter((member) => member.user_id !== userId)
            }
          : current
      );
      setMemberToRemove(null);
      window.requestAnimationFrame(() => membersHeadingRef.current?.focus());
      void queryClient.invalidateQueries({ queryKey: membersQueryKey });
    },
    onSettled: () => {
      removeMemberSubmissionRef.current = false;
    }
  });

  function confirmLeave() {
    if (leaveSubmissionRef.current || leave.isPending) return;

    leaveSubmissionRef.current = true;
    leave.mutate();
  }

  function confirmTransfer() {
    if (!selectedMember || transferSubmissionRef.current || transfer.isPending) return;

    transferSubmissionRef.current = true;
    transfer.mutate(selectedMember.user_id);
  }

  function confirmRemoveMember() {
    if (!memberToRemove || removeMemberSubmissionRef.current || remove.isPending) return;

    removeMemberSubmissionRef.current = true;
    remove.mutate(memberToRemove.user_id);
  }

  function handleFileChange(next: File | null) {
    upload.reset();
    setFile(next);
  }

  if (household.isPending) return <p>Laden…</p>;
  if (household.isError) return <p className="text-red-600">{household.error.message}</p>;

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
        <h2
          id="members-heading"
          ref={membersHeadingRef}
          tabIndex={-1}
          className="mb-3 text-lg font-medium"
        >
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
                <div className="flex flex-wrap items-center justify-end gap-3">
                  <span className="text-gray-600">{householdRoleLabel(member.role)}</span>
                  {household.data.my_role === MyRole.Owner &&
                    user?.userId !== undefined &&
                    member.user_id !== user.userId && (
                      <>
                        <button
                          type="button"
                          onClick={(event) => {
                            transfer.reset();
                            transferButtonRef.current = event.currentTarget;
                            setSelectedMember(member);
                          }}
                          className="text-sm underline"
                        >
                          Haushaltsleitung übergeben
                        </button>
                        <button
                          type="button"
                          onClick={(event) => {
                            remove.reset();
                            removeMemberButtonRef.current = event.currentTarget;
                            setMemberToRemove(member);
                          }}
                          className="text-sm text-red-700 underline"
                        >
                          Mitglied entfernen
                        </button>
                      </>
                    )}
                </div>
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
      {selectedMember && (
        <TransferOwnershipDialog
          member={selectedMember}
          error={transfer.isError ? transferErrorMessage(transfer.error) : null}
          isPending={transfer.isPending}
          onClose={() => setSelectedMember(null)}
          onConfirm={confirmTransfer}
          triggerRef={transferButtonRef}
        />
      )}
      {memberToRemove && (
        <RemoveMemberDialog
          member={memberToRemove}
          error={remove.isError ? removeMemberErrorMessage(remove.error) : null}
          isPending={remove.isPending}
          onClose={() => setMemberToRemove(null)}
          onConfirm={confirmRemoveMember}
          triggerRef={removeMemberButtonRef}
        />
      )}
    </div>
  );
}

function transferErrorMessage(error: Error) {
  if (!(error instanceof HttpError)) {
    return 'Haushaltsleitung konnte nicht übergeben werden. Bitte versuche es erneut.';
  }

  switch (error.status) {
    case 403:
      return 'Du bist nicht berechtigt, die Haushaltsleitung zu übergeben.';
    case 404:
      return 'Der Haushalt oder das Mitglied ist nicht mehr verfügbar.';
    default:
      return 'Haushaltsleitung konnte nicht übergeben werden. Bitte versuche es erneut.';
  }
}

function removeMemberErrorMessage(error: Error) {
  if (!(error instanceof HttpError)) {
    return 'Mitglied konnte nicht entfernt werden. Bitte versuche es erneut.';
  }

  switch (error.status) {
    case 403:
      return 'Du bist nicht berechtigt, Mitglieder aus diesem Haushalt zu entfernen.';
    case 404:
      return 'Der Haushalt oder das Mitglied ist nicht mehr verfügbar.';
    default:
      return 'Mitglied konnte nicht entfernt werden. Bitte versuche es erneut.';
  }
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

function TransferOwnershipDialog({
  member,
  error,
  isPending,
  onClose,
  onConfirm,
  triggerRef
}: {
  member: Member;
  error: string | null;
  isPending: boolean;
  onClose: () => void;
  onConfirm: () => void;
  triggerRef: React.RefObject<HTMLButtonElement | null>;
}) {
  const id = useId();
  const titleId = `${id}-title`;
  const descriptionId = `${id}-description`;
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
      aria-describedby={descriptionId}
      ref={dialogRef}
      onCancel={handleCancel}
    >
      <h2 id={titleId} className="text-lg font-semibold">
        Haushaltsleitung übergeben?
      </h2>
      <p id={descriptionId} className="mt-3 text-sm text-gray-700">
        Die Haushaltsleitung wird an <span className="font-medium">{member.display_name}</span>{' '}
        übergeben. Dein eigenes Konto bleibt als Mitglied im Haushalt.
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
          className="rounded bg-black px-4 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-50"
        >
          {isPending ? 'Wird übergeben…' : 'Haushaltsleitung übergeben'}
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

function RemoveMemberDialog({
  member,
  error,
  isPending,
  onClose,
  onConfirm,
  triggerRef
}: {
  member: Member;
  error: string | null;
  isPending: boolean;
  onClose: () => void;
  onConfirm: () => void;
  triggerRef: React.RefObject<HTMLButtonElement | null>;
}) {
  const id = useId();
  const titleId = `${id}-title`;
  const descriptionId = `${id}-description`;
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
      aria-describedby={descriptionId}
      ref={dialogRef}
      onCancel={handleCancel}
    >
      <h2 id={titleId} className="text-lg font-semibold">
        Mitglied entfernen?
      </h2>
      <p id={descriptionId} className="mt-3 text-sm text-gray-700">
        <span className="font-medium">{member.display_name}</span> verliert sofort den Zugriff auf
        diesen Haushalt.
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
          {isPending ? 'Wird entfernt…' : 'Mitglied entfernen'}
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

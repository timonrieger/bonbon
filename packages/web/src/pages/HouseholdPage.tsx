import { useAuthenticator } from '@aws-amplify/ui-react';
import { HttpError } from '@oazapfts/runtime';
import { useIsMutating, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useId, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import {
  createInvite,
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
import { requestPrivateResource } from '@/api/privateQuery';
import { useSessionMutation, useSessionSignal } from '@/components/AuthenticatedSession';
import { HouseholdReceiptList, useHouseholdReceiptList } from '@/components/HouseholdReceiptList';
import { ReceiptUploadSection } from '@/components/ReceiptUploadSection';
import {
  denyHouseholdAccess,
  handleHouseholdAccessError,
  householdAccessKey,
  readHouseholdResource
} from '@/features/households/householdAccess';
import { useHouseholdAccess } from '@/features/households/useHouseholdAccess';
import { useReceiptUpload } from '@/features/receipts/useReceiptUpload';
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
  const getSessionSignal = useSessionSignal();

  const household = useHouseholdAccess(householdId);
  const leaveKey = ['leaveHousehold', householdId] as const;
  const activeLeave = useIsMutating({ mutationKey: leaveKey, exact: true }) > 0;
  const members = useQuery({
    queryKey: ['householdMembers', householdId],
    queryFn: ({ signal }) =>
      readHouseholdResource(
        queryClient,
        householdId,
        (options) => listMembers({ householdId }, options),
        signal
      ),
    enabled: Boolean(household.data)
  });

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

  function isLeavePending() {
    return (
      leaveSubmissionRef.current ||
      queryClient.isMutating({ mutationKey: leaveKey, exact: true }) > 0
    );
  }

  const receiptUpload = useReceiptUpload(householdId, isLeavePending);
  const { activeUpload } = receiptUpload;
  const receiptList = useHouseholdReceiptList(
    householdId,
    Boolean(household.data),
    receiptUpload.upload.data?.completedAt
  );

  const leave = useSessionMutation({
    mutationKey: leaveKey,
    mutationFn: () => requestPrivateResource((options) => leaveHousehold({ householdId }, options)),
    retry: false,
    onError: handleAccessError,
    onSuccess: () => {
      receiptUpload.abortPreparation();
      const householdsQueryKey = ['households', user?.userId] as const;
      denyHouseholdAccess(queryClient, householdId);
      navigate('/', { replace: true });
      void queryClient.invalidateQueries({
        queryKey: householdsQueryKey
      });
    },
    onSettled: () => {
      leaveSubmissionRef.current = false;
    }
  });
  function handleAccessError(error: Error) {
    handleHouseholdAccessError(queryClient, householdId, error, getSessionSignal());
  }

  function refreshAccessAfterMemberMutationError(error: Error) {
    // A role change or a missing target member can also return 403 or 404.
    if (error instanceof HttpError && (error.status === 403 || error.status === 404)) {
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: householdAccessKey(householdId) }),
        queryClient.invalidateQueries({ queryKey: ['householdMembers', householdId] })
      ]);
    } else {
      handleAccessError(error);
    }
  }

  const transfer = useSessionMutation({
    mutationFn: (userId: string) =>
      requestPrivateResource((options) =>
        transferOwnership({ householdId, transferOwnerRequest: { user_id: userId } }, options)
      ),
    retry: false,
    onError: refreshAccessAfterMemberMutationError,
    onSuccess: async (updatedMembers) => {
      const signal = getSessionSignal();
      if (!queryClient.getQueryData(householdAccessKey(householdId))) return;
      const membersQueryKey = ['householdMembers', householdId] as const;
      const householdQueryKey = householdAccessKey(householdId);
      const householdsQueryKey = ['households', user?.userId] as const;

      await Promise.all([
        queryClient.cancelQueries({ queryKey: membersQueryKey }),
        queryClient.cancelQueries({ queryKey: householdsQueryKey })
      ]);

      if (signal.aborted || !queryClient.getQueryData(householdQueryKey)) return;
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
      }

      setSelectedMember(null);
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: householdQueryKey }),
        queryClient.invalidateQueries({ queryKey: householdsQueryKey })
      ]);
      window.requestAnimationFrame(() => membersHeadingRef.current?.focus());
    },
    onSettled: () => {
      transferSubmissionRef.current = false;
    }
  });
  const remove = useSessionMutation({
    mutationFn: (userId: string) =>
      requestPrivateResource((options) => removeMember({ householdId, userId }, options)),
    retry: false,
    onError: refreshAccessAfterMemberMutationError,
    onSuccess: async (_, userId) => {
      const signal = getSessionSignal();
      if (!queryClient.getQueryData(householdAccessKey(householdId))) return;
      const membersQueryKey = ['householdMembers', householdId] as const;
      await queryClient.cancelQueries({ queryKey: membersQueryKey });
      if (signal.aborted || !queryClient.getQueryData(householdAccessKey(householdId))) return;
      queryClient.setQueryData<MemberList>(membersQueryKey, (current) =>
        current
          ? {
              ...current,
              members: current.members.filter((member) => member.user_id !== userId)
            }
          : current
      );
      setMemberToRemove(null);
      void queryClient.invalidateQueries({ queryKey: membersQueryKey });
    },
    onSettled: () => {
      removeMemberSubmissionRef.current = false;
    }
  });

  useEffect(() => {
    if (remove.isSuccess && memberToRemove === null) {
      membersHeadingRef.current?.focus();
    }
  }, [memberToRemove, remove.isSuccess]);

  function confirmLeave() {
    if (isLeavePending() || receiptUpload.isUploadPending()) return;

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

  const isOwner = household.data.my_role === MyRole.Owner;

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
          disabled={activeUpload || activeLeave}
          onClick={() => {
            leave.reset();
            setShowLeaveDialog(true);
          }}
          className="mt-3 block rounded border border-red-300 px-3 py-2 text-sm text-red-700 hover:bg-red-50 disabled:opacity-50"
        >
          Haushalt verlassen
        </button>
        {activeUpload && (
          <p className="mt-1 text-sm text-gray-600">
            Warte mit dem Verlassen, bis der Upload beendet ist.
          </p>
        )}
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
                <div className="flex flex-wrap items-center justify-end gap-3">
                  <span className="text-gray-600">{householdRoleLabel(member.role)}</span>
                  {isOwner && user?.userId !== undefined && member.user_id !== user.userId && (
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

      <ReceiptUploadSection
        householdId={householdId}
        disabled={activeUpload || activeLeave || showLeaveDialog}
        workflow={receiptUpload}
      />
      <HouseholdReceiptList householdId={householdId} list={receiptList} />
      {showLeaveDialog && (
        <ConfirmDialog
          title="Haushalt verlassen?"
          description={
            <>
              <p>Du verlierst sofort den Zugriff auf diesen Haushalt.</p>
              <p className="mt-3 rounded bg-red-50 px-3 py-2 text-red-800">
                Falls du das letzte Mitglied bist, wird der Haushalt samt Belegen und Bildern
                gelöscht.
              </p>
            </>
          }
          error={leave.isError ? leaveErrorMessage(leave.error) : null}
          isPending={leave.isPending}
          confirmDisabled={activeUpload}
          onClose={() => setShowLeaveDialog(false)}
          onConfirm={confirmLeave}
          triggerRef={leaveButtonRef}
          confirmLabel="Haushalt verlassen"
          pendingLabel="Wird verlassen…"
          confirmClassName="rounded bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
        />
      )}
      {selectedMember && (
        <ConfirmDialog
          title="Haushaltsleitung übergeben?"
          description={
            <p>
              Die Haushaltsleitung wird an{' '}
              <span className="font-medium">{selectedMember.display_name}</span> übergeben. Dein
              eigenes Konto bleibt als Mitglied im Haushalt.
            </p>
          }
          error={transfer.isError ? transferErrorMessage(transfer.error) : null}
          isPending={transfer.isPending}
          onClose={() => setSelectedMember(null)}
          onConfirm={confirmTransfer}
          triggerRef={transferButtonRef}
          confirmLabel="Haushaltsleitung übergeben"
          pendingLabel="Wird übergeben…"
          confirmClassName="rounded bg-black px-4 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-50"
        />
      )}
      {memberToRemove && (
        <ConfirmDialog
          title="Mitglied entfernen?"
          description={
            <p>
              <span className="font-medium">{memberToRemove.display_name}</span> verliert sofort den
              Zugriff auf diesen Haushalt.
            </p>
          }
          error={remove.isError ? removeMemberErrorMessage(remove.error) : null}
          isPending={remove.isPending}
          onClose={() => setMemberToRemove(null)}
          onConfirm={confirmRemoveMember}
          triggerRef={removeMemberButtonRef}
          confirmLabel="Mitglied entfernen"
          pendingLabel="Wird entfernt…"
          confirmClassName="rounded bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
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

function ConfirmDialog({
  title,
  description,
  error,
  isPending,
  confirmDisabled,
  onClose,
  onConfirm,
  triggerRef,
  confirmLabel,
  pendingLabel,
  confirmClassName
}: {
  title: string;
  description: React.ReactNode;
  error: string | null;
  isPending: boolean;
  confirmDisabled?: boolean;
  onClose: () => void;
  onConfirm: () => void;
  triggerRef: React.RefObject<HTMLButtonElement | null>;
  confirmLabel: string;
  pendingLabel: string;
  confirmClassName: string;
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
        {title}
      </h2>
      <div id={descriptionId} className="mt-3 text-sm text-gray-700">
        {description}
      </div>

      {error && (
        <p role="alert" className="mt-3 text-sm text-red-600">
          {error}
        </p>
      )}

      <div className="mt-6 flex flex-col gap-2 sm:flex-row-reverse sm:gap-3">
        <button
          type="button"
          disabled={isPending || confirmDisabled}
          onClick={onConfirm}
          className={confirmClassName}
        >
          {isPending ? pendingLabel : confirmLabel}
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
  const getSessionSignal = useSessionSignal();
  const queryClient = useQueryClient();
  const [copyStatus, setCopyStatus] = useState<{
    invite: InviteCode;
    status: 'copied' | 'error';
  } | null>(null);
  const inviteMutation = useSessionMutation({
    mutationFn: () => requestPrivateResource((options) => createInvite({ householdId }, options)),
    onMutate: () => setCopyStatus(null),
    onError: (error) =>
      handleHouseholdAccessError(queryClient, householdId, error, getSessionSignal())
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

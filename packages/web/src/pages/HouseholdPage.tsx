import { useAuthenticator } from '@aws-amplify/ui-react';
import { HttpError } from '@oazapfts/runtime';
import { useIsMutating, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import {
  createInvite,
  createReceipt,
  type Household,
  type HouseholdList,
  type InviteCode,
  leaveHousehold,
  listMembers,
  listReceipts,
  type Member,
  type MemberList,
  MyRole,
  Role,
  removeMember,
  transferOwnership
} from '@/api';
import { denyHouseholdAccess, householdAccessKey, useHouseholdAccess } from '@/api/householdAccess';
import {
  isPrivateResourceUnavailable,
  readPrivateResource,
  requestPrivateResource
} from '@/api/privateQuery';
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

  const household = useHouseholdAccess(householdId);
  const uploadKey = ['receiptUpload', householdId] as const;
  const leaveKey = ['leaveHousehold', householdId] as const;
  const activeUpload = useIsMutating({ mutationKey: uploadKey, exact: true }) > 0;
  const activeLeave = useIsMutating({ mutationKey: leaveKey, exact: true }) > 0;
  const members = useQuery({
    queryKey: ['householdMembers', householdId],
    queryFn: async ({ signal }) => {
      const data = await readPrivateResource(
        (options) => listMembers({ householdId }, options),
        signal
      );
      signal.throwIfAborted();
      if (data === null) denyHouseholdAccess(queryClient, householdId);
      return data;
    },
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
  const [file, setFile] = useState<File | null>(null);
  const [preparing, setPreparing] = useState(false);
  const preparation = useRef<AbortController | null>(null);
  const submitting = useRef(false);

  useLayoutEffect(() => {
    const controller = new AbortController();
    preparation.current = controller;
    return () => controller.abort();
  }, []);

  function ensureHouseholdAccess(id: string) {
    if (!queryClient.getQueryData(householdAccessKey(id))) {
      throw new Error('Du hast keinen Zugriff mehr auf diesen Haushalt.');
    }
  }

  const upload = useMutation({
    mutationKey: uploadKey,
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
      ensureHouseholdAccess(householdId);
      setPreparing(false);

      // Sign the exact MIME type and size of the file sent to S3.
      const receiptUpload = await requestPrivateResource(
        (options) =>
          createReceipt(
            {
              householdId,
              createReceiptRequest: {
                content_type: prepared.contentType,
                size_bytes: prepared.file.size
              }
            },
            options
          ),
        signal
      );

      // Step 2: unauthenticated PUT — send raw bytes to S3 with all backend-supplied headers.
      signal.throwIfAborted();
      ensureHouseholdAccess(householdId);
      await uploadToS3(receiptUpload, prepared.file, signal);
      return { completedAt: Date.now(), originalSize: file.size, uploadedSize: prepared.file.size };
    },
    onSettled: () => {
      submitting.current = false;
      setPreparing(false);
    },
    onError: (error, { signal }) => {
      if (!signal.aborted && isPrivateResourceUnavailable(error)) {
        denyHouseholdAccess(queryClient, householdId);
      }
    },
    onSuccess: (_, { householdId, signal }) => {
      if (signal.aborted) return;
      setFile(null);
      void queryClient.invalidateQueries({ queryKey: ['receipts', householdId] });
    }
  });

  const receipts = useQuery({
    queryKey: ['receipts', householdId],
    queryFn: async ({ signal }) => {
      const data = await readPrivateResource(
        (options) => listReceipts({ householdId }, options),
        signal
      );
      signal.throwIfAborted();
      if (data === null) denyHouseholdAccess(queryClient, householdId);
      return data;
    },
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
    if (
      !file ||
      !preparation.current ||
      submitting.current ||
      leaveSubmissionRef.current ||
      queryClient.isMutating({ mutationKey: uploadKey, exact: true }) ||
      queryClient.isMutating({ mutationKey: leaveKey, exact: true })
    )
      return;

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
    mutationKey: leaveKey,
    mutationFn: (signal: AbortSignal) =>
      requestPrivateResource((options) => leaveHousehold({ householdId }, options), signal),
    retry: false,
    onError: (error, signal) => {
      if (!signal.aborted && isPrivateResourceUnavailable(error)) {
        denyHouseholdAccess(queryClient, householdId);
      }
    },
    onSuccess: (_, signal) => {
      if (signal.aborted) return;
      preparation.current?.abort();
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
  function refreshAccessAfterMemberMutationError(
    error: Error,
    { signal }: { signal: AbortSignal }
  ) {
    if (signal.aborted || !isPrivateResourceUnavailable(error)) return;
    // A role change or a missing target member can also return 403 or 404.
    if (error instanceof HttpError && (error.status === 403 || error.status === 404)) {
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: householdAccessKey(householdId) }),
        queryClient.invalidateQueries({ queryKey: ['householdMembers', householdId] })
      ]);
    } else {
      denyHouseholdAccess(queryClient, householdId);
    }
  }

  const transfer = useMutation({
    mutationFn: ({ userId, signal }: { userId: string; signal: AbortSignal }) =>
      requestPrivateResource(
        (options) =>
          transferOwnership({ householdId, transferOwnerRequest: { user_id: userId } }, options),
        signal
      ),
    retry: false,
    onError: refreshAccessAfterMemberMutationError,
    onSuccess: async (updatedMembers, { signal }) => {
      if (signal.aborted || !queryClient.getQueryData(householdAccessKey(householdId))) return;
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
  const remove = useMutation({
    mutationFn: ({ userId, signal }: { userId: string; signal: AbortSignal }) =>
      requestPrivateResource((options) => removeMember({ householdId, userId }, options), signal),
    retry: false,
    onError: refreshAccessAfterMemberMutationError,
    onSuccess: async (_, { userId, signal }) => {
      if (signal.aborted || !queryClient.getQueryData(householdAccessKey(householdId))) return;
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
    if (
      leaveSubmissionRef.current ||
      submitting.current ||
      queryClient.isMutating({ mutationKey: leaveKey, exact: true }) ||
      queryClient.isMutating({ mutationKey: uploadKey, exact: true })
    )
      return;

    leaveSubmissionRef.current = true;
    leave.mutate(getUploadSignal());
  }

  function confirmTransfer() {
    if (!selectedMember || transferSubmissionRef.current || transfer.isPending) return;

    transferSubmissionRef.current = true;
    transfer.mutate({ userId: selectedMember.user_id, signal: getUploadSignal() });
  }

  function confirmRemoveMember() {
    if (!memberToRemove || removeMemberSubmissionRef.current || remove.isPending) return;

    removeMemberSubmissionRef.current = true;
    remove.mutate({ userId: memberToRemove.user_id, signal: getUploadSignal() });
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

  const isOwner = household.data.my_role === MyRole.Owner;
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

      <section aria-labelledby="upload-heading">
        <h2 id="upload-heading" className="mb-3 text-lg font-medium">
          Kassenzettel hochladen
        </h2>

        <ReceiptFilePicker
          file={file}
          onChange={handleFileChange}
          disabled={activeUpload || activeLeave || showLeaveDialog}
        />

        {file && (
          <button
            type="button"
            onClick={handleUpload}
            disabled={activeUpload || activeLeave || showLeaveDialog}
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
  const getUploadSignal = useUploadSignal();
  const queryClient = useQueryClient();
  const [copyStatus, setCopyStatus] = useState<{
    invite: InviteCode;
    status: 'copied' | 'error';
  } | null>(null);
  const inviteMutation = useMutation({
    mutationFn: (signal: AbortSignal) =>
      requestPrivateResource((options) => createInvite({ householdId }, options), signal),
    onMutate: () => setCopyStatus(null),
    onError: (error, signal) => {
      if (!signal.aborted && isPrivateResourceUnavailable(error)) {
        denyHouseholdAccess(queryClient, householdId);
      }
    }
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

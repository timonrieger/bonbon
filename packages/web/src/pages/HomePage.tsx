import { useAuthenticator } from '@aws-amplify/ui-react';
import { HttpError } from '@oazapfts/runtime';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { createHousehold, joinHousehold, listHouseholds } from '@/api';
import { useUploadSignal } from '@/components/AuthenticatedSession';
import { householdRoleLabel } from '@/householdRoleLabel';

function joinErrorMessage(error: Error) {
  if (!(error instanceof HttpError)) {
    return 'Beitreten war nicht möglich. Bitte versuche es erneut.';
  }

  switch (error.status) {
    case 404:
      return 'Der Code ist ungültig, abgelaufen oder wurde bereits verwendet.';
    case 409:
      return 'Du bist bereits Mitglied dieses Haushalts.';
    case 422:
      return 'Die Eingabe ist ungültig. Bitte prüfe den Einladungscode.';
    case 429:
      return 'Zu viele Versuche. Bitte probiere es später erneut.';
    default:
      return 'Beitreten war nicht möglich. Bitte versuche es erneut.';
  }
}

export function HomePage() {
  const { user } = useAuthenticator((context) => [context.user]);
  const [name, setName] = useState('');
  const [code, setCode] = useState('');
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const getSessionSignal = useUploadSignal();
  const householdsQueryKey = ['households', user?.userId] as const;
  const households = useQuery({
    queryKey: householdsQueryKey,
    queryFn: ({ signal }) => listHouseholds({ signal }),
    enabled: user?.userId !== undefined
  });
  const create = useMutation({
    mutationFn: ({ householdName, signal }: { householdName: string; signal: AbortSignal }) =>
      createHousehold({ createHouseholdRequest: { name: householdName } }, { signal }),
    onSuccess: (household, { signal }) => {
      if (signal.aborted) return;
      const invalidation = queryClient.invalidateQueries({ queryKey: householdsQueryKey });
      navigate(`/households/${household.id}`);
      return invalidation;
    }
  });
  const join = useMutation({
    mutationFn: ({ inviteCode, signal }: { inviteCode: string; signal: AbortSignal }) =>
      joinHousehold({ joinRequest: { code: inviteCode } }, { signal }),
    retry: false,
    onSuccess: (household, { signal }) => {
      if (signal.aborted) return;
      const invalidation = queryClient.invalidateQueries({ queryKey: householdsQueryKey });
      navigate(`/households/${household.id}`);
      return invalidation;
    }
  });

  return (
    <div className="flex flex-col gap-6">
      <section aria-labelledby="households-heading">
        <h1 id="households-heading" className="mb-3 text-2xl font-semibold">
          Meine Haushalte
        </h1>

        {households.isPending && <p className="text-sm text-gray-600">Haushalte werden geladen…</p>}
        {households.isError && (
          <p role="alert" className="text-sm text-red-600">
            {households.error.message}
          </p>
        )}
        {households.isSuccess && households.data.households.length === 0 && (
          <p className="text-sm text-gray-600">Du bist noch keinem Haushalt beigetreten.</p>
        )}
        {households.isSuccess && households.data.households.length > 0 && (
          <ul className="divide-y divide-gray-200 rounded border border-gray-200">
            {households.data.households.map((household) => (
              <li
                key={household.id}
                className="flex flex-wrap items-center justify-between gap-2 px-3 py-2"
              >
                <Link to={`/households/${household.id}`} className="font-medium underline">
                  {household.name}
                </Link>
                <span className="text-sm text-gray-600">
                  Deine Rolle: {householdRoleLabel(household.my_role)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="join-household-heading">
        <h2 id="join-household-heading" className="mb-3 text-lg font-medium">
          Haushalt beitreten
        </h2>
        <form
          className="flex flex-col gap-2 sm:flex-row sm:items-end"
          onSubmit={(e) => {
            e.preventDefault();
            join.mutate({ inviteCode: code, signal: getSessionSignal() });
          }}
        >
          <div className="flex-1">
            <label htmlFor="invite-code" className="mb-1 block text-sm">
              Einladungscode
            </label>
            <input
              id="invite-code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              className="w-full rounded border px-3 py-2"
            />
          </div>
          <button
            type="submit"
            disabled={join.isPending || code.trim() === ''}
            className="rounded bg-black px-4 py-2 text-white disabled:opacity-50"
          >
            {join.isPending ? 'Wird beigetreten…' : 'Beitreten'}
          </button>
          {join.isError && (
            <p role="alert" className="text-sm text-red-600">
              {joinErrorMessage(join.error)}
            </p>
          )}
        </form>
      </section>

      <section aria-labelledby="create-household-heading">
        <h2 id="create-household-heading" className="mb-3 text-lg font-medium">
          Haushalt erstellen
        </h2>
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate({ householdName: name.trim(), signal: getSessionSignal() });
          }}
        >
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Name des Haushalts"
            className="flex-1 rounded border px-3 py-2"
          />
          <button
            type="submit"
            disabled={create.isPending || name.trim() === ''}
            className="rounded bg-black px-4 py-2 text-white"
          >
            Haushalt erstellen
          </button>
          {create.isError && <p className="text-red-600">{create.error.message}</p>}
        </form>
      </section>
    </div>
  );
}

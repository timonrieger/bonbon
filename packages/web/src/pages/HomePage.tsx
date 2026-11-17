import { useAuthenticator } from '@aws-amplify/ui-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { createHousehold, listHouseholds } from '@/api';

export function HomePage() {
  const { user } = useAuthenticator((context) => [context.user]);
  const [name, setName] = useState('');
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const householdsQueryKey = ['households', user?.userId] as const;
  const households = useQuery({
    queryKey: householdsQueryKey,
    queryFn: () => listHouseholds(),
    enabled: user?.userId !== undefined
  });
  const create = useMutation({
    mutationFn: (householdName: string) =>
      createHousehold({ createHouseholdRequest: { name: householdName } }),
    onSuccess: (household) => {
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
                <span className="text-sm text-gray-600">Deine Rolle: {household.my_role}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="create-household-heading">
        <h2 id="create-household-heading" className="mb-3 text-lg font-medium">
          Haushalt erstellen
        </h2>
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate(name.trim());
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

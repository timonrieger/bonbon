import { useQuery } from '@tanstack/react-query';
import { Link, useParams } from 'react-router';
import { getHousehold } from '@/api';

export function DashboardPage() {
  // biome-ignore lint/style/noNonNullAssertion: the route always has :householdId
  const householdId = useParams().householdId!;
  const household = useQuery({
    queryKey: ['household', householdId],
    queryFn: () => getHousehold({ householdId })
  });

  if (household.isPending) return <p>Laden…</p>;
  if (household.isError) return <p className="text-red-600">{household.error.message}</p>;
  return (
    <div>
      <h1 className="text-2xl font-semibold">Dashboard</h1>
      <p className="mt-1 text-sm text-gray-600">{household.data.name}</p>
      <p className="mt-4">Die Auswertungen für diesen Haushalt sind noch nicht verfügbar.</p>
      <Link to={`/households/${householdId}`} className="mt-4 inline-block text-sm underline">
        Zur Haushaltsseite
      </Link>
    </div>
  );
}

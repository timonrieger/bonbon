import { useQuery } from '@tanstack/react-query';
import { useParams } from 'react-router';
import { getHousehold } from '@/api';

export function HouseholdPage() {
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
      <h1 className="text-2xl font-semibold">{household.data.name}</h1>
      <p className="text-sm text-gray-600">Deine Rolle: {household.data.my_role}</p>
    </div>
  );
}

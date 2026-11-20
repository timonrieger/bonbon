import { type QueryClient, useQuery, useQueryClient } from '@tanstack/react-query';
import { getHousehold, type HouseholdList } from '@/api';
import { readPrivateResource } from '@/api/privateQuery';

export function householdAccessKey(householdId: string) {
  return ['householdAccess', householdId] as const;
}

const householdDataKeys = new Set([
  'household',
  'householdMembers',
  'receipts',
  'receipt',
  'monthlyReport',
  'spendingTrend'
]);

export function denyHouseholdAccess(
  client: QueryClient,
  householdId: string,
  fromAccessQuery = false
) {
  const queryKey = householdAccessKey(householdId);
  if (!fromAccessQuery) {
    void client.cancelQueries({ queryKey, exact: true });
    client.setQueryData(queryKey, null);
  }
  const householdsKey = ['households'];
  void client.cancelQueries({ queryKey: householdsKey });
  client.setQueriesData<HouseholdList>(
    { queryKey: householdsKey },
    (cached) =>
      cached && {
        ...cached,
        households: cached.households.filter((entry) => entry.id !== householdId)
      }
  );
  // Removing a query destroys it and cancels its fetch, even if the caller did not use its signal.
  client.removeQueries({
    predicate: ({ queryKey: key }) =>
      typeof key[0] === 'string' && householdDataKeys.has(key[0]) && key[1] === householdId
  });
}

export function useHouseholdAccess(householdId: string) {
  const client = useQueryClient();
  return useQuery({
    queryKey: householdAccessKey(householdId),
    refetchOnMount: 'always',
    queryFn: async ({ signal }) => {
      const household = await readPrivateResource(
        (options) => getHousehold({ householdId }, options),
        signal
      );
      signal.throwIfAborted();
      if (household === null) denyHouseholdAccess(client, householdId, true);
      return household;
    }
  });
}

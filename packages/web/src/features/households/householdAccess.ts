import type { RequestOpts } from '@oazapfts/runtime';
import type { QueryClient } from '@tanstack/react-query';
import type { HouseholdList } from '@/api';
import { isPrivateResourceUnavailable, readPrivateResource } from '@/api/privateQuery';

export function householdAccessKey(householdId: string) {
  return ['householdAccess', householdId] as const;
}

const householdDataKeys = new Set([
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

// For requests whose denial establishes that the household itself is unavailable.
export async function readHouseholdResource<T>(
  client: QueryClient,
  householdId: string,
  request: (options: RequestOpts) => Promise<T>,
  signal: AbortSignal,
  fromAccessQuery = false
): Promise<T | null> {
  const data = await readPrivateResource(request, signal);
  signal.throwIfAborted();
  if (data === null) denyHouseholdAccess(client, householdId, fromAccessQuery);
  return data;
}

export function handleHouseholdAccessError(
  client: QueryClient,
  householdId: string,
  error: unknown,
  signal: AbortSignal
) {
  if (!signal.aborted && isPrivateResourceUnavailable(error)) {
    denyHouseholdAccess(client, householdId);
  }
}

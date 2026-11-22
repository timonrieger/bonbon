import { useQuery, useQueryClient } from '@tanstack/react-query';
import { getHousehold } from '@/api';
import { householdAccessKey, readHouseholdResource } from './householdAccess';

export function useHouseholdAccess(householdId: string) {
  const client = useQueryClient();
  return useQuery({
    queryKey: householdAccessKey(householdId),
    refetchOnMount: 'always',
    queryFn: ({ signal }) =>
      readHouseholdResource(
        client,
        householdId,
        (options) => getHousehold({ householdId }, options),
        signal,
        true
      )
  });
}

import { useQuery, useQueryClient } from '@tanstack/react-query';
import { listHouseholds, listMembers, Role } from '@/api';
import { requestPrivateResource } from '@/api/privateQuery';
import { denyHouseholdAccess, readHouseholdResource } from '@/features/households/householdAccess';

export function useDeletionPreview(userId: string) {
  const client = useQueryClient();
  // The normal household list can be pruned by cache eviction. Only a fresh
  // server response can establish which households the preview must include.
  const query = useQuery({
    queryKey: ['accountDeletionPreview', userId],
    gcTime: 0,
    queryFn: async ({ signal }) => {
      async function loadPreview() {
        const { households } = await requestPrivateResource(listHouseholds, signal);
        return Promise.all(
          households.map(async ({ id, name }) => {
            const data = await readHouseholdResource(
              client,
              id,
              (options) => listMembers({ householdId: id }, options),
              signal
            );
            if (data === null) return null;
            const membership = data.members.find((member) => member.user_id === userId);
            if (!membership) {
              signal.throwIfAborted();
              denyHouseholdAccess(client, id);
              return null;
            }

            const soleMember = data.members.length === 1;
            return {
              id,
              name,
              consequence: soleMember
                ? 'Dieser Haushalt wird mit allen Belegen und Bildern gelöscht.'
                : 'Deine Mitgliedschaft wird entfernt. Die gemeinsamen Belege bleiben erhalten.',
              transfersOwnership: !soleMember && membership.role === Role.Owner
            };
          })
        );
      }

      let preview = await loadPreview();
      if (preview.includes(null)) preview = await loadPreview();
      return preview;
    }
  });

  const preview = query.data?.filter((entry) => entry !== null) ?? [];
  return {
    preview,
    loading: query.fetchStatus === 'fetching',
    ready: query.isSuccess && query.fetchStatus === 'idle' && preview.length === query.data.length,
    reload: query.refetch
  };
}

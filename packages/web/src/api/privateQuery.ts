import { HttpError, type RequestOpts } from '@oazapfts/runtime';
import { defaults } from '@/api';

const unavailableStatuses = [401, 403, 404];
const authenticationErrors = [
  'NotAuthorizedException',
  'TokenRevokedException',
  'UserNotFoundException',
  'PasswordResetRequiredException',
  'UserNotConfirmedException',
  'RefreshTokenReuseException',
  'UserUnAuthenticatedException'
];

// Store a definitive denial as null so a later transient failure cannot bring
// previously cached private data back into view.
export async function readPrivateResource<T>(
  request: (options: RequestOpts) => Promise<T>,
  signal: AbortSignal
): Promise<T | null> {
  const authenticatedFetch = defaults.fetch;
  if (!authenticatedFetch) throw new Error('The authenticated API client is unavailable.');

  try {
    return await request({
      signal,
      cache: 'no-store',
      fetch: async (input, init) => {
        const response = await authenticatedFetch(input, init);
        // Check access before the generated client decodes the response body.
        if (unavailableStatuses.includes(response.status)) {
          throw new HttpError(response.status, undefined, response.headers);
        }
        return response;
      }
    });
  } catch (error) {
    if (
      (error instanceof HttpError && unavailableStatuses.includes(error.status)) ||
      (error instanceof Error && authenticationErrors.some((name) => error.name.startsWith(name)))
    ) {
      return null;
    }
    throw error;
  }
}

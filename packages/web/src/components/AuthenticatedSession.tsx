import { useAuthenticator } from '@aws-amplify/ui-react';
import {
  QueryClient,
  QueryClientProvider,
  type UseMutationOptions,
  useMutation
} from '@tanstack/react-query';
import {
  createContext,
  type ReactNode,
  useContext,
  useLayoutEffect,
  useRef,
  useState
} from 'react';
import { bindApiSession } from '@/api';

const SessionSignalContext = createContext<(() => AbortSignal) | null>(null);

export function useSessionSignal() {
  const getSignal = useContext(SessionSignalContext);
  if (!getSignal) throw new Error('An authenticated session is required.');
  return getSignal;
}

export function useSessionMutation<TData, TError = Error, TVariables = void, TContext = unknown>({
  mutationFn,
  onMutate,
  onSuccess,
  onError,
  onSettled,
  ...options
}: UseMutationOptions<TData, TError, TVariables, TContext> & {
  mutationFn: NonNullable<UseMutationOptions<TData, TError, TVariables, TContext>['mutationFn']>;
}) {
  const getSessionSignal = useSessionSignal();
  return useMutation<TData, TError, TVariables, TContext>({
    ...options,
    onMutate:
      onMutate &&
      ((...args) => {
        getSessionSignal().throwIfAborted();
        return onMutate(...args);
      }),
    mutationFn: async (...args) => {
      // A paused mutation can resume after a different API session has been bound.
      const signal = getSessionSignal();
      signal.throwIfAborted();
      const result = await mutationFn(...args);
      signal.throwIfAborted();
      return result;
    },
    onSuccess: (...args) => {
      if (!getSessionSignal().aborted) return onSuccess?.(...args);
    },
    onError: (...args) => {
      if (!getSessionSignal().aborted) return onError?.(...args);
    },
    onSettled: (...args) => {
      if (!getSessionSignal().aborted) return onSettled?.(...args);
    }
  });
}

export function AuthenticatedSession({ children }: { children: ReactNode }) {
  const { route, user } = useAuthenticator((context) => [context.route, context.user]);
  if (route !== 'authenticated' || !user) return null;

  return (
    <SessionQueries key={user.userId} subject={user.userId}>
      {children}
    </SessionQueries>
  );
}

function SessionQueries({ children, subject }: { children: ReactNode; subject: string }) {
  const [queryClient] = useState(() => new QueryClient());
  const sessionController = useRef<AbortController | null>(null);
  const [invalidated, setInvalidated] = useState(false);

  useLayoutEffect(() => {
    const controller = new AbortController();
    sessionController.current = controller;
    function invalidate() {
      controller.abort();
      queryClient.clear();
      setInvalidated(true);
    }
    const unbind = bindApiSession({ subject, signal: controller.signal, invalidate });
    // Amplify's default Cognito token storage shares the active user across tabs.
    const lastUserKey = `CognitoIdentityServiceProvider.${import.meta.env.VITE_USER_POOL_CLIENT_ID}.LastAuthUser`;
    function handleStorage(event: StorageEvent) {
      if (
        event.storageArea === window.localStorage &&
        (event.key === null || event.key === lastUserKey)
      ) {
        invalidate();
      }
    }
    window.addEventListener('storage', handleStorage);
    return () => {
      window.removeEventListener('storage', handleStorage);
      unbind();
      controller.abort();
      queryClient.clear();
    };
  }, [queryClient, subject]);

  if (invalidated) {
    return (
      <main className="mx-auto max-w-3xl p-4">
        <p role="alert">Die Anmeldung hat sich geändert. Lade die Seite neu, um fortzufahren.</p>
        <button type="button" className="mt-3 underline" onClick={() => window.location.reload()}>
          Seite neu laden
        </button>
      </main>
    );
  }

  function getSessionSignal() {
    if (!sessionController.current) throw new Error('The authenticated session has not mounted.');
    return sessionController.current.signal;
  }

  return (
    <SessionSignalContext.Provider value={getSessionSignal}>
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </SessionSignalContext.Provider>
  );
}

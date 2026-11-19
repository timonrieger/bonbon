import { useAuthenticator } from '@aws-amplify/ui-react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  createContext,
  type ReactNode,
  useContext,
  useLayoutEffect,
  useRef,
  useState
} from 'react';
import { bindApiSession } from '@/api';

const UploadSignalContext = createContext<(() => AbortSignal) | null>(null);

export function useUploadSignal() {
  const getSignal = useContext(UploadSignalContext);
  if (!getSignal) throw new Error('Receipt uploads require an authenticated session.');
  return getSignal;
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
  const uploads = useRef<AbortController | null>(null);
  const [invalidated, setInvalidated] = useState(false);

  useLayoutEffect(() => {
    const controller = new AbortController();
    uploads.current = controller;
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

  function getUploadSignal() {
    if (!uploads.current) throw new Error('The authenticated session has not mounted.');
    return uploads.current.signal;
  }

  return (
    <UploadSignalContext.Provider value={getUploadSignal}>
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </UploadSignalContext.Provider>
  );
}

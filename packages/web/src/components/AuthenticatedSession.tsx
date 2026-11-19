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

const UploadSignalContext = createContext<(() => AbortSignal) | null>(null);

export function useUploadSignal() {
  const getSignal = useContext(UploadSignalContext);
  if (!getSignal) throw new Error('Receipt uploads require an authenticated session.');
  return getSignal;
}

export function AuthenticatedSession({ children }: { children: ReactNode }) {
  const { route, user } = useAuthenticator((context) => [context.route, context.user]);
  if (route !== 'authenticated' || !user) return null;

  return <SessionQueries key={user.userId}>{children}</SessionQueries>;
}

function SessionQueries({ children }: { children: ReactNode }) {
  const [queryClient] = useState(() => new QueryClient());
  const uploads = useRef<AbortController | null>(null);

  useLayoutEffect(() => {
    const controller = new AbortController();
    uploads.current = controller;
    return () => {
      controller.abort();
      queryClient.clear();
    };
  }, [queryClient]);

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

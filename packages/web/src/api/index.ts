// Import API functions from here, never from client.gen.ts directly.
import { fetchAuthSession } from 'aws-amplify/auth';
import { defaults } from './client.gen';

defaults.baseUrl = import.meta.env.VITE_API_URL;

type ApiSession = {
  subject: string;
  signal: AbortSignal;
  invalidate: () => void;
};

let currentSession: ApiSession | undefined;

export function bindApiSession(session: ApiSession) {
  currentSession = session;
  return () => {
    if (currentSession === session) currentSession = undefined;
  };
}

defaults.fetch = async (input, init) => {
  const session = currentSession;
  if (!session) throw new DOMException('No authenticated API session', 'AbortError');
  const signal = init?.signal ? AbortSignal.any([session.signal, init.signal]) : session.signal;
  signal.throwIfAborted();
  const { tokens } = await fetchAuthSession();
  signal.throwIfAborted();

  // Check the same token that will authorize the request.
  const token = tokens?.idToken;
  if (!token || token.payload.sub !== session.subject || currentSession !== session) {
    if (currentSession === session) session.invalidate();
    throw new DOMException('The authenticated identity changed', 'AbortError');
  }
  const headers = new Headers(init?.headers);
  headers.set('Authorization', token.toString());
  const response = await fetch(input, { ...init, signal, headers });
  signal.throwIfAborted();
  return response;
};

export * from './client.gen';

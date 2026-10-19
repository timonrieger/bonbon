// Import API functions from here, never from client.gen.ts directly.
import { fetchAuthSession } from 'aws-amplify/auth';
import { defaults } from './client.gen';

defaults.baseUrl = import.meta.env.VITE_API_URL;

// Every request carries the Cognito ID token; API Gateway rejects requests without it.
defaults.fetch = async (input, init) => {
  const { tokens } = await fetchAuthSession();
  const headers = new Headers(init?.headers);
  if (tokens?.idToken) headers.set('Authorization', tokens.idToken.toString());
  return fetch(input, { ...init, headers });
};

export * from './client.gen';

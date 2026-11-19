import '@aws-amplify/ui-react/styles.css';
import './index.css';

import { Authenticator } from '@aws-amplify/ui-react';
import { Amplify } from 'aws-amplify';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router';
import { App } from '@/App';
import { AuthenticatedSession } from '@/components/AuthenticatedSession';

Amplify.configure({
  Auth: {
    Cognito: {
      userPoolId: import.meta.env.VITE_USER_POOL_ID,
      userPoolClientId: import.meta.env.VITE_USER_POOL_CLIENT_ID
    }
  }
});

// biome-ignore lint/style/noNonNullAssertion: index.html always has #root
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Authenticator>
      <AuthenticatedSession>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </AuthenticatedSession>
    </Authenticator>
  </StrictMode>
);

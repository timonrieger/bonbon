import { Authenticator, useAuthenticator } from '@aws-amplify/ui-react';
import { useLayoutEffect, useRef, useState } from 'react';
import { BrowserRouter, Link, Route, Routes } from 'react-router';
import { AuthenticatedSession } from '@/components/AuthenticatedSession';
import { DeleteAccountDialog } from '@/components/DeleteAccountDialog';
import { DashboardPage } from '@/pages/DashboardPage';
import { HomePage } from '@/pages/HomePage';
import { HouseholdPage } from '@/pages/HouseholdPage';
import { ReceiptPage } from '@/pages/ReceiptPage';

function App({ setDeletionAccepted }: { setDeletionAccepted: (accepted: boolean) => void }) {
  const { signOut, user } = useAuthenticator((context) => [context.user]);
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  // Users sign in with their email (UsernameAttributes: email), so the login id is the email.
  const userEmail = user?.signInDetails?.loginId ?? '';

  // Ref to the trigger button so focus returns there when the dialog closes.
  const deleteButtonRef = useRef<HTMLButtonElement>(null);

  // App mounts inside a new authenticated session, after the signed-out notice.
  useLayoutEffect(() => {
    setDeletionAccepted(false);
  }, [setDeletionAccepted]);

  return (
    <div className="mx-auto max-w-3xl p-4">
      <header className="mb-6 flex items-center justify-between">
        <Link to="/" className="text-xl font-semibold">
          Bonbon
        </Link>
        <div className="flex items-center gap-4">
          <button
            ref={deleteButtonRef}
            type="button"
            onClick={() => setShowDeleteDialog(true)}
            className="text-sm text-gray-400 underline hover:text-gray-700"
          >
            Konto löschen
          </button>
          <button type="button" onClick={signOut} className="text-sm underline">
            Abmelden
          </button>
        </div>
      </header>

      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/households/:householdId" element={<HouseholdPage />} />
        <Route path="/households/:householdId/receipts/:receiptId" element={<ReceiptPage />} />
        <Route path="/households/:householdId/dashboard" element={<DashboardPage />} />
      </Routes>

      {showDeleteDialog && user && (
        <DeleteAccountDialog
          userId={user.userId}
          userEmail={userEmail}
          triggerRef={deleteButtonRef}
          onClose={() => setShowDeleteDialog(false)}
          onAccepted={() => {
            setDeletionAccepted(true);
            signOut();
          }}
        />
      )}
    </div>
  );
}

export function Bonbon() {
  const [deletionAccepted, setDeletionAccepted] = useState(false);

  return (
    <>
      <div role="status" className={deletionAccepted ? 'mx-auto max-w-3xl p-4' : undefined}>
        {deletionAccepted && (
          <p className="rounded bg-green-50 p-3 text-sm text-green-900">
            Dein Löschauftrag wurde angenommen. Die Löschung wird im Hintergrund verarbeitet.
          </p>
        )}
      </div>
      {deletionAccepted && (
        <div className="mx-auto max-w-3xl px-4">
          <button
            type="button"
            className="text-sm underline"
            onClick={() => setDeletionAccepted(false)}
          >
            Meldung schliessen
          </button>
        </div>
      )}
      <Authenticator>
        <AuthenticatedSession>
          <BrowserRouter>
            <App setDeletionAccepted={setDeletionAccepted} />
          </BrowserRouter>
        </AuthenticatedSession>
      </Authenticator>
    </>
  );
}
